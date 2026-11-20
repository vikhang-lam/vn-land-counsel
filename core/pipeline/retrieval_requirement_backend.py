"""Backend Retrieval: một Requirement, một action chính do Python đóng."""

from __future__ import annotations

from typing import Any

from core.agents.retrieval_issue_context import issue_retrieval_hints
from core.article_guard import explicit_article_numbers
from core.llm import LocalLLMClient
from core.retrieval_plan import execute_retrieval_plan

from .retrieval_contract import RetrievalBudget


def run_requirement_retrieval(
    client: LocalLLMClient,
    question: str,
    issue: str,
    temporal_context: str,
    index: int,
    total: int,
    previous_actions: list[dict] | None = None,
    case_facts: list[dict[str, str]] | None = None,
    requirement_ids: set[str] | None = None,
    retrieval_budget: RetrievalBudget | None = None,
) -> tuple[list[str], list[dict]]:
    """Thực thi query Planner của đúng một Requirement.

    ``client``, ``previous_actions`` và ``case_facts`` được giữ trong chữ ký để
    tương thích stage, nhưng backend này không giao việc gán ID hay chọn action
    cho LLM. Query phụ được tạo ở một component riêng, cũng theo từng
    Requirement và được caller gắn ID bằng Python.
    """

    del client, question, issue, total, previous_actions, case_facts
    active_budget = retrieval_budget or RetrievalBudget.baseline()
    active_budget.validate()
    normalized_ids = {
        str(value).strip().upper()
        for value in requirement_ids or set()
        if str(value).strip()
    }
    if len(normalized_ids) != 1:
        raise ValueError("Retrieval backend cần đúng một Requirement ID.")
    requirement_id = next(iter(normalized_ids))
    _, requirements, _, target_date, named_document = issue_retrieval_hints(
        temporal_context,
        index,
    )
    requirement = next(
        (
            item
            for item in requirements
            if str(item.get("requirement_id", "")).strip().upper()
            == requirement_id
        ),
        None,
    )
    if not isinstance(requirement, dict):
        raise ValueError(
            f"Không tìm thấy {requirement_id} trong Issue đang truy xuất."
        )
    query = str(requirement.get("query", "")).strip()
    if not query:
        raise ValueError(f"{requirement_id} không có query Planner.")

    articles = sorted(explicit_article_numbers(query))
    if len(articles) == 1:
        action: dict[str, Any] = {
            "tool": "search_by_article",
            "so_dieu": articles[0],
            "ten_luat": "",
            "named_document": named_document,
            "target_date": target_date,
            "requirement_id": requirement_id,
            "query_origin": "PLANNER",
        }
    else:
        action = {
            "tool": "search_law",
            "query": query,
            "target_date": target_date,
            "is_transitional": False,
            "named_document": named_document,
            "candidate_k": active_budget.candidate_k,
            "top_k": active_budget.rerank_k,
            "requirement_id": requirement_id,
            "query_origin": "PLANNER",
        }
    return execute_retrieval_plan([action]), [action]


__all__ = [
    "run_requirement_retrieval",
]
