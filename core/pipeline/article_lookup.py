"""Exact ARTICLE fast path: collection lookup and Python rendering, no LLM."""

from __future__ import annotations

from dataclasses import dataclass
import re
from time import perf_counter
from typing import Any

from core.article_guard import explicit_article_numbers
from core.temporal_guard import inferred_named_document
from core.text_normalization import fold_vietnamese
from retrieval.chromadb_client import get_readonly_collection


@dataclass(frozen=True, slots=True)
class ArticleSourceRecord:
    source_index: int
    document: str
    citation: str
    text: str


@dataclass(frozen=True, slots=True)
class ArticleLookupResult:
    article: str
    sources: tuple[ArticleSourceRecord, ...]
    message: str
    found: bool
    latency_seconds: float

    @property
    def document_count(self) -> int:
        return len({source.document for source in self.sources})

    @property
    def chunk_count(self) -> int:
        return len(self.sources)


def _citation(article: str, metadata: dict[str, Any]) -> str:
    law_name = str(metadata.get("tên_luật", "Không rõ văn bản")).strip()
    clause = str(metadata.get("số_khoản") or metadata.get("khoản") or "").strip()
    point = str(metadata.get("điểm") or "").strip()
    parts: list[str] = []
    if point:
        parts.append(f"điểm {point}")
    if clause:
        parts.append(f"khoản {clause}")
    parts.append(f"Điều {article}")
    parts.append(law_name)
    return " ".join(parts)


def _sort_value(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    match = re.search(r"\d+", text)
    return (int(match.group(0)) if match else 10**9, text.casefold())


def _record_order(record: tuple[str, dict[str, Any]]) -> tuple:
    _, metadata = record
    return (
        str(metadata.get("tên_luật", "")).casefold(),
        _sort_value(metadata.get("số_khoản") or metadata.get("khoản")),
        _sort_value(metadata.get("điểm")),
        _sort_value(
            metadata.get("chunk_order")
            or metadata.get("chunk_index")
            or metadata.get("thứ_tự")
        ),
    )


class ArticleLookupStage:
    def run(self, question: str) -> ArticleLookupResult:
        started = perf_counter()
        text = str(question or "").strip()
        articles = sorted(explicit_article_numbers(text))
        if len(articles) != 1:
            raise ValueError("ARTICLE fast path cần đúng một số Điều.")
        article = articles[0]
        collection = get_readonly_collection()
        if collection is None:
            raise RuntimeError("Chưa kết nối cơ sở dữ liệu pháp luật.")
        try:
            result = collection.get(where={"số_điều": article})
        except Exception:
            result = collection.get(where={"số_điều": {"$eq": article}})

        documents = list(result.get("documents") or [])
        metadatas = list(result.get("metadatas") or [])
        records = [
            (str(document or "").strip(), dict(metadata or {}))
            for document, metadata in zip(documents, metadatas)
            if str(document or "").strip()
        ]
        named_document = inferred_named_document(text)
        if named_document:
            expected = fold_vietnamese(named_document)
            records = [
                record
                for record in records
                if expected in fold_vietnamese(record[1].get("tên_luật", ""))
                or fold_vietnamese(record[1].get("tên_luật", "")) in expected
            ]
        else:
            current = [
                record
                for record in records
                if str(record[1].get("trang_thai", "")).strip().casefold()
                in {"con_hieu_luc", "còn hiệu lực"}
            ]
            if current:
                records = current

        requested_clause = re.search(
            r"\bkhoản\s+(\d+)\s+Điều\s+" + re.escape(article) + r"\b",
            text,
            flags=re.IGNORECASE,
        )
        requested_point = re.search(
            r"\bđiểm\s+([A-Za-zĐđ])\s+(?:khoản\s+\d+\s+)?Điều\s+"
            + re.escape(article)
            + r"\b",
            text,
            flags=re.IGNORECASE,
        )
        if requested_clause:
            clause = requested_clause.group(1)
            scoped = [
                record
                for record in records
                if str(
                    record[1].get("số_khoản")
                    or record[1].get("khoản")
                    or ""
                ).strip()
                == clause
            ]
            if scoped:
                records = scoped
        if requested_point:
            point = requested_point.group(1).casefold()
            scoped = [
                record
                for record in records
                if str(record[1].get("điểm") or "").strip().casefold()
                == point
            ]
            if scoped:
                records = scoped

        unique_records: list[tuple[str, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        for document, metadata in sorted(records, key=_record_order):
            law_name = str(metadata.get("tên_luật", "Không rõ văn bản")).strip()
            key = (law_name.casefold(), re.sub(r"\s+", " ", document).casefold())
            if key in seen:
                continue
            seen.add(key)
            unique_records.append((document, metadata))

        if not unique_records:
            return ArticleLookupResult(
                message=(
                    f"Không tìm thấy Điều {article}"
                    + (f" trong {named_document}" if named_document else "")
                    + " trong cơ sở dữ liệu pháp luật."
                ),
                article=article,
                sources=(),
                found=False,
                latency_seconds=round(perf_counter() - started, 4),
            )

        sources = tuple(
            ArticleSourceRecord(
                source_index=index,
                document=str(metadata.get("tên_luật", "Không rõ văn bản")).strip(),
                citation=_citation(article, metadata),
                text=document,
            )
            for index, (document, metadata) in enumerate(unique_records)
        )
        return ArticleLookupResult(
            article=article,
            sources=sources,
            message="",
            found=True,
            latency_seconds=round(perf_counter() - started, 4),
        )


__all__ = ["ArticleLookupResult", "ArticleLookupStage", "ArticleSourceRecord"]
