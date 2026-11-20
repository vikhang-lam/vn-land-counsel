"""Mở rộng dẫn chiếu nội bộ đã xuất hiện nguyên văn trong nguồn truy xuất."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Any

from core.agents.transport import sanitize_retrieval_query
from core.retrieval_plan import execute_retrieval_plan

from .contracts import FactRecord, RequirementRecord
from .retrieval_contract import RetrievalBudget


@dataclass(frozen=True, slots=True)
class CrossReferenceBatch:
    """Một nhóm kết quả trong đúng Điều được nguồn cha dẫn chiếu."""

    action: dict[str, Any]
    parent_text: str
    document: str
    article: str
    contexts: tuple[str, ...]

_SOURCE_HEADER_RE = re.compile(
    r"(?mi)^\s*-\s*NGUỒN:\s*"
    r"(?:BỘ\s+LUẬT|LUẬT|NGHỊ\s*ĐỊNH|THÔNG\s*TƯ|NGHỊ\s*QUYẾT)\s+"
    r"(?P<document>.+?),\s*Điều\s+(?P<article>\d+[A-Za-zĐđ]?)\b"
)
_SAME_DOCUMENT_REFERENCE_RE = re.compile(
    r"(?P<group>Điều\s+\d+[A-Za-zĐđ]?"
    r"(?:\s*(?:,|và|hoặc)\s*Điều\s+\d+[A-Za-zĐđ]?)*?)"
    r"\s+của\s+(?:Bộ\s+luật|Luật|Nghị\s*định|Thông\s*tư|Nghị\s*quyết)\s+này\b",
    flags=re.IGNORECASE,
)


def internal_article_references(source_text: str) -> tuple[str, list[str]]:
    """Trả tên văn bản và các Điều được dẫn chiếu rõ là cùng văn bản."""

    source = str(source_text or "")
    header = _SOURCE_HEADER_RE.search(source)
    if not header:
        return "", []
    document = re.sub(r"\s+", " ", header.group("document")).strip()
    source_article = header.group("article").casefold()
    body = source[header.end() :]
    references: list[str] = []
    for match in _SAME_DOCUMENT_REFERENCE_RE.finditer(body):
        for article in re.findall(
            r"Điều\s+(\d+[A-Za-zĐđ]?)",
            match.group("group"),
            flags=re.IGNORECASE,
        ):
            normalized = article.strip()
            if normalized.casefold() == source_article or normalized in references:
                continue
            references.append(normalized)
    return document, references


def expand_requirement_cross_references(
    contexts: list[str],
    requirement: RequirementRecord,
    facts: list[FactRecord],
    *,
    target_date: str | None,
    executor: Callable[[list[dict[str, Any]]], list[str]] = execute_retrieval_plan,
    budget: RetrievalBudget | None = None,
) -> list[CrossReferenceBatch]:
    """Theo tối đa hai dẫn chiếu thật và gắn provenance bằng Python."""

    active_budget = budget or RetrievalBudget.baseline()
    active_budget.validate()
    if active_budget.max_cross_references_per_requirement == 0:
        return []
    requests: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for context in contexts:
        document, articles = internal_article_references(context)
        for article in articles:
            key = (document.casefold(), article.casefold())
            if not document or key in seen:
                continue
            seen.add(key)
            requests.append((context, document, article))
            if len(requests) >= active_budget.max_cross_references_per_requirement:
                break
        if len(requests) >= active_budget.max_cross_references_per_requirement:
            break

    batches: list[CrossReferenceBatch] = []
    linked_ids = set(requirement.fact_ids)
    linked_facts = [fact for fact in facts if fact.fact_id in linked_ids]
    scoped_query = re.sub(
        r"\s+",
        " ",
        " ".join(
            [
                requirement.objective,
                requirement.query,
                *[fact.value for fact in linked_facts],
            ]
        ),
    ).strip()
    scoped_query = sanitize_retrieval_query(
        scoped_query,
        [fact.to_dict() for fact in facts],
    )[:600].strip()
    for parent_text, document, article in requests:
        action = {
            "tool": "search_law",
            "query": scoped_query or requirement.query,
            "depth": 1,
            "target_date": target_date,
            "is_transitional": False,
            "named_document": document,
            "article_filter": article,
            "candidate_k": active_budget.candidate_k,
            "top_k": active_budget.rerank_k,
            "requirement_id": requirement.requirement_id,
            "query_facet": "CROSS_REFERENCE",
            "query_origin": "SOURCE_CROSS_REFERENCE",
        }
        article_contexts = executor([action])
        if not article_contexts:
            continue
        batches.append(
            CrossReferenceBatch(
                action=action,
                parent_text=parent_text,
                document=document,
                article=article,
                contexts=tuple(article_contexts),
            )
        )
    return batches


__all__ = [
    "CrossReferenceBatch",
    "expand_requirement_cross_references",
    "internal_article_references",
]
