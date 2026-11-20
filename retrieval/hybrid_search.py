import numpy as np
import pickle
import os
import threading
import torch
import re
import gc
from time import perf_counter
from rank_bm25 import BM25Okapi
from retrieval.chromadb_client import get_collection, get_database_path
from retrieval.embedder import activate_embedding_models, park_embedding_models
from sentence_transformers import CrossEncoder
from core.debug_trace import debug_dump, debug_enabled
from core.telemetry import record_counter, record_duration

# The reranker was downloaded during setup. Never make a network request while
# serving a legal question; a temporary connection failure must not stop RAG.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _internal_print(message: str) -> None:
    if debug_enabled():
        print(message)

# Prefer CUDA on this workstation while keeping an explicit CPU fallback.
_DEFAULT_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
_DEVICE = os.getenv("RERANKER_DEVICE", _DEFAULT_DEVICE).strip().lower()
if _DEVICE == "cuda" and not torch.cuda.is_available():
    _DEVICE = "cpu"

# Keep CrossEncoder batches deliberately small on 8 GiB workstations.  The
# sentence-transformers default can score the whole candidate pool at once,
# which creates a large temporary activation spike at max_length=1024.
try:
    _RERANKER_BATCH_SIZE = max(1, int(os.getenv("RERANKER_BATCH_SIZE", "2")))
except ValueError:
    _RERANKER_BATCH_SIZE = 2
try:
    _RERANKER_CPU_BATCH_SIZE = max(
        1, int(os.getenv("RERANKER_CPU_BATCH_SIZE", "1"))
    )
except ValueError:
    _RERANKER_CPU_BATCH_SIZE = 1
_RERANKER_CPU_FALLBACK_ENABLED = os.getenv(
    "RERANKER_CPU_FALLBACK", "true"
).strip().lower() in {"1", "true", "yes", "on"}

_internal_print(
    f"[Reranker] Sử dụng device ưu tiên: {_DEVICE.upper()} "
    f"(batch={_RERANKER_BATCH_SIZE}, CPU fallback="
    f"{'ON' if _RERANKER_CPU_FALLBACK_ENABLED else 'OFF'})"
)

collection = None
_collection_lock = threading.Lock()


# Khởi tạo bộ nhớ cache cho BM25
_BM25_INDEXES = {}
DEFAULT_CACHE_DIR = get_database_path()
_bm25_lock = threading.Lock()

# Khởi tạo CrossEncoder Reranker (BAAI/bge-reranker-v2-m3)
_RERANKER = None
_reranker_lock = threading.Lock()
_RERANKER_PARKED = False
_RERANKER_FORCE_CPU = False
_RERANKER_ACTIVE_DEVICE = None


def _is_cuda_oom(error: BaseException) -> bool:
    """Recognize PyTorch/CUDA allocation failures without matching unrelated errors."""
    oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", ())
    if oom_type and isinstance(error, oom_type):
        return True
    message = str(error or "").casefold()
    return any(
        marker in message
        for marker in (
            "cuda error: out of memory",
            "cuda out of memory",
            "cudaerrormemoryallocation",
            "cuda_error_out_of_memory",
        )
    )


def _cleanup_cuda_cache() -> None:
    """Release dead tensors after a failed CUDA allocation.

    Do not synchronize here: after an asynchronous CUDA failure, synchronize()
    can merely re-raise the same stale error and prevent cleanup.
    """
    gc.collect()
    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
        except (AttributeError, RuntimeError):
            pass


def _model_to_float32(model) -> None:
    """Make a parked fp16 GPU model safe for CPU inference."""
    inner_model = getattr(model, "model", None)
    if inner_model is not None and hasattr(inner_model, "float"):
        inner_model.float()


def _park_reranker_for_embedding() -> None:
    """Ensure vector embedding and CrossEncoder never occupy VRAM together."""
    global _RERANKER_PARKED, _RERANKER_ACTIVE_DEVICE
    with _reranker_lock:
        if _RERANKER is None or _RERANKER_ACTIVE_DEVICE != "cuda":
            record_counter("resource_park_noop_count")
            return
        try:
            started = perf_counter()
            _RERANKER.to("cpu")
            _RERANKER_PARKED = True
            _RERANKER_ACTIVE_DEVICE = "cpu"
            record_counter("reranker_gpu_to_cpu")
            record_duration("reranker_gpu_to_cpu", perf_counter() - started)
        except (AttributeError, RuntimeError) as error:
            _internal_print(
                "[Lỗi Reranker] Không thể tạm chuyển model về CPU trước "
                f"embedding: {error}"
            )
            return
    _cleanup_cuda_cache()


def get_active_collection():
    """Activate embeddings only after the CrossEncoder has left VRAM."""
    global collection
    _park_reranker_for_embedding()
    with _collection_lock:
        if collection is None:
            collection = get_collection()
        else:
            activate_embedding_models()
        return collection


def _load_cross_encoder(target_device: str):
    reranker_model = os.getenv(
        "RERANKER_MODEL",
        "BAAI/bge-reranker-v2-m3",
    ).strip()
    _internal_print(
        f"Đang tải CrossEncoder Reranker ({reranker_model}) "
        f"trên {target_device.upper()}..."
    )
    model_kwargs = (
        {"torch_dtype": torch.float16} if target_device == "cuda" else {}
    )
    return CrossEncoder(
        reranker_model,
        max_length=1024,
        device=target_device,
        model_kwargs=model_kwargs,
        local_files_only=True,
    )


def get_reranker():
    global _RERANKER, _RERANKER_PARKED
    global _RERANKER_FORCE_CPU, _RERANKER_ACTIVE_DEVICE
    with _reranker_lock:
        target_device = "cpu" if _RERANKER_FORCE_CPU else _DEVICE
        if _RERANKER is None:
            try:
                _RERANKER = _load_cross_encoder(target_device)
                _RERANKER_PARKED = False
                _RERANKER_ACTIVE_DEVICE = target_device
            except Exception as error:
                if (
                    target_device == "cuda"
                    and _RERANKER_CPU_FALLBACK_ENABLED
                    and _is_cuda_oom(error)
                ):
                    _internal_print(
                        "[Reranker] CUDA OOM khi nạp model; chuyển cố định sang CPU "
                        "cho phần còn lại của tiến trình."
                    )
                    _RERANKER = None
                    _RERANKER_FORCE_CPU = True
                    _RERANKER_ACTIVE_DEVICE = None
                    _cleanup_cuda_cache()
                    try:
                        _RERANKER = _load_cross_encoder("cpu")
                        _RERANKER_PARKED = False
                        _RERANKER_ACTIVE_DEVICE = "cpu"
                    except Exception as cpu_error:
                        _RERANKER = None
                        _RERANKER_PARKED = False
                        _RERANKER_ACTIVE_DEVICE = None
                        _internal_print(
                            "[Lỗi Reranker] Không thể nạp model CPU sau CUDA OOM: "
                            f"{cpu_error}"
                        )
                        return None
                else:
                    _RERANKER = None
                    _RERANKER_PARKED = False
                    _RERANKER_ACTIVE_DEVICE = None
                    _internal_print(
                        f"[Lỗi Reranker] Không thể nạp model local: {error}"
                    )
                    return None
        elif _RERANKER_PARKED:
            if target_device == "cpu":
                # The model is already parked in CPU RAM.  CPU fallback must not
                # try to send it back to the GPU on the next retrieval query.
                _model_to_float32(_RERANKER)
                _RERANKER_PARKED = False
                _RERANKER_ACTIVE_DEVICE = "cpu"
            else:
                try:
                    started = perf_counter()
                    _RERANKER.to(target_device)
                    _RERANKER_PARKED = False
                    _RERANKER_ACTIVE_DEVICE = target_device
                    record_counter("reranker_cpu_to_gpu")
                    record_duration(
                        "reranker_cpu_to_gpu",
                        perf_counter() - started,
                    )
                except (AttributeError, RuntimeError) as error:
                    if (
                        _RERANKER_CPU_FALLBACK_ENABLED
                        and _is_cuda_oom(error)
                    ):
                        _internal_print(
                            "[Reranker] CUDA OOM khi chuyển model từ RAM lên GPU; "
                            "giữ model trên CPU cho phần còn lại của tiến trình."
                        )
                        _RERANKER_FORCE_CPU = True
                        _model_to_float32(_RERANKER)
                        _RERANKER_PARKED = False
                        _RERANKER_ACTIVE_DEVICE = "cpu"
                        _cleanup_cuda_cache()
                    else:
                        _internal_print(
                            "[Lỗi Reranker] Không thể chuyển model từ RAM lên "
                            f"{target_device.upper()}: {error}"
                        )
                        return None
    return _RERANKER


def _force_reranker_to_cpu_after_oom() -> object | None:
    """Recover from a predict-time CUDA OOM and disable GPU reranking for this run."""
    global _RERANKER_FORCE_CPU, _RERANKER_PARKED, _RERANKER_ACTIVE_DEVICE
    with _reranker_lock:
        if _RERANKER is None:
            return None
        try:
            started = perf_counter()
            _RERANKER.to("cpu")
            _model_to_float32(_RERANKER)
            record_counter("reranker_gpu_to_cpu")
            record_duration("reranker_gpu_to_cpu", perf_counter() - started)
        except (AttributeError, RuntimeError) as error:
            _internal_print(
                f"[Lỗi Reranker] Không thể phục hồi model trên CPU sau CUDA OOM: {error}"
            )
            return None
        _RERANKER_FORCE_CPU = True
        _RERANKER_PARKED = False
        _RERANKER_ACTIVE_DEVICE = "cpu"
        recovered = _RERANKER
    _cleanup_cuda_cache()
    return recovered


def release_retrieval_resources() -> dict[str, int | bool]:
    """Park retrieval models in CPU RAM once evidence collection is complete.

    BM25 stays in RAM while the embedding model and CrossEncoder leave VRAM.
    This is safe to call repeatedly because an audit may request one additional
    retrieval round.
    """
    global _RERANKER_PARKED, _RERANKER_ACTIVE_DEVICE
    with _reranker_lock:
        had_reranker = _RERANKER is not None
        # Backward-compatible state inference: older callers/tests may inject an
        # already-loaded reranker without setting _RERANKER_ACTIVE_DEVICE.  Under
        # the CUDA profile that object historically lived on GPU, so preserve the
        # original park -> restore contract unless CPU fallback was explicitly
        # activated after an OOM.
        should_park_gpu_reranker = bool(
            had_reranker
            and not _RERANKER_FORCE_CPU
            and _DEVICE == "cuda"
            and _RERANKER_ACTIVE_DEVICE in {None, "cuda"}
        )
        if should_park_gpu_reranker:
            try:
                started = perf_counter()
                _RERANKER.to("cpu")
                _RERANKER_PARKED = True
                _RERANKER_ACTIVE_DEVICE = "cpu"
                record_counter("reranker_gpu_to_cpu")
                record_duration("reranker_gpu_to_cpu", perf_counter() - started)
            except (AttributeError, RuntimeError):
                _RERANKER_PARKED = False
        elif had_reranker and _RERANKER_FORCE_CPU:
            _RERANKER_PARKED = False
            _RERANKER_ACTIVE_DEVICE = "cpu"
            record_counter("resource_park_noop_count")
        else:
            record_counter("resource_park_noop_count")
    with _bm25_lock:
        bm25_index_count = len(_BM25_INDEXES)
    embedding_model_count = park_embedding_models()

    _cleanup_cuda_cache()
    released = {
        "reranker": had_reranker,
        "bm25_indexes": bm25_index_count,
        "embedding_models": embedding_model_count,
    }
    _internal_print(
        f"[Retrieval] Đã chuyển embedding/reranker về RAM; giữ "
        f"{bm25_index_count} BM25 index trong RAM."
    )
    return released


def _structured_candidate_text(document: str, metadata: dict) -> str:
    """Combine statutory hierarchy with content for lexical and rerank search."""

    headings = [
        str(metadata.get("tên_luật", "")).strip(),
        (
            f"Điều {str(metadata.get('số_điều', '')).strip()}"
            if str(metadata.get("số_điều", "")).strip()
            else ""
        ),
        str(metadata.get("tiêu_đề_điều", "")).strip(),
        str(metadata.get("mục", "")).strip(),
    ]
    prefix = " | ".join(value for value in headings if value)
    body = str(document or "").strip()
    return f"{prefix}\n{body}" if prefix else body


def get_bm25_index(doc_type):
    """
    Tạo hoặc tải BM25 Index cho một loại văn bản cụ thể (luật, bản_án, án_lệ).
    """
    with _bm25_lock:
        if doc_type in _BM25_INDEXES:
            return _BM25_INDEXES[doc_type]
            
        cache_dir = os.path.abspath(os.getenv("CHROMA_DB_PATH", DEFAULT_CACHE_DIR))
        # Separate cache name prevents silently reusing the old content-only
        # index after legal headings became part of retrieval text.
        cache_file = os.path.join(
            cache_dir,
            f"bm25_structured_v1_{doc_type}.pkl",
        )
        
        # 1. Thử tải từ file cache
        if os.path.exists(cache_file) and os.path.getsize(cache_file) > 0:
            _internal_print(f"Đang tải BM25 cache cho dữ liệu {doc_type.upper()}...")
            try:
                with open(cache_file, "rb") as f:
                    _BM25_INDEXES[doc_type] = pickle.load(f)
                return _BM25_INDEXES[doc_type]
            except Exception as e:
                _internal_print(f"Lỗi đọc cache BM25, tiến hành khởi tạo lại: {e}")

    # 2. Khởi tạo mới nếu chưa có cache
    _internal_print(f"Đang khởi tạo BM25 Index cho dữ liệu {doc_type.upper()}...")
    where_filter = {"loại": {"$in": ["luật", "nghị định", "thông tư", "nghị quyết"]}} if doc_type == "luật" else {"loại": doc_type}
    
    try:
        active_collection = get_active_collection()
        if active_collection is None:
            return None, [], [], []
        all_data = active_collection.get(where=where_filter, include=["documents", "metadatas"])
    except Exception as e:
        _internal_print(f"Lỗi khi truy xuất ChromaDB: {e}")
        return None, [], [], []

    docs = all_data.get('documents', [])
    metas = all_data.get('metadatas', [])
    ids = all_data.get('ids', [])
    
    if not docs:
        _BM25_INDEXES[doc_type] = (None, [], [], [])
        return _BM25_INDEXES[doc_type]
        
    # Tokenize bằng pyvi.ViTokenizer (giữ nguyên các cụm từ ghép tiếng Việt)
    try:
        from pyvi import ViTokenizer
        _internal_print(f"Đang tokenize BM25 bằng pyvi.ViTokenizer cho {len(docs)} documents...")
        tokenized_corpus = [
            ViTokenizer.tokenize(
                _structured_candidate_text(doc, meta)
            ).lower().split()
            for doc, meta in zip(docs, metas)
        ]
    except ImportError:
        _internal_print("Cảnh báo: pyvi chưa được cài đặt. Dùng whitespace tokenizer.")
        tokenized_corpus = [
            _structured_candidate_text(doc, meta).lower().split()
            for doc, meta in zip(docs, metas)
        ]
        
    bm25 = BM25Okapi(tokenized_corpus)
    
    _BM25_INDEXES[doc_type] = (bm25, docs, metas, ids)
    
    # 3. Lưu bộ nhớ đệm
    try:
        with open(cache_file, "wb") as f:
            pickle.dump(_BM25_INDEXES[doc_type], f)
        _internal_print(f"Đã lưu cache BM25 cho {doc_type.upper()}.")
    except Exception as e:
        _internal_print(f"Không thể lưu cache BM25: {e}")
        
    return _BM25_INDEXES[doc_type]

def reciprocal_rank_fusion(vector_results, bm25_results, k=60):
    """Kết hợp kết quả bằng Reciprocal Rank Fusion (RRF)"""
    rrf_scores = {}
    
    for rank, (doc_id, doc, meta) in enumerate(vector_results):
        if doc_id not in rrf_scores:
            rrf_scores[doc_id] = {"score": 0.0, "doc": doc, "meta": meta}
        rrf_scores[doc_id]["score"] += 1.0 / (k + rank + 1)
        
    for rank, (doc_id, doc, meta) in enumerate(bm25_results):
        if doc_id not in rrf_scores:
            rrf_scores[doc_id] = {"score": 0.0, "doc": doc, "meta": meta}
        rrf_scores[doc_id]["score"] += 1.0 / (k + rank + 1)
        
    sorted_results = sorted(rrf_scores.values(), key=lambda x: x["score"], reverse=True)
    return sorted_results


def rerank_candidates(query: str, candidates: list[dict], top_k: int = 7) -> list[dict]:
    """Deduplicate and rerank candidates with bounded GPU memory usage.

    Vector embeddings leave VRAM before the CrossEncoder starts.  A genuine
    CUDA allocation failure triggers one CPU retry, then GPU reranking remains
    disabled for the rest of the process so a later CUDA call does not inherit
    the failed allocator state.
    """
    unique: list[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        document = str(candidate.get("doc", ""))
        metadata = candidate.get("meta", {}) or {}
        key = (
            f"{metadata.get('tên_luật', '')}|"
            f"{metadata.get('số_điều', '')}|{document}"
        )
        if not document or key in seen:
            continue
        seen.add(key)
        unique.append(dict(candidate))

    if not unique:
        return []

    # The vector query has completed.  Do not keep the embedding model beside
    # the CrossEncoder on an 8 GiB GPU.
    parked_embeddings = park_embedding_models()
    if parked_embeddings:
        _internal_print(
            f"[Retrieval] Đã tạm chuyển {parked_embeddings} embedding model "
            "về RAM trước reranking."
        )
    _cleanup_cuda_cache()

    cross_inp = [
        [
            query,
            _structured_candidate_text(
                item["doc"],
                item.get("meta", {}) or {},
            ),
        ]
        for item in unique
    ]
    cross_scores = None
    try:
        reranker = get_reranker()
        if reranker is None:
            raise RuntimeError("Reranker local chưa sẵn sàng")
        batch_size = (
            _RERANKER_CPU_BATCH_SIZE
            if _RERANKER_FORCE_CPU
            else _RERANKER_BATCH_SIZE
        )
        cross_scores = reranker.predict(cross_inp, batch_size=batch_size)
    except Exception as error:
        if (
            _RERANKER_CPU_FALLBACK_ENABLED
            and _is_cuda_oom(error)
        ):
            _internal_print(
                "[Reranker] CUDA OOM khi chấm điểm; giải phóng CUDA và retry "
                "một lần trên CPU."
            )
            reranker = _force_reranker_to_cpu_after_oom()
            if reranker is not None:
                try:
                    cross_scores = reranker.predict(
                        cross_inp,
                        batch_size=_RERANKER_CPU_BATCH_SIZE,
                    )
                    _internal_print(
                        "[Reranker] CPU fallback thành công; tiếp tục dùng CPU "
                        "cho các truy vấn còn lại."
                    )
                except Exception as cpu_error:
                    cross_scores = None
                    _internal_print(
                        "[Lỗi Reranker] CPU fallback thất bại; giữ thứ tự RRF. "
                        f"Lỗi: {cpu_error}"
                    )
            else:
                cross_scores = None
        else:
            _internal_print(
                "[Lỗi Reranker] Không thể chấm điểm bằng mô hình; "
                f"giữ thứ tự ứng viên. Lỗi: {error}"
            )

    try:
        if cross_scores is not None:
            for item, score in zip(unique, cross_scores):
                item["rerank_score"] = float(score)
            unique.sort(
                key=lambda item: item["rerank_score"],
                reverse=True,
            )
    finally:
        # Drop activation/output references immediately.  This matters after an
        # OOM because the next pipeline stage may load an 8B model.
        del cross_inp
        if cross_scores is not None:
            del cross_scores
        _cleanup_cuda_cache()

    return unique[:top_k]


def hybrid_query(query: str, doc_type: str, top_k: int = 7, threshold: float = 0.0, target_date: str = None, is_transitional: bool = False, named_document: str = None, candidate_k: int | None = None, article_filter: str | int | None = None):
    """
    Quy trình tra cứu: Vector + BM25 -> RRF Fusion -> Rerank (BGE-M3) -> Threshold filter
    """
    active_collection = get_active_collection()
    if active_collection is None:
        return []
        
    # ``candidate_k`` tách ngân sách recall khỏi số kết quả sau rerank. Caller
    # cũ không truyền tham số này vẫn giữ nguyên hành vi top_k * 3.
    fetch_k = max(top_k, int(candidate_k)) if candidate_k is not None else top_k * 3
        
    # 1. Vector Search (ChromaDB)
    type_filter = {"loại": {"$in": ["luật", "nghị định", "thông tư", "nghị quyết"]}} if doc_type == "luật" else {"loại": doc_type}
    normalized_article = str(article_filter or "").strip()
    base_filter = (
        {"$and": [type_filter, {"số_điều": {"$eq": normalized_article}}]}
        if normalized_article
        else type_filter
    )
    if named_document:
        named_document = str(named_document).strip()
        
    if doc_type == "luật":
        if target_date:
            try:
                parts = target_date.split("-")
                if len(parts) == 1:
                    start_date = int(f"{parts[0]}0101")
                    end_date = int(f"{parts[0]}1231")
                elif len(parts) == 2:
                    start_date = int(f"{parts[0]}{parts[1]}01")
                    end_date = int(f"{parts[0]}{parts[1]}31")
                else:
                    date_int = int(target_date.replace("-", ""))
                    start_date = date_int
                    end_date = date_int
                    
                if is_transitional:
                    where_filter = {
                        "$and": [
                            base_filter,
                            {
                                "$or": [
                                    {"$and": [{"effective_from": {"$lte": end_date}}, {"effective_to": {"$gte": start_date}}]},
                                    {"trang_thai": {"$in": ["con_hieu_luc", "còn hiệu lực"]}}
                                ]
                            }
                        ]
                    }
                else:
                    where_filter = {
                        "$and": [
                            base_filter,
                            {"effective_from": {"$lte": end_date}},
                            {"effective_to": {"$gte": start_date}}
                        ]
                    }
            except Exception:
                where_filter = base_filter
        elif named_document:
            # A document named by the user may be expired today but still be the
            # only statute the question asks to interpret.
            where_filter = base_filter
        else:
            where_filter = {
                "$and": [
                    base_filter,
                    {"trang_thai": {"$in": ["con_hieu_luc", "còn hiệu lực"]}}
                ]
            }
    else:
        where_filter = base_filter

    debug_dump(
        "HYBRID QUERY :: TEMPORAL FILTER",
        {
            "query": query,
            "doc_type": doc_type,
            "target_date": target_date,
            "is_transitional": is_transitional,
            "named_document": named_document,
            "article_filter": normalized_article or None,
            "where_filter": where_filter,
        },
    )
    
    try:
        v_results = active_collection.query(
            query_texts=[query],
            n_results=fetch_k * 5 if named_document else fetch_k,  # Fetch more if we need to filter manually
            where=where_filter
        )
    except Exception:
        v_results = {'documents': [], 'metadatas': [], 'ids': []}
    
    vector_list = []
    if v_results.get('documents') and len(v_results['documents']) > 0:
        for idx, doc in enumerate(v_results['documents'][0]):
            doc_id = v_results['ids'][0][idx]
            meta = v_results['metadatas'][0][idx]
            
            # Manual filter for named_document in Vector results
            if named_document and doc_type == "luật":
                t_luat = str(meta.get("tên_luật", "")).lower()
                if named_document.lower() not in t_luat:
                    continue
                    
            vector_list.append((doc_id, doc, meta))
            if len(vector_list) >= fetch_k:
                break
            
    # 2. BM25 Search (Keyword)
    bm25_data = get_bm25_index(doc_type)
    bm25_list = []
    if bm25_data and bm25_data[0] is not None:
        bm25, docs, metas, ids = bm25_data
        try:
            from pyvi import ViTokenizer
            tokenized_query = ViTokenizer.tokenize(query).lower().split()
        except ImportError:
            tokenized_query = query.lower().split()
        
        doc_scores = bm25.get_scores(tokenized_query)
        sorted_indices = np.argsort(doc_scores)[::-1]
        
        for idx in sorted_indices:
            if doc_scores[idx] <= 0:
                break
                
            meta = metas[idx]
            if normalized_article and str(meta.get("số_điều", "")).strip() != normalized_article:
                continue
            # Lọc luật hết hiệu lực trong kết quả BM25
            if doc_type == "luật":
                if named_document:
                    # Tên văn bản là một điều kiện bổ sung, không được vô hiệu hóa mốc thời gian.
                    t_luat = str(meta.get("tên_luật", "")).lower()
                    if named_document.lower() not in t_luat:
                        continue

                if target_date:
                    try:
                        parts = target_date.split("-")
                        if len(parts) == 1:
                            date_int = int(f"{parts[0]}0101")
                        elif len(parts) == 2:
                            date_int = int(f"{parts[0]}{parts[1]}01")
                        else:
                            date_int = int(target_date.replace("-", ""))
                        
                        ef = int(meta.get("effective_from", 19000101))
                        et = int(meta.get("effective_to", 99991231))
                        trang_thai = str(meta.get("trang_thai", "")).lower()
                        is_active = (trang_thai == "con_hieu_luc" or trang_thai == "còn hiệu lực")
                        if is_transitional:
                            if not ((ef <= date_int <= et) or is_active):
                                continue
                        else:
                            if not (ef <= date_int <= et):
                                continue
                    except Exception:
                        pass
                elif not named_document:
                    trang_thai = str(meta.get("trang_thai", "")).lower()
                    if trang_thai != "con_hieu_luc" and trang_thai != "còn hiệu lực":
                        continue
            
            bm25_list.append((ids[idx], docs[idx], meta))
            if len(bm25_list) >= fetch_k:
                break
                
    # 3. Fusion (RRF)
    fused_results = reciprocal_rank_fusion(vector_list, bm25_list)
    
    if not fused_results:
        return []
        
    # 4. Rerank (Cross-Encoder) and return the strongest candidates.
    return rerank_candidates(query, fused_results, top_k=top_k)
