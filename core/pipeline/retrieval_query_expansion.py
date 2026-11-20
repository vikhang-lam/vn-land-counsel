"""Sinh một cách diễn đạt truy vấn pháp lý thay thế cho từng Requirement."""

from __future__ import annotations

import json
import re

from core.agents.transport import sanitize_retrieval_query
from core.article_guard import explicit_article_numbers
from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.llm import LocalLLMClient

from .contracts import FactRecord, IssueRecord, RequirementRecord
from .prompts import RETRIEVAL_QUERY_VARIANT_SPEC, retrieval_query_variant_schema
from .retrieval_contract import RetrievalBudget


RETRIEVAL_QUERY_EXPANDER_PROMPT = RETRIEVAL_QUERY_VARIANT_SPEC.text
RETRIEVAL_QUERY_EXPANDER_SCHEMA = retrieval_query_variant_schema(
    RetrievalBudget.baseline().max_query_chars
)


def _parse_query(raw: str) -> str:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(raw or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict) or set(payload) != {"query"}:
        return ""
    return re.sub(r"\s+", " ", str(payload.get("query", ""))).strip(" .;:")


def expand_requirement_query(
    client: LocalLLMClient,
    *,
    question: str,
    issue: IssueRecord,
    requirement: RequirementRecord,
    facts: list[FactRecord],
    budget: RetrievalBudget | None = None,
) -> str:
    """Trả một query phụ đã kiểm tra; liên kết ID do caller sở hữu."""

    active_budget = budget or RetrievalBudget.baseline()
    active_budget.validate()
    linked_ids = set(requirement.fact_ids)
    linked_facts = [fact for fact in facts if fact.fact_id in linked_ids]
    facts_text = "\n".join(
        f"- [{fact.category}] {fact.value}" for fact in linked_facts
    ) or "NONE"
    message = (
        f"CÂU HỎI GỐC:\n{sanitize_retrieval_query(question, [fact.to_dict() for fact in facts])}\n\n"
        f"VẤN ĐỀ:\n{issue.display_text}\n\n"
        f"MỤC TIÊU:\n{requirement.objective}\n\n"
        f"LOẠI CĂN CỨ:\n{requirement.target_kind}\n\n"
        f"QUERY BAN ĐẦU:\n{requirement.query}\n\n"
        f"DỮ KIỆN LIÊN KẾT:\n{facts_text}"
    )
    settings = get_active_settings()
    response = client.complete(
        message,
        model=settings.adjudicator_model,
        system_prompt=RETRIEVAL_QUERY_VARIANT_SPEC.text,
        temperature=0.0,
        max_tokens=120,
        json_mode=True,
        json_schema=retrieval_query_variant_schema(active_budget.max_query_chars),
    )
    candidate = _parse_query(response.text)
    candidate = sanitize_retrieval_query(
        candidate,
        [fact.to_dict() for fact in facts],
    )
    if len(candidate) > active_budget.max_query_chars:
        candidate = ""
    if candidate.casefold() == requirement.query.casefold():
        candidate = ""

    # Query phụ không được tự bịa locator mà câu hỏi/query gốc chưa nêu.
    allowed_articles = {
        *explicit_article_numbers(question),
        *explicit_article_numbers(requirement.query),
    }
    if explicit_article_numbers(candidate) - allowed_articles:
        candidate = ""
    debug_dump(
        "PIPELINE :: RETRIEVAL QUERY EXPANSION",
        {
            "issue_id": issue.issue_id,
            "requirement_id": requirement.requirement_id,
            "primary_query": requirement.query,
            "raw_output": response.text,
            "accepted_query": candidate,
        },
    )
    return candidate


__all__ = [
    "RETRIEVAL_QUERY_EXPANDER_PROMPT",
    "RETRIEVAL_QUERY_EXPANDER_SCHEMA",
    "expand_requirement_query",
]
