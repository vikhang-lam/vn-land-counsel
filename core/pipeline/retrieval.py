"""Stage 4 - truy xuất nguồn theo từng Issue và Requirement."""

from __future__ import annotations

import re
from functools import partial
from typing import Callable, Any

from core.debug_trace import debug_dump
from core.evidence import (
    retrieval_rerank_score,
    strip_retrieval_metadata,
)
from core.llm import LocalLLMClient
from core.retrieval_plan import execute_retrieval_plan

from .contracts import (
    FactRecord,
    IssueRetrievalResult,
    PlanningResult,
    RetrievalActionRecord,
    RetrievalResult,
    RetrievedContextRecord,
)
from .retrieval_cross_reference import expand_requirement_cross_references
from .retrieval_requirement_backend import run_requirement_retrieval
from .retrieval_contract import RetrievalBudget


RetrievalBackend = Callable[..., tuple[list[str], list[dict]]]
QueryExpander = Callable[..., str]
RetrievalExecutor = Callable[[list[dict[str, Any]]], list[str]]

def _context_identity(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        strip_retrieval_metadata(str(text or "")),
    ).strip().casefold()


def _select_requirement_contexts(
    contexts: list[str],
    limit: int,
) -> list[str]:
    """Giữ các nguồn điểm cao nhất trong một nhóm provenance."""

    unique: list[tuple[int, str]] = []
    seen: set[str] = set()
    for position, context in enumerate(contexts):
        raw_text = str(context or "").strip()
        identity = _context_identity(raw_text)
        if not raw_text or not identity or identity in seen:
            continue
        seen.add(identity)
        unique.append((position, raw_text))
    ranked = sorted(
        unique,
        key=lambda item: (
            -(
                retrieval_rerank_score(item[1])
                if retrieval_rerank_score(item[1]) is not None
                else float("-inf")
            ),
            item[0],
        ),
    )
    return [text for _, text in ranked[: max(1, limit)]]


class RetrievalStage:
    """Chạy worker theo thứ tự Issue và đóng provenance thành contract typed."""

    def __init__(
        self,
        backend: RetrievalBackend | None = None,
        *,
        query_expander: QueryExpander | None = None,
        executor: RetrievalExecutor | None = None,
        budget: RetrievalBudget | None = None,
    ) -> None:
        self._budget = budget or RetrievalBudget.baseline()
        self._budget.validate()
        self._backend = backend or partial(
            run_requirement_retrieval,
            retrieval_budget=self._budget,
        )
        # Runtime dùng đúng một query phụ đã được kiểm tra. Custom backend
        # trong unit test không tự bật model phụ nếu caller không truyền.
        if query_expander is not None:
            self._query_expander = query_expander
        elif backend is None:
            from .retrieval_query_expansion import expand_requirement_query

            self._query_expander = expand_requirement_query
        else:
            self._query_expander = None
        self._executor = executor or execute_retrieval_plan

    def run(
        self,
        client: LocalLLMClient,
        question: str,
        facts: list[FactRecord],
        planning: PlanningResult,
    ) -> RetrievalResult:
        query = str(question or "").strip()
        if not query:
            raise ValueError("Retrieval không nhận câu hỏi rỗng.")
        if not planning.issues:
            raise ValueError("Retrieval cần ít nhất một Issue từ Planner.")

        fact_payloads = [fact.to_dict() for fact in facts]
        previous_actions: list[dict] = []
        issue_results: list[IssueRetrievalResult] = []
        next_action = 1
        next_context = 1
        next_group = 1

        for index, issue in enumerate(planning.issues, 1):
            typed_actions: list[RetrievalActionRecord] = []
            typed_contexts: list[RetrievedContextRecord] = []
            seen_requirement_contexts: dict[str, set[str]] = {
                requirement.requirement_id: set()
                for requirement in issue.requirements
            }

            for requirement in issue.requirements:
                # Worker chỉ nhìn một Requirement. Vì vậy Python biết chắc mọi
                # action/context của lượt gọi thuộc Requirement nào, kể cả khi
                # model bỏ trống hoặc ghi nhầm ID trong JSON.
                contexts, actions = self._backend(
                    client,
                    query,
                    issue.display_text,
                    planning.temporal_context,
                    index,
                    len(planning.issues),
                    previous_actions,
                    fact_payloads,
                    requirement_ids={requirement.requirement_id},
                )
                candidate_actions = list(actions)[
                    : self._budget.max_actions_per_requirement
                ]
                candidate_contexts = list(contexts)

                if (
                    self._query_expander is not None
                    and len(candidate_actions)
                    < self._budget.max_actions_per_requirement
                ):
                    try:
                        expanded_query = self._query_expander(
                            client,
                            question=query,
                            issue=issue,
                            requirement=requirement,
                            facts=facts,
                            budget=self._budget,
                        )
                    except Exception as error:  # query gốc vẫn đủ để tiếp tục
                        expanded_query = ""
                        debug_dump(
                            "PIPELINE :: RETRIEVAL QUERY EXPANSION :: SKIPPED",
                            str(error),
                        )
                    existing_queries = {
                        re.sub(
                            r"\s+",
                            " ",
                            str(action.get("query") or action.get("so_dieu") or ""),
                        ).strip().casefold()
                        for action in candidate_actions
                    }
                    if expanded_query and expanded_query.casefold() not in existing_queries:
                        expanded_action: dict[str, Any] = {
                            "tool": "search_law",
                            "query": expanded_query,
                            "requirement_id": requirement.requirement_id,
                            "query_origin": "LEGAL_QUERY_EXPANSION",
                            "candidate_k": self._budget.candidate_k,
                            "top_k": self._budget.rerank_k,
                        }
                        if candidate_actions:
                            source_action = candidate_actions[0]
                            for key in (
                                "target_date",
                                "is_transitional",
                                "named_document",
                            ):
                                if source_action.get(key) not in (None, ""):
                                    expanded_action[key] = source_action[key]
                        try:
                            expanded_contexts = self._executor([expanded_action])
                        except Exception as error:  # giữ kết quả query chính
                            expanded_contexts = []
                            debug_dump(
                                "PIPELINE :: RETRIEVAL QUERY EXPANSION :: EXECUTION FAILED",
                                str(error),
                            )
                        else:
                            candidate_actions.append(expanded_action)
                            candidate_contexts.extend(expanded_contexts)

                preliminary_contexts = _select_requirement_contexts(
                    candidate_contexts,
                    self._budget.rerank_k,
                )
                target_date = next(
                    (
                        str(action.get("target_date")).strip()
                        for action in candidate_actions
                        if action.get("target_date") not in (None, "")
                    ),
                    None,
                )
                cross_batches = expand_requirement_cross_references(
                    preliminary_contexts,
                    requirement,
                    facts,
                    target_date=target_date,
                    executor=self._executor,
                    budget=self._budget,
                )
                candidate_actions.extend(batch.action for batch in cross_batches)

                requirement_actions: list[RetrievalActionRecord] = []
                action_records_by_object: dict[int, RetrievalActionRecord] = {}
                for action in candidate_actions:
                    record = RetrievalActionRecord.from_mapping(
                        action,
                        action_id=f"A{next_action:03d}",
                        issue_id=issue.issue_id,
                        requirement_id=requirement.requirement_id,
                    )
                    requirement_actions.append(record)
                    action_records_by_object[id(action)] = record
                    typed_actions.append(record)
                    next_action += 1

                primary_group_id = f"G{next_group:04d}"
                next_group += 1
                primary_action_id = (
                    requirement_actions[0].action_id if requirement_actions else ""
                )
                primary_ids_by_identity: dict[str, str] = {}
                seen_contexts = seen_requirement_contexts[requirement.requirement_id]
                for context in preliminary_contexts:
                    raw_text = str(context or "").strip()
                    # Bỏ trùng trong cùng Requirement, nhưng giữ cùng một nguồn
                    # nếu nó hỗ trợ hai Requirement khác nhau.
                    if not raw_text or raw_text in seen_contexts:
                        continue
                    seen_contexts.add(raw_text)
                    context_id = f"RC{next_context:04d}"
                    record = RetrievedContextRecord.from_text(
                        raw_text,
                        context_id=context_id,
                        issue_id=issue.issue_id,
                        requirement_id=requirement.requirement_id,
                        group_id=primary_group_id,
                        action_id=primary_action_id,
                        origin="PRIMARY",
                    )
                    typed_contexts.append(record)
                    primary_ids_by_identity[_context_identity(raw_text)] = context_id
                    next_context += 1

                for batch in cross_batches:
                    cross_group_id = f"G{next_group:04d}"
                    next_group += 1
                    parent_context_id = primary_ids_by_identity.get(
                        _context_identity(batch.parent_text),
                        "",
                    )
                    # Cross-reference action đã được type ở trên; lookup theo
                    # object identity tránh model hoặc chuỗi query tham gia nối ID.
                    if id(batch.action) not in action_records_by_object:
                        raise ValueError("Thiếu action Python cho nhóm dẫn chiếu.")
                    group_seen: set[str] = set()
                    for context in _select_requirement_contexts(
                        list(batch.contexts),
                        self._budget.rerank_k,
                    ):
                        raw_text = str(context or "").strip()
                        identity = _context_identity(raw_text)
                        if not raw_text or not identity or identity in group_seen:
                            continue
                        group_seen.add(identity)
                        typed_contexts.append(
                            RetrievedContextRecord.from_text(
                                raw_text,
                                context_id=f"RC{next_context:04d}",
                                issue_id=issue.issue_id,
                                requirement_id=requirement.requirement_id,
                                group_id=cross_group_id,
                                action_id=action_records_by_object[
                                    id(batch.action)
                                ].action_id,
                                origin="CROSS_REFERENCE",
                                parent_context_id=parent_context_id,
                                scope_document=batch.document,
                                scope_article=batch.article,
                            )
                        )
                        next_context += 1

                # Chỉ truyền action đã được Python đóng lại ID cho worker sau.
                previous_actions.extend(
                    record.to_dict() for record in requirement_actions
                )

            issue_results.append(
                IssueRetrievalResult(
                    issue_id=issue.issue_id,
                    contexts=tuple(typed_contexts),
                    actions=tuple(typed_actions),
                )
            )
        result = RetrievalResult(issues=tuple(issue_results))
        debug_dump(
            "PIPELINE :: RETRIEVAL :: CONTRACT",
            {
                "issue_context_counts": {
                    issue.issue_id: len(issue.contexts) for issue in result.issues
                },
                "action_count": len(result.actions),
                "context_count": len(result.contexts),
                "unique_context_count": len(result.context_texts()),
                "action_id_reconciliations": sum(
                    action.id_reconciled for action in result.actions
                ),
                "context_id_reconciliations": sum(
                    context.id_reconciled for context in result.contexts
                ),
                "cross_reference_action_count": sum(
                    action.query_facet == "CROSS_REFERENCE"
                    for action in result.actions
                ),
                "context_group_count": len(
                    {context.group_id for context in result.contexts}
                ),
                "actions": result.action_payloads(),
                "retrieval_budget": self._budget.to_dict(),
            },
        )
        return result


__all__ = ["RetrievalStage"]
