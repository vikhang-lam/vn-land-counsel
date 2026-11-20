from retrieval.chromadb_client import get_collection
from retrieval.hybrid_search import hybrid_query, rerank_candidates
from core.article_guard import article_request_warning
from core.debug_trace import debug_dump
from core.temporal_guard import get_active_question, sanitize_active_temporal_arguments, target_date_to_int
from core.terminal_ui import panel, progress
from collections import Counter
from difflib import SequenceMatcher
from math import log
import re
import unicodedata

collection = get_collection()

_TITLE_STOPWORDS = frozenset(
    {
        "va", "ve", "theo", "duoc", "quy", "dinh", "nhu", "the", "nao", "cua", "trong", "cho",
        "tai", "la", "nhung", "cac", "co", "khong", "mot", "nhieu", "nam", "luat", "bo", "nghi",
        "dinh", "thong", "tu", "quyet",
    }
)
_DIRECT_DOCUMENT_FACT_RE = re.compile(
    r"\b(?:ông|bà|anh|chị|gia\s+đình|hộ\s+gia\s+đình|ubnd|ủy\s+ban|"
    r"ngày\s+\d|tháng\s+\d|héc\s*ta|diện\s+tích|"
    r"xử\s+phạt|tranh\s+chấp|quyết\s+định|bồi\s+thường)\b",
    re.IGNORECASE,
)


def _debug_hybrid_results(tool_name: str, query: str, results: list[dict]) -> None:
    """Expose retrieval ranking without changing the context sent downstream."""
    debug_dump(
        f"{tool_name} :: RANKED RETRIEVAL RESULTS",
        {
            "query": query,
            "result_count": len(results),
            "results": [
                {
                    "rank": rank,
                    "rrf_score": result.get("score"),
                    "rerank_score": result.get("rerank_score"),
                    "metadata": result.get("meta", {}),
                    "content": result.get("doc", ""),
                }
                for rank, result in enumerate(results, 1)
            ],
        },
    )


def _rerank_score_marker(result: dict) -> str:
    """Carry reranker relevance to the evidence layer without parsing debug logs."""
    score = result.get("rerank_score")
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        return ""
    return f"[RERANK_SCORE: {numeric_score:.6f}]\n"


def _fold_terms(value: str) -> set[str]:
    return set(_fold_token_sequence(value))


def _fold_token_sequence(value: str) -> list[str]:
    """Normalize a heading while retaining token order for generic similarity."""

    normalized = unicodedata.normalize("NFD", str(value or "").casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char)).replace("đ", "d")
    return [
        term
        for term in re.findall(r"[a-z0-9]{2,}", normalized)
        if term not in _TITLE_STOPWORDS and not term.isdigit()
    ]


def _weighted_title_similarity(
    query_sequence: list[str],
    title_sequence: list[str],
    document_frequency: Counter[str],
    title_count: int,
) -> float:
    """Score a heading without a domain-specific keyword allow/deny list.

    IDF is learned from the title corpus returned by Chroma for this request:
    terms shared by many headings contribute less automatically.  Ordered
    similarity prevents a long heading containing scattered query terms from
    beating a shorter heading that expresses the requested concept directly.
    """

    query_terms = set(query_sequence)
    title_terms = set(title_sequence)
    overlap = query_terms & title_terms
    if not overlap:
        return 0.0

    def weight(term: str) -> float:
        return log((max(1, title_count) + 1) / (document_frequency.get(term, 0) + 1)) + 1.0

    overlap_weight = sum(weight(term) for term in overlap)
    query_weight = sum(weight(term) for term in query_terms)
    title_weight = sum(weight(term) for term in title_terms)
    precision = overlap_weight / max(title_weight, 1e-9)
    recall = overlap_weight / max(query_weight, 1e-9)
    weighted_f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    matcher = SequenceMatcher(
        None,
        query_sequence,
        title_sequence,
        autojunk=False,
    )
    ordered_ratio = matcher.ratio()
    longest_block = max(
        (block.size for block in matcher.get_matching_blocks()),
        default=0,
    )
    contiguous_ratio = longest_block / max(1, min(len(query_sequence), len(title_sequence)))
    return weighted_f1 * 50.0 + ordered_ratio * 30.0 + contiguous_ratio * 20.0


def _rank_document_title_sources(
    query: str,
    docs: list[str],
    metas: list[dict],
    top_k: int = 5,
) -> list[tuple[str, dict]]:
    """Rank chunks from one named law by article heading before body similarity.

    This is used for direct doctrinal questions such as "quyền và nghĩa vụ của
    tổ chức kinh tế ... theo Luật Đất đai 2024". It does not infer an article
    number and does not replace `search_by_article`.
    """
    query_sequence = _fold_token_sequence(query)
    if not query_sequence:
        return []

    grouped: dict[tuple[str, str, str], dict[str, object]] = {}
    for index, (doc, meta) in enumerate(zip(docs, metas)):
        title = str(meta.get("tiêu_đề_điều", ""))
        title_sequence = _fold_token_sequence(title)
        if not title_sequence:
            continue
        article_key = (
            str(meta.get("tên_luật", "")),
            str(meta.get("số_điều", "")),
            title,
        )
        item = grouped.setdefault(
            article_key,
            {"score": 0.0, "sources": [], "title_sequence": title_sequence},
        )
        item["sources"].append((index, doc, meta))

    if not grouped:
        return []
    document_frequency: Counter[str] = Counter()
    for item in grouped.values():
        document_frequency.update(set(item["title_sequence"]))
    for item in grouped.values():
        item["score"] = _weighted_title_similarity(
            query_sequence,
            item["title_sequence"],
            document_frequency,
            len(grouped),
        )

    ordered_groups = sorted(
        (item for item in grouped.values() if float(item["score"]) > 0.0),
        key=lambda value: float(value["score"]),
        reverse=True,
    )
    if not ordered_groups:
        return []

    # A second article is useful for genuinely compound questions (for example,
    # principles and prohibited acts), but a weak lexical match must not dilute
    # a direct question whose heading has a clear match.
    best_score = float(ordered_groups[0]["score"])
    minimum_related_score = max(10.0, best_score * 0.55)
    ranked: list[tuple[str, dict]] = []
    for item in ordered_groups[:2]:
        if ranked and float(item["score"]) < minimum_related_score:
            continue
        for _, doc, meta in item["sources"]:
            ranked.append((doc, meta))
            if len(ranked) >= top_k:
                return ranked
    return ranked


def _strongest_title_group(
    query: str,
    title_sources: list[tuple[str, dict]],
) -> list[tuple[str, dict]]:
    """Keep one strongly matching heading group inside the seven-source budget."""

    if not title_sources:
        return []
    first_meta = title_sources[0][1]
    title = str(first_meta.get("tiêu_đề_điều", ""))
    query_sequence = _fold_token_sequence(query)
    title_sequence = _fold_token_sequence(title)
    overlap = set(query_sequence) & set(title_sequence)
    ordered_ratio = SequenceMatcher(
        None,
        query_sequence,
        title_sequence,
        autojunk=False,
    ).ratio()
    if len(overlap) < 2 or ordered_ratio < 0.25:
        return []
    group_key = (
        str(first_meta.get("tên_luật", "")),
        str(first_meta.get("số_điều", "")),
        title,
    )
    return [
        (doc, meta)
        for doc, meta in title_sources
        if (
            str(meta.get("tên_luật", "")),
            str(meta.get("số_điều", "")),
            str(meta.get("tiêu_đề_điều", "")),
        )
        == group_key
    ]


def _preserve_title_group(
    query: str,
    ranked_candidates: list[dict],
    title_sources: list[tuple[str, dict]],
    top_k: int = 7,
) -> list[dict]:
    """Project a strong title group plus the best remaining reranked sources."""

    def identity(doc: object, meta: dict) -> tuple[str, str, str, str, str, str]:
        return (
            str(doc),
            str(meta.get("tên_luật", "")),
            str(meta.get("số_điều", "")),
            str(meta.get("khoản", "")),
            str(meta.get("điểm", "")),
            str(meta.get("tiêu_đề_điều", "")),
        )

    protected_ids = {
        identity(doc, meta)
        for doc, meta in _strongest_title_group(query, title_sources)
    }
    if not protected_ids:
        return ranked_candidates[:top_k]
    protected = [
        candidate
        for candidate in ranked_candidates
        if identity(candidate.get("doc"), candidate.get("meta", {}))
        in protected_ids
    ]
    remaining = [
        candidate
        for candidate in ranked_candidates
        if identity(candidate.get("doc"), candidate.get("meta", {}))
        not in protected_ids
    ]
    return [*protected, *remaining][:top_k]


def _named_document_title_sources(
    query: str,
    named_document: str | None,
    target_date: str | None,
    is_transitional: bool,
) -> list[tuple[str, dict]]:
    """Return active title-ranked legal sources for a direct doctrinal query.

    A user need not know the governing document in advance.  When no document
    is named, search headings across active legislation and let the existing
    reranker merge at most five title candidates with semantic/BM25 results.
    Fact-heavy case questions remain on requirement-scoped semantic retrieval.
    """
    if _DIRECT_DOCUMENT_FACT_RE.search(str(query or "")) or collection is None:
        return []
    where_parts: list[dict] = [
        {"loại": {"$in": ["luật", "nghị định", "thông tư", "nghị quyết"]}}
    ]
    if named_document:
        where_parts.append({"tên_luật": named_document})
    if not target_date:
        where_parts.append(
            {"trang_thai": {"$in": ["con_hieu_luc", "còn hiệu lực"]}}
        )
    where = where_parts[0] if len(where_parts) == 1 else {"$and": where_parts}
    try:
        result = collection.get(where=where)
    except Exception:
        return []
    docs = result.get("documents", [])
    metas = result.get("metadatas", [])
    if not target_date:
        return _rank_document_title_sources(query, docs, metas)

    date_int = target_date_to_int(target_date)
    if date_int is None:
        return _rank_document_title_sources(query, docs, metas)
    filtered = [
        (doc, meta)
        for doc, meta in zip(docs, metas)
        if (
            (int(meta.get("effective_from", 0) or 0) <= date_int <= int(meta.get("effective_to", 99999999) or 99999999))
            or (is_transitional and str(meta.get("trang_thai", "")).casefold() in {"con_hieu_luc", "còn hiệu lực"})
        )
    ]
    return _rank_document_title_sources(query, [doc for doc, _ in filtered], [meta for _, meta in filtered])


CACHE_ARTICLE = {}


def _article_unit_sort_key(meta: dict, original_index: int) -> tuple:
    """Order all chunks of one article by clause and point.

    Exact article lookup is provenance closure, not semantic top-k retrieval.
    Keeping the legal order makes a multi-chunk article readable and ensures a
    cross-reference such as ``các điểm a, b, i, k, l, m và q khoản 1`` is not
    accidentally reordered or truncated.
    """

    clause = str(meta.get("khoản", "") or "").strip()
    point = str(meta.get("điểm", "") or "").strip().casefold()
    try:
        clause_order = int(clause)
    except (TypeError, ValueError):
        clause_order = 0 if not clause else 10_000

    # Vietnamese legal point labels normally follow this order. Unknown labels
    # remain stable after the known labels instead of being discarded.
    point_order = {
        label: index
        for index, label in enumerate(
            ("", "a", "b", "c", "d", "đ", "e", "g", "h", "i", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "x", "y"),
        )
    }
    return (
        clause_order,
        point_order.get(point, 1_000),
        point,
        original_index,
    )


def search_by_article(
    so_dieu: str | int,
    ten_luat: str = "",
    depth: int = 0,
    target_date: str | int = None,
    is_transitional: bool = False,
    named_document: str = None,
    khoan: str | int | None = None,
    diem: str | list[str] | None = None,
) -> str:
    """Tra cứu trực tiếp một Điều luật cụ thể theo số điều.
    Dùng khi câu hỏi hỏi thẳng 'Điều X là gì', 'Khoản Y Điều X quy định gì', 'Điều X Bộ luật Y'.
    Ưu tiên dùng tool này TRƯỚC KHI dùng search_law nếu câu hỏi có đề cập số điều cụ thể.

    Args:
        so_dieu: Số điều xuất hiện rõ sau từ "Điều" trong câu hỏi gốc (ví dụ: "101", "15"). Không dùng số thứ tự tình huống, năm, diện tích hoặc số tiền.
        ten_luat: Tên bộ luật (ví dụ: "Luật Đất đai"). KHÔNG điền số điều vào đây. Để trống nếu không rõ.
        target_date: Điền thời gian theo độ chính xác của câu hỏi (YYYY, YYYY-MM, hoặc YYYY-MM-DD). Ví dụ: "Tháng 10 năm 2024" điền "2024-10". Nếu hoàn toàn không có thông tin thời gian, BẮT BUỘC để trống (None). Cấm tự suy diễn ngày 01.
        is_transitional: Kích hoạt True nếu cần lấy thêm cả điều khoản chuyển tiếp ở văn bản hiện hành cho một sự việc cũ.
        named_document: Tên văn bản cụ thể cần tra cứu (ví dụ: "Luật Đất đai 2013"). Chỉ dùng khi muốn tra CỤ THỂ một văn bản duy nhất. Nếu muốn tra cả Luật và Nghị định hướng dẫn, HÃY ĐỂ TRỐNG (None).
        khoan: Nếu câu hỏi nêu rõ Khoản thì truyền số Khoản để chỉ lấy toàn bộ
            phần thuộc Khoản đó. Để trống để lấy toàn bộ Điều.
        diem: Một Điểm hoặc danh sách Điểm được nêu rõ. Chỉ dùng cùng ``khoan``;
            khi có giá trị, chỉ các Điểm này được trả về.
    """
    guard_warning = article_request_warning(get_active_question(), so_dieu, depth)
    if guard_warning:
        panel("ARTICLE GUARD", guard_warning)
        return guard_warning

    # FIX BUG 2: cache_key phải bao gồm target_date + is_transitional, nếu không sẽ trả
    # nhầm kết quả của một mốc thời gian khác cho cùng một Điều luật.
    so_dieu = str(so_dieu).strip()
    if ten_luat: ten_luat = str(ten_luat).strip()
    if named_document: named_document = str(named_document).strip()
    requested_named_document = named_document
    khoan = str(khoan or "").strip()
    if isinstance(diem, (list, tuple, set)):
        requested_points = {
            str(point).strip().casefold()
            for point in diem
            if str(point).strip()
        }
    else:
        requested_points = {
            point.casefold()
            for point in re.findall(r"\b([a-zđ])\b", str(diem or ""), re.IGNORECASE)
        }
    # A point label is not unique across an article. Ignore an unsafe point-only
    # filter rather than mixing points from several clauses.
    if requested_points and not khoan:
        requested_points = set()
    target_date, named_document, is_transitional = sanitize_active_temporal_arguments(
        target_date, named_document, is_transitional
    )
    # ``depth > 0`` is reserved for provenance closure initiated by the
    # pipeline after a verified source explicitly refers to another article.
    # In that path the document name comes from the source itself, not from an
    # unconstrained model guess.  The user-question sanitizer must still govern
    # direct tool calls (depth == 0), but stripping this trusted scope here
    # turns a reference such as "Điều 8 Nghị định 88/2024/NĐ-CP" into a
    # corpus-wide search for every document's Điều 8.
    if depth > 0 and requested_named_document:
        named_document = requested_named_document
    
    # Version the key so a long-lived process never reuses a previous cached
    # response that contained only the first five chunks of the article.
    point_key = ",".join(sorted(requested_points))
    cache_key = (
        f"hierarchical_article_v1_{so_dieu}_{khoan}_{point_key}_"
        f"{ten_luat}_{target_date}_{is_transitional}_{named_document}"
    )
    if cache_key in CACHE_ARTICLE:
        debug_dump(
            "search_by_article :: CACHE HIT",
            {"cache_key": cache_key, "context": CACHE_ARTICLE[cache_key]},
        )
        return CACHE_ARTICLE[cache_key]

    panel("TRA CỨU ĐIỀU LUẬT", f"Điều {so_dieu} {ten_luat or named_document or ''}".strip())
    progress(f"Đang tra cứu Điều {so_dieu} trong cơ sở dữ liệu pháp luật...")
    so_dieu = str(so_dieu)
    
    target_name = named_document or ten_luat
    if target_name: target_name = str(target_name)
    
    if collection is None:
        return "Lỗi: Chưa kết nối Database."

    so_dieu_list = re.findall(r'\d+', so_dieu)
    so_dieu_filter = {"số_điều": {"$in": so_dieu_list}} if len(so_dieu_list) > 1 else ({"số_điều": so_dieu_list[0]} if so_dieu_list else {"số_điều": so_dieu})
    
    try:
        results = collection.get(where=so_dieu_filter)
    except Exception:
        results = collection.get(where={"số_điều": so_dieu})
        
    docs = results.get("documents", [])
    metas = results.get("metadatas", [])
    
    filtered_docs = []
    filtered_metas = []
    
    date_int = target_date_to_int(target_date)
            
    # Nếu nhận cả tên văn bản và mốc thời gian, phải thỏa cả hai điều kiện.
    # Tên văn bản chỉ được phép bỏ lọc thời gian khi target_date không được truyền.
    ignore_date = bool(target_date is None and ((target_name and re.search(r'\b(19|20)\d{2}\b', target_name)) or named_document))
    
    for rank, (doc, meta) in enumerate(zip(docs, metas)):
        # 1. Lọc theo tên luật (Python contains)
        if target_name:
            meta_ten = str(meta.get("tên_luật", "")).lower()
            if target_name.lower().strip() not in meta_ten:
                continue
                
        # 2. Lọc theo thời gian
        if not ignore_date:
            if date_int is not None:
                eff_from = meta.get("effective_from", 0) or 0
                eff_to = meta.get("effective_to", 99999999) or 99999999
                status = str(meta.get("trang_thai", "")).lower()
                
                if is_transitional:
                    # Hợp lệ nếu nằm trong khoảng thời gian HOẶC đang còn hiệu lực
                    if not ((eff_from <= date_int <= eff_to) or status in ["con_hieu_luc", "còn hiệu lực"]):
                        continue
                else:
                    # Phải nằm trong khoảng thời gian
                    if not (eff_from <= date_int <= eff_to):
                        continue
            elif target_date is None:
                # Nếu không có date_int và target_date=None -> Chỉ lấy luật còn hiệu lực
                status = str(meta.get("trang_thai", "")).lower()
                if status not in ["con_hieu_luc", "còn hiệu lực"]:
                    continue
                    
        filtered_docs.append(doc)
        filtered_metas.append(meta)

    # Apply deterministic legal locators only after document and temporal
    # filtering. No semantic ranking or top-k is allowed for exact locators.
    if khoan:
        scoped_units = [
            (doc, meta)
            for doc, meta in zip(filtered_docs, filtered_metas)
            if str(meta.get("khoản", "") or "").strip() == khoan
            and (
                not requested_points
                or str(meta.get("điểm", "") or "").strip().casefold()
                in requested_points
            )
        ]
        filtered_docs = [doc for doc, _ in scoped_units]
        filtered_metas = [meta for _, meta in scoped_units]
        
    # Exact article lookup must return the complete article after document and
    # temporal filtering.  A semantic top-k cap is unsafe here: one clause can
    # explicitly refer to more subpoints than the cap (for example khoản 3 Điều
    # 133 refers to seven points of khoản 1).
    ordered_units = sorted(
        enumerate(zip(filtered_docs, filtered_metas)),
        key=lambda item: _article_unit_sort_key(item[1][1], item[0]),
    )
    docs = [doc for _, (doc, _) in ordered_units]
    metas = [meta for _, (_, meta) in ordered_units]
    debug_dump(
        "search_by_article :: FILTERED RESULTS",
        {
            "article": so_dieu,
            "clause": khoan,
            "points": sorted(requested_points),
            "document": target_name,
            "target_date": target_date,
            "is_transitional": is_transitional,
            "result_count": len(docs),
            "results": [
                {"rank": rank, "metadata": meta, "content": doc}
                for rank, (doc, meta) in enumerate(zip(docs, metas), 1)
            ],
        },
    )
    
    if not docs:
        return f"Không tìm thấy Điều {so_dieu} trong cơ sở dữ liệu."

    context = ""

    for rank, (doc, meta) in enumerate(zip(docs, metas)):
        hieu_luc = meta.get('trang_thai', 'Không xác định').upper()
        context += (
            f"- NGUỒN: {meta.get('loại', '').upper()} {meta.get('tên_luật', '')}"
            f"{_law_source_location(meta)} - {meta.get('tiêu_đề_điều', '')}\n"
            f"[THỜI GIAN HIỆU LỰC: {hieu_luc}]\n"
            f"Nội dung: {doc}\n\n"
        )

    CACHE_ARTICLE[cache_key] = context
    return context


CACHE_LAW = {}


def _law_source_location(meta: dict) -> str:
    article = str(meta.get("số_điều", "")).strip()
    if article:
        location = f", Điều {article}"
        clause = str(meta.get("khoản", "")).strip()
        point = str(meta.get("điểm", "")).strip()
        if clause:
            location += f", Khoản {clause}"
        if point:
            location += f", Điểm {point}"
        return location
    appendix = str(meta.get("phụ_lục", "")).strip()
    if appendix:
        return f", {appendix}"
    return ""


def search_law(query: str, depth: int = 0, target_date: str = None, is_transitional: bool = False, named_document: str = None, candidate_k: int | None = None, top_k: int = 7, article_filter: str | int | None = None) -> str:
    """Tìm kiếm nội dung trong các Văn bản quy phạm pháp luật (Luật, Nghị định, Thông tư, Nghị quyết).
    Sử dụng khi cần tìm căn cứ pháp lý theo ngữ nghĩa, mô tả tình huống.
    KHÔNG dùng nếu câu hỏi đã có số điều cụ thể — dùng search_by_article thay thế.

    Args:
        query: Từ khóa hoặc mô tả tình huống cần tra cứu trong luật.
        target_date: Điền thời gian theo độ chính xác của câu hỏi (YYYY, YYYY-MM, hoặc YYYY-MM-DD). Ví dụ: "Tháng 10 năm 2024" điền "2024-10". Nếu hoàn toàn không có thông tin thời gian, BẮT BUỘC để trống (None). Cấm tự suy diễn ngày 01.
        is_transitional: Kích hoạt True nếu cần lấy thêm cả điều khoản chuyển tiếp ở văn bản hiện hành cho một sự việc cũ.
        named_document: Tên văn bản cụ thể cần tra cứu (ví dụ: "Luật Đất đai 2013"). Chỉ dùng khi muốn tra CỤ THỂ một văn bản duy nhất. Nếu muốn tra cả Luật và Nghị định hướng dẫn, HÃY ĐỂ TRỐNG (None) và ghi rõ tên luật vào query.
        candidate_k: Số ứng viên Vector/BM25 đưa vào fusion và rerank. None giữ hành vi cũ.
        top_k: Số nguồn giữ lại sau rerank.
        article_filter: Giới hạn tìm kiếm trong đúng một Điều đã được nguồn dẫn chiếu.
    """
    requested_named_document = str(named_document or "").strip() or None
    target_date, named_document, is_transitional = sanitize_active_temporal_arguments(
        target_date, named_document, is_transitional
    )
    # depth > 0 chỉ được tạo từ provenance closure: tên văn bản lấy trực tiếp
    # từ header nguồn cha, không phải do model đoán.
    if depth > 0 and requested_named_document:
        named_document = requested_named_document
    # Chuẩn hóa các thuật ngữ giao dịch thửa đất/đất thành quyền sử dụng đất
    query = re.sub(
        r"\bchuyển nhượng\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "chuyển nhượng một phần quyền sử dụng đất" if "một phần" in m.group(0).lower() else "chuyển nhượng quyền sử dụng đất",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\btặng cho\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "tặng cho một phần quyền sử dụng đất" if "một phần" in m.group(0).lower() else "tặng cho quyền sử dụng đất",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\bthế chấp\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "thế chấp một phần quyền sử dụng đất" if "một phần" in m.group(0).lower() else "thế chấp quyền sử dụng đất",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\bchuyển quyền\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "chuyển quyền một phần sử dụng đất" if "một phần" in m.group(0).lower() else "chuyển quyền sử dụng đất",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\bmua bán\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "chuyển nhượng một phần quyền sử dụng đất" if "một phần" in m.group(0).lower() else "chuyển nhượng quyền sử dụng đất",
        query,
        flags=re.IGNORECASE,
    )
    result_top_k = max(1, min(int(top_k), 20))
    normalized_article_filter = str(article_filter or "").strip() or None
    candidate_pool_k = (
        max(result_top_k, min(int(candidate_k), 100))
        if candidate_k is not None
        else None
    )
    # Cache phải phân biệt cả mốc thời gian lẫn ngân sách truy xuất.
    cache_key = (
        f"{query}_{target_date}_{is_transitional}_{named_document}_"
        f"{candidate_pool_k}_{result_top_k}_{normalized_article_filter}"
    )
    if cache_key in CACHE_LAW:
        debug_dump(
            "search_law :: CACHE HIT",
            {"cache_key": cache_key, "context": CACHE_LAW[cache_key]},
        )
        return CACHE_LAW[cache_key]

    panel("TRA CỨU PHÁP LUẬT", query)
    progress("Đang tra cứu quy định liên quan:", query)
    if collection is None:
        return "Lỗi: Chưa kết nối Database."

    title_sources = (
        []
        if normalized_article_filter
        else _named_document_title_sources(
            get_active_question() or query,
            named_document,
            target_date,
            is_transitional,
        )
    )
    hybrid_arguments = {
        "query": query,
        "doc_type": "luật",
        "top_k": result_top_k,
        "target_date": target_date,
        "is_transitional": is_transitional,
        "named_document": named_document,
        "article_filter": normalized_article_filter,
    }
    if candidate_pool_k is not None:
        hybrid_arguments["candidate_k"] = candidate_pool_k
    hybrid_results = hybrid_query(**hybrid_arguments)
    if title_sources:
        title_candidates = [
            {"doc": doc, "meta": meta, "score": "document_title", "rerank_score": None}
            for doc, meta in title_sources
        ]
        all_candidates = [*hybrid_results, *title_candidates]
        ranked_candidates = rerank_candidates(
            query,
            all_candidates,
            top_k=len(all_candidates),
        )
        fused_results = _preserve_title_group(
            query,
            ranked_candidates,
            title_sources,
            top_k=result_top_k,
        )
        debug_dump(
            "search_law :: MERGED DOCUMENT TITLE RESULTS",
            {
                "query": query,
                "named_document": named_document,
                "hybrid_count": len(hybrid_results),
                "title_count": len(title_candidates),
                "result_count": len(fused_results),
            },
        )
    else:
        fused_results = hybrid_results
        _debug_hybrid_results("search_law", query, fused_results)

    if len(fused_results) == 0 and (target_date or named_document):
        return f"Không tìm thấy quy định phù hợp với văn bản hoặc mốc thời gian đã chỉ định: {named_document or target_date}."

    context = ""

    for rank, res in enumerate(fused_results):
        doc = res["doc"]
        meta = res["meta"]
        hieu_luc = meta.get('trang_thai', 'Không xác định').upper()
        context += (
            f"- NGUỒN: {meta.get('loại', '').upper()} {meta.get('tên_luật', '')}"
            f"{_law_source_location(meta)}\n"
            f"{_rerank_score_marker(res)}"
            f"[THỜI GIAN HIỆU LỰC: {hieu_luc}]\n"
            f"Nội dung: {doc}\n\n"
        )

    result = context if context else "Không tìm thấy quy định pháp luật liên quan."
    CACHE_LAW[cache_key] = result
    return result


CACHE_JUDGMENT = {}
def search_judgment(query: str) -> str:
    """Tìm kiếm các Bản án thực tế từ Tòa án nhân dân.
    Sử dụng khi cần tham khảo cách Tòa án xét xử, phân chia tài sản, bồi thường thực tế.

    Args:
        query: Tình huống tranh chấp cần tìm bản án tương tự.
    """
    if query in CACHE_JUDGMENT:
        debug_dump(
            "search_judgment :: CACHE HIT",
            {"query": query, "context": CACHE_JUDGMENT[query]},
        )
        return CACHE_JUDGMENT[query]
    panel("TRA CỨU BẢN ÁN", query)
    progress(f"Đang tìm bản án có tình tiết tương tự: {query[:140]}")
    if collection is None:
        return "Lỗi: Chưa kết nối Database."

    fused_results = hybrid_query(query, doc_type="bản_án", top_k=7)
    _debug_hybrid_results("search_judgment", query, fused_results)

    context = ""
    for res in fused_results:
        doc = res["doc"]
        meta = res["meta"]
        context += (
            f"- NGUỒN: Bản án số {meta.get('số_bản_án', '')}/{meta.get('năm', '')} "
            f"({meta.get('phần', '')})\n"
            f"{_rerank_score_marker(res)}"
            f"Nội dung: {doc}\n\n"
        )
    result = context if context else "Không tìm thấy bản án liên quan."
    CACHE_JUDGMENT[query] = result
    return result


CACHE_PRECEDENT = {}
def search_precedent(query: str) -> str:
    """Tìm kiếm Án lệ của Hội đồng Thẩm phán Tòa án nhân dân tối cao.
    Chỉ dùng khi câu hỏi liên quan tranh chấp phức tạp, thừa kế, Việt kiều,
    hoặc khi cần án lệ có giá trị pháp lý bắt buộc.

    Args:
        query: Tình huống tranh chấp cần tìm án lệ tương tự.
    """
    if query in CACHE_PRECEDENT:
        debug_dump(
            "search_precedent :: CACHE HIT",
            {"query": query, "context": CACHE_PRECEDENT[query]},
        )
        return CACHE_PRECEDENT[query]
    panel("TRA CỨU ÁN LỆ", query)
    progress(f"Đang tìm án lệ liên quan: {query[:140]}")
    if collection is None:
        return "Lỗi: Chưa kết nối Database."

    fused_results = hybrid_query(query, doc_type="án_lệ", top_k=5)
    _debug_hybrid_results("search_precedent", query, fused_results)

    context = ""
    for res in fused_results:
        doc = res["doc"]
        meta = res["meta"]
        context += (
            f"- NGUỒN: {meta.get('số_án_lệ', '')} (Phần: {meta.get('phần', '')})\n"
            f"{_rerank_score_marker(res)}"
            f"Nội dung: {doc}\n\n"
        )
    result = context if context else "Không tìm thấy án lệ liên quan."
    CACHE_PRECEDENT[query] = result
    return result
