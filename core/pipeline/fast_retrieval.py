"""Direct hybrid retrieval for low-latency public paths."""

from __future__ import annotations

import re
from typing import Any

from core.answer_mode import is_procedure_question
from core.text_normalization import fold_vietnamese
from core.temporal_guard import inferred_named_document, inferred_target_date
from retrieval.chromadb_client import get_readonly_collection
from retrieval.hybrid_search import hybrid_query

from .fast_grounding import FastSource
from .retrieval_contract import RetrievalBudget


_TITLE_STOPWORDS = {
    "cac", "cua", "do", "giay", "nguoi", "quy", "su", "thu", "thuc",
    "tinh", "trinh", "tu", "tuc", "va", "ve",
}
_USER_ACTION_RE = re.compile(
    r"\b(?:nguoi\s+su\s+dung\s+dat|chu\s+so\s+huu|nguoi\s+yeu\s+cau|"
    r"nguoi\s+nop\s+ho\s+so)\b.{0,220}\b(?:nop|gui|de\s+nghi|"
    r"ke\s+khai|xuat\s+trinh)\b",
    re.IGNORECASE | re.DOTALL,
)


def _meaningful_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", fold_vietnamese(value))
        if len(token) > 1 and token not in _TITLE_STOPWORDS
    }


def _source_text(document: str, metadata: dict[str, Any]) -> str:
    title = str(metadata.get("tiêu_đề_điều", "")).strip()
    body = str(document or "").strip()
    if title and fold_vietnamese(title) not in fold_vietnamese(body[:500]):
        return f"{title}\n{body}"
    return body


def _procedure_article_siblings(
    question: str,
    results: list[dict[str, Any]],
    *,
    max_additions: int = 2,
) -> list[dict[str, Any]]:
    """Add bounded same-article clauses when a procedure title matches."""

    if not is_procedure_question(question) or max_additions < 1:
        return []
    query_tokens = _meaningful_tokens(question)
    anchors: list[tuple[int, dict[str, Any]]] = []
    for result in results:
        metadata = dict(result.get("meta") or {})
        document_id = str(metadata.get("id_van_ban", "")).strip()
        article = str(metadata.get("số_điều", "")).strip()
        title = str(metadata.get("tiêu_đề_điều", "")).strip()
        if not document_id or not article or not title:
            continue
        overlap = len(query_tokens & _meaningful_tokens(title))
        if overlap >= 2:
            anchors.append((overlap, metadata))
    if not anchors:
        return []
    anchor = max(
        anchors,
        key=lambda item: (
            item[0],
            int(item[1].get("effective_from", 0) or 0),
        ),
    )[1]
    collection = get_readonly_collection()
    if collection is None:
        return []
    try:
        article_data = collection.get(
            where={
                "$and": [
                    {"id_van_ban": {"$eq": str(anchor["id_van_ban"])}},
                    {"số_điều": {"$eq": str(anchor["số_điều"])}},
                ]
            },
            include=["documents", "metadatas"],
        )
    except Exception:
        return []
    existing = {
        _source_identity(
            str(result.get("doc", "")),
            dict(result.get("meta") or {}),
        )
        for result in results
    }
    candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    for document, metadata_value in zip(
        article_data.get("documents", []),
        article_data.get("metadatas", []),
    ):
        metadata = dict(metadata_value or {})
        identity = _source_identity(str(document or ""), metadata)
        if not str(document or "").strip() or identity in existing:
            continue
        structured = _source_text(str(document), metadata)
        folded = fold_vietnamese(structured)
        overlap = len(query_tokens & _meaningful_tokens(structured))
        clause = str(metadata.get("số_khoản") or metadata.get("khoản") or "")
        clause_order = int(clause) if clause.isdigit() else 999
        candidates.append(
            (
                1 if _USER_ACTION_RE.search(folded) else 0,
                overlap,
                -clause_order,
                {"doc": str(document), "meta": metadata},
            )
        )
    candidates.sort(key=lambda item: item[:3], reverse=True)
    return [item[3] for item in candidates[:max_additions]]


def legal_source_citation(metadata: dict[str, Any]) -> str:
    law_name = str(metadata.get("tên_luật", "Không rõ văn bản")).strip()
    article = str(metadata.get("số_điều") or "").strip()
    clause = str(metadata.get("số_khoản") or metadata.get("khoản") or "").strip()
    point = str(metadata.get("điểm") or "").strip()
    parts: list[str] = []
    if point:
        parts.append(f"điểm {point}")
    if clause:
        parts.append(f"khoản {clause}")
    if article:
        parts.append(f"Điều {article}")
    parts.append(law_name)
    return " ".join(parts)


def _source_identity(document: str, metadata: dict[str, Any]) -> tuple[str, str]:
    citation = legal_source_citation(metadata).casefold()
    text = re.sub(r"\s+", " ", str(document or "")).strip().casefold()
    return citation, text


def retrieve_fast_sources(
    question: str,
    query: str,
    budget: RetrievalBudget,
) -> tuple[FastSource, ...]:
    budget.validate()
    results = hybrid_query(
        query=str(query or "").strip(),
        doc_type="luật",
        top_k=budget.rerank_k,
        target_date=inferred_target_date(question),
        is_transitional=False,
        named_document=inferred_named_document(question),
        candidate_k=budget.candidate_k,
    )
    results = [
        *results,
        *_procedure_article_siblings(question, results),
    ]
    output: list[FastSource] = []
    seen: set[tuple[str, str]] = set()
    for result in results:
        document = str(result.get("doc", "")).strip()
        metadata = dict(result.get("meta") or {})
        identity = _source_identity(document, metadata)
        if not document or identity in seen:
            continue
        seen.add(identity)
        output.append(
            FastSource(
                source_index=len(output),
                citation=legal_source_citation(metadata),
                text=_source_text(document, metadata),
            )
        )
    return tuple(output)


def merge_fast_sources(
    first: tuple[FastSource, ...],
    second: tuple[FastSource, ...],
) -> tuple[FastSource, ...]:
    output: list[FastSource] = []
    seen: set[tuple[str, str]] = set()
    for source in (*first, *second):
        identity = (
            source.citation.casefold(),
            re.sub(r"\s+", " ", source.text).strip().casefold(),
        )
        if identity in seen:
            continue
        seen.add(identity)
        output.append(
            FastSource(
                source_index=len(output),
                citation=source.citation,
                text=source.text,
            )
        )
    return tuple(output)


__all__ = [
    "legal_source_citation",
    "merge_fast_sources",
    "retrieve_fast_sources",
]
