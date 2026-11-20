"""Phục hồi nguồn theo Requirement mà không chạy lại bản ghi đã được duyệt."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
import re
from typing import Any, Callable

from core.agents.transport import sanitize_retrieval_query
from core.article_guard import explicit_article_numbers
from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.llm import LocalLLMClient
from core.retrieval_plan import execute_retrieval_plan

from .claim_contract import ClaimExtractionResult, ClaimRecord
from .condition_contract import (
    ApplicationStatus,
    ConditionApplicationResult,
    ConditionExtractionResult,
    ConditionRecord,
)
from .contracts import (
    FactRecord,
    IssueRecord,
    IssueRetrievalResult,
    PlanningResult,
    RetrievalActionRecord,
    RetrievalResult,
    RetrievedContextRecord,
)
from .evidence_contract import (
    CandidateCoverage,
    EvidenceSelectionResult,
    RequirementEvidenceResult,
    SelectedEvidenceRecord,
)
from .prompts import RETRIEVAL_RECOVERY_QUERY_SPEC, retrieval_query_variant_schema
from .retrieval import _context_identity, _select_requirement_contexts
from .retrieval_contract import RetrievalBudget
from .verification_contract import ClaimVerificationResult


Executor = Callable[[list[dict[str, Any]]], list[str]]
QueryBuilder = Callable[..., str]


@dataclass(frozen=True, slots=True)
class RecoveryTarget:
    issue: IssueRecord
    requirement_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class IncrementalRecoveryResult:
    retrieval: RetrievalResult
    evidence: EvidenceSelectionResult
    claims: ClaimExtractionResult
    verification: ClaimVerificationResult
    application: ConditionApplicationResult
    attempted_requirement_ids: tuple[str, ...]
    committed_requirement_ids: tuple[str, ...]
    skipped: tuple[dict[str, str], ...]

    @property
    def committed(self) -> bool:
        return bool(self.committed_requirement_ids)


def incremental_recovery_enabled() -> bool:
    return os.getenv(
        "PIPELINE_INCREMENTAL_RECOVERY_ENABLED", "false"
    ).strip().casefold() in {"1", "true", "yes", "on"}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(0, value)


def _numeric_suffix(value: str, prefix: str) -> int:
    match = re.fullmatch(re.escape(prefix) + r"(\d+)", str(value or "").upper())
    return int(match.group(1)) if match else 0


def _next_id(values, prefix: str, width: int) -> int:
    return max((_numeric_suffix(value, prefix) for value in values), default=0) + 1


def _normalize_claim(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" .;:").casefold()


def _requirement_index(planning: PlanningResult) -> dict[str, tuple[IssueRecord, Any]]:
    return {
        requirement.requirement_id: (issue, requirement)
        for issue in planning.issues
        for requirement in issue.requirements
    }


def requirements_for_recovery(
    planning: PlanningResult,
    evidence: EvidenceSelectionResult,
    claims: ClaimExtractionResult,
    verification: ClaimVerificationResult,
    application: ConditionApplicationResult,
    *,
    limit: int,
) -> tuple[RecoveryTarget, ...]:
    """Chỉ chọn lỗi có khả năng được cải thiện bằng một nguồn khác."""

    if limit < 1:
        return ()
    evidence_by_id = evidence.by_requirement_id()
    claims_by_id = claims.by_requirement_id()
    verification_by_id: dict[str, list] = {}
    for record in verification.records:
        verification_by_id.setdefault(record.claim.requirement_id, []).append(record)
    application_by_id: dict[str, list] = {}
    for record in application.records:
        application_by_id.setdefault(
            record.verification.claim.requirement_id, []
        ).append(record)

    targets: list[RecoveryTarget] = []
    for issue in planning.issues:
        for requirement in issue.requirements:
            requirement_id = requirement.requirement_id
            applications = application_by_id.get(requirement_id, [])
            # Một trạng thái áp dụng đã được quyết định là kết quả hợp lệ. Không
            # tìm quy tắc khác để thay thế hoặc làm thay đổi kết quả đó.
            if any(
                record.status is not ApplicationStatus.MATCHING_FAILED
                for record in applications
            ):
                continue
            selection = evidence_by_id.get(requirement_id)
            reason = ""
            if selection is None or selection.coverage is CandidateCoverage.NO_USABLE_CANDIDATE:
                reason = "NO_USABLE_CANDIDATE"
            elif selection.classification_failed:
                # Đây là lỗi bộ phân loại, không phải lỗi truy xuất.
                continue
            elif selection.selected_evidence and not claims_by_id.get(requirement_id):
                reason = "NO_EXTRACTED_CLAIM"
            else:
                records = verification_by_id.get(requirement_id, [])
                if records and not any(record.usable_for_application for record in records):
                    reason = "NO_VERIFIED_CLAIM"
            if reason:
                targets.append(RecoveryTarget(issue, requirement_id, reason))
                if len(targets) >= limit:
                    return tuple(targets)
    return tuple(targets)


def _recovery_query(
    client: LocalLLMClient,
    *,
    question: str,
    issue: IssueRecord,
    requirement,
    facts: list[FactRecord],
    previous_queries: tuple[str, ...],
    reason_code: str,
    budget: RetrievalBudget,
) -> str:
    linked = set(requirement.fact_ids)
    fact_payload = [
        {"category": fact.category, "text": fact.value}
        for fact in facts
        if fact.fact_id in linked
    ]
    message = json.dumps(
        {
            "request": sanitize_retrieval_query(
                question, [fact.to_dict() for fact in facts]
            ),
            "issue": issue.display_text,
            "requirement": {
                "target_kind": requirement.target_kind,
                "objective": requirement.objective,
            },
            "linked_facts": fact_payload,
            "previous_queries": list(previous_queries),
            "failure_reason": reason_code,
        },
        ensure_ascii=False,
    )
    response = client.complete(
        message,
        model=get_active_settings().adjudicator_model,
        system_prompt=RETRIEVAL_RECOVERY_QUERY_SPEC.text,
        temperature=0.0,
        max_tokens=120,
        json_mode=True,
        json_schema=retrieval_query_variant_schema(budget.max_query_chars),
    )
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", str(response.text or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(payload, dict) or set(payload) != {"query"}:
        return ""
    candidate = sanitize_retrieval_query(
        str(payload.get("query", "")),
        [fact.to_dict() for fact in facts],
    ).strip(" .;:")
    if not candidate or len(candidate) > budget.max_query_chars:
        return ""
    previous = {re.sub(r"\s+", " ", value).strip().casefold() for value in previous_queries}
    if re.sub(r"\s+", " ", candidate).strip().casefold() in previous:
        return ""
    allowed_articles = set(explicit_article_numbers(question))
    for value in previous_queries:
        allowed_articles.update(explicit_article_numbers(value))
    if explicit_article_numbers(candidate) - allowed_articles:
        return ""
    return candidate


def _subset_planning(
    planning: PlanningResult,
    issue: IssueRecord,
    requirement_id: str,
) -> PlanningResult:
    requirement = next(
        item for item in issue.requirements if item.requirement_id == requirement_id
    )
    issue_only = replace(issue, requirements=(requirement,))
    return PlanningResult(
        issue_texts=(issue.display_text,),
        issues=(issue_only,),
        temporal_context=planning.temporal_context,
        temporal_payload=planning.temporal_payload,
    )


def _previous_queries(retrieval: RetrievalResult, requirement_id: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            action.query_text
            for action in retrieval.actions
            if action.requirement_id == requirement_id and action.query_text
        )
    )


def _action_scope(retrieval: RetrievalResult, requirement_id: str) -> dict[str, Any]:
    for action in retrieval.actions:
        if action.requirement_id == requirement_id:
            return {
                key: action.raw[key]
                for key in ("target_date", "is_transitional", "named_document")
                if action.raw.get(key) not in (None, "")
            }
    return {}


def _append_retrieval(
    current: RetrievalResult,
    issue_id: str,
    action: RetrievalActionRecord,
    contexts: tuple[RetrievedContextRecord, ...],
) -> RetrievalResult:
    issues = []
    for issue in current.issues:
        if issue.issue_id == issue_id:
            issues.append(replace(
                issue,
                actions=(*issue.actions, action),
                contexts=(*issue.contexts, *contexts),
            ))
        else:
            issues.append(issue)
    return RetrievalResult(issues=tuple(issues))


def _append_evidence(
    current: EvidenceSelectionResult,
    delta: RequirementEvidenceResult,
) -> EvidenceSelectionResult:
    output = []
    for item in current.requirements:
        if item.requirement_id != delta.requirement_id:
            output.append(item)
            continue
        coverage = (
            CandidateCoverage.DIRECT_AVAILABLE
            if CandidateCoverage.DIRECT_AVAILABLE in {item.coverage, delta.coverage}
            else CandidateCoverage.COMPONENT_ONLY
            if CandidateCoverage.COMPONENT_ONLY in {item.coverage, delta.coverage}
            else item.coverage
        )
        output.append(replace(
            item,
            coverage=coverage,
            selected_evidence=(*item.selected_evidence, *delta.selected_evidence),
            decisions=(*item.decisions, *delta.decisions),
            classification_failed=False,
        ))
    return EvidenceSelectionResult(requirements=tuple(output))


def _assert_append_only(before: tuple, after: tuple, label: str) -> None:
    if after[:len(before)] != before:
        raise ValueError(f"Recovery đã thay đổi phần {label} được duyệt trước đó.")


def _assert_preserved(before: tuple, after: tuple, label: str, key) -> None:
    """Cho phép chèn theo Issue/Requirement nhưng cấm sửa hoặc xóa bản ghi cũ."""

    after_by_id = {key(item): item for item in after}
    if len(after_by_id) != len(after):
        raise ValueError(f"Recovery tạo ID trùng trong {label}.")
    for item in before:
        if after_by_id.get(key(item)) != item:
            raise ValueError(f"Recovery đã sửa hoặc xóa {label} được duyệt trước đó.")


class IncrementalRecoveryStage:
    """Một vòng phục hồi có giới hạn; commit theo từng Requirement."""

    def __init__(
        self,
        *,
        executor: Executor = execute_retrieval_plan,
        query_builder: QueryBuilder = _recovery_query,
        budget: RetrievalBudget | None = None,
        max_requirements: int | None = None,
    ) -> None:
        self.executor = executor
        self.query_builder = query_builder
        self.budget = budget or RetrievalBudget.baseline()
        self.budget.validate()
        self.max_requirements = (
            _positive_int_env("PIPELINE_RECOVERY_MAX_REQUIREMENTS", 2)
            if max_requirements is None else max(0, max_requirements)
        )

    def run(
        self,
        client: LocalLLMClient,
        *,
        question: str,
        facts: list[FactRecord],
        planning: PlanningResult,
        retrieval: RetrievalResult,
        evidence: EvidenceSelectionResult,
        claims: ClaimExtractionResult,
        verification: ClaimVerificationResult,
        application: ConditionApplicationResult,
    ) -> IncrementalRecoveryResult:
        targets = requirements_for_recovery(
            planning, evidence, claims, verification, application,
            limit=self.max_requirements,
        )
        attempted: list[str] = []
        committed: list[str] = []
        skipped: list[dict[str, str]] = []
        current_retrieval = retrieval
        current_evidence = evidence
        current_claims = claims
        current_verification = verification
        current_application = application

        for target in targets:
            attempted.append(target.requirement_id)
            try:
                result = self._recover_one(
                    client,
                    target=target,
                    question=question,
                    facts=facts,
                    planning=planning,
                    retrieval=current_retrieval,
                    evidence=current_evidence,
                    claims=current_claims,
                    verification=current_verification,
                    application=current_application,
                )
                if result is None:
                    skipped.append({
                        "requirement_id": target.requirement_id,
                        "reason": "NO_NEW_PUBLISHABLE_APPLICATION",
                    })
                    continue
                (
                    next_retrieval,
                    next_evidence,
                    next_claims,
                    next_verification,
                    next_application,
                ) = result
                _assert_preserved(
                    current_retrieval.actions, next_retrieval.actions,
                    "action", lambda item: item.action_id,
                )
                _assert_preserved(
                    current_retrieval.contexts, next_retrieval.contexts,
                    "context", lambda item: item.context_id,
                )
                _assert_preserved(
                    current_evidence.selected_evidence, next_evidence.selected_evidence,
                    "evidence", lambda item: item.evidence_id,
                )
                _assert_append_only(current_claims.claims, next_claims.claims, "claim")
                _assert_append_only(current_verification.records, next_verification.records, "verification")
                _assert_append_only(current_application.records, next_application.records, "application")
                current_retrieval = next_retrieval
                current_evidence = next_evidence
                current_claims = next_claims
                current_verification = next_verification
                current_application = next_application
                committed.append(target.requirement_id)
            except Exception as error:
                skipped.append({
                    "requirement_id": target.requirement_id,
                    "reason": type(error).__name__,
                })
                debug_dump(
                    "PIPELINE :: INCREMENTAL RECOVERY :: ROLLBACK",
                    {"requirement_id": target.requirement_id, "error": str(error)},
                )

        outcome = IncrementalRecoveryResult(
            retrieval=current_retrieval,
            evidence=current_evidence,
            claims=current_claims,
            verification=current_verification,
            application=current_application,
            attempted_requirement_ids=tuple(attempted),
            committed_requirement_ids=tuple(committed),
            skipped=tuple(skipped),
        )
        debug_dump(
            "PIPELINE :: INCREMENTAL RECOVERY :: RESULT",
            {
                "attempted_requirement_ids": outcome.attempted_requirement_ids,
                "committed_requirement_ids": outcome.committed_requirement_ids,
                "skipped": outcome.skipped,
            },
        )
        return outcome

    def _recover_one(
        self,
        client,
        *,
        target,
        question,
        facts,
        planning,
        retrieval,
        evidence,
        claims,
        verification,
        application,
    ):
        index = _requirement_index(planning)
        issue, requirement = index[target.requirement_id]
        previous_queries = _previous_queries(retrieval, target.requirement_id)
        recovery_query = self.query_builder(
            client,
            question=question,
            issue=issue,
            requirement=requirement,
            facts=facts,
            previous_queries=previous_queries,
            reason_code=target.reason_code,
            budget=self.budget,
        )
        if not recovery_query:
            return None
        action_payload = {
            "tool": "search_law",
            "query": recovery_query,
            "requirement_id": target.requirement_id,
            "query_origin": "INCREMENTAL_RECOVERY",
            "candidate_k": self.budget.candidate_k,
            "top_k": self.budget.rerank_k,
            **_action_scope(retrieval, target.requirement_id),
        }
        raw_contexts = self.executor([action_payload])
        existing = {
            _context_identity(context.raw_text)
            for context in retrieval.contexts
            if context.requirement_id == target.requirement_id
        }
        fresh = [
            value for value in _select_requirement_contexts(
                list(raw_contexts), self.budget.rerank_k
            )
            if _context_identity(value) not in existing
        ]
        if not fresh:
            return None

        next_action = _next_id((item.action_id for item in retrieval.actions), "A", 3)
        next_context = _next_id((item.context_id for item in retrieval.contexts), "RC", 4)
        next_group = _next_id((item.group_id for item in retrieval.contexts), "G", 4)
        action = RetrievalActionRecord.from_mapping(
            action_payload,
            action_id=f"A{next_action:03d}",
            issue_id=target.issue.issue_id,
            requirement_id=target.requirement_id,
        )
        contexts = tuple(
            RetrievedContextRecord.from_text(
                text,
                context_id=f"RC{next_context + offset:04d}",
                issue_id=target.issue.issue_id,
                requirement_id=target.requirement_id,
                group_id=f"G{next_group:04d}",
                action_id=action.action_id,
                origin="RECOVERY",
            )
            for offset, text in enumerate(fresh)
        )
        delta_retrieval = RetrievalResult(issues=(IssueRetrievalResult(
            issue_id=target.issue.issue_id,
            contexts=contexts,
            actions=(action,),
        ),))
        subset = _subset_planning(planning, issue, target.requirement_id)

        from .evidence_selector import EvidenceSelectorStage
        selected_local = EvidenceSelectorStage().run(client, subset, delta_retrieval)
        selected_result = selected_local.requirements[0]
        if not selected_result.selected_evidence:
            return None
        next_evidence = _next_id(
            (item.evidence_id for item in evidence.selected_evidence), "E", 3
        )
        evidence_map = {
            item.evidence_id: f"E{next_evidence + offset:03d}"
            for offset, item in enumerate(selected_result.selected_evidence)
        }
        selected_result = replace(
            selected_result,
            selected_evidence=tuple(
                replace(item, evidence_id=evidence_map[item.evidence_id])
                for item in selected_result.selected_evidence
            ),
        )
        delta_evidence = EvidenceSelectionResult(requirements=(selected_result,))

        from .claim_extractor import ClaimExtractorStage
        extracted = ClaimExtractorStage().run(client, subset, delta_evidence)
        # Nguồn mới đã được loại trùng theo nội dung trước đó. Không loại Claim
        # chỉ vì proposition giống Claim cũ: một nguồn khác có thể hỗ trợ chính
        # proposition mà nguồn cũ đã bị Verifier bác. Claim mới vẫn mang E/RC mới
        # và là bản ghi độc lập; Claim cũ không bị gọi lại hay thay thế.
        unique_claims = list(extracted.claims)
        if not unique_claims:
            return None
        next_claim = _next_id((item.claim_id for item in claims.claims), "C", 3)
        remapped_claims = tuple(
            replace(claim, claim_id=f"C{next_claim + offset:03d}")
            for offset, claim in enumerate(unique_claims)
        )
        delta_claims = ClaimExtractionResult(
            claims=remapped_claims,
            failures=extracted.failures,
        )

        from .claim_verifier import ClaimVerifierStage
        delta_verification = ClaimVerifierStage().run(
            client,
            question=question,
            planning=subset,
            evidence=delta_evidence,
            claims=delta_claims,
        )
        if not delta_verification.usable_records:
            return None

        from .condition_extractor import ConditionExtractorStage
        extracted_conditions = ConditionExtractorStage().run(
            client, delta_verification, delta_evidence
        )
        old_conditions = tuple(
            match.condition
            for record in application.records
            for match in record.matches
        )
        next_condition = _next_id(
            (item.condition_id for item in old_conditions), "K", 3
        )
        next_condition_group = _next_id(
            (item.group_id for item in old_conditions), "KC", 3
        )
        group_map: dict[str, str] = {}
        remapped_conditions: list[ConditionRecord] = []
        for condition in extracted_conditions.conditions:
            if condition.group_id not in group_map:
                group_map[condition.group_id] = f"KC{next_condition_group + len(group_map):03d}"
            remapped_conditions.append(replace(
                condition,
                condition_id=f"K{next_condition + len(remapped_conditions):03d}",
                group_id=group_map[condition.group_id],
            ))
        delta_conditions = ConditionExtractionResult(
            conditions=tuple(remapped_conditions),
            failures=extracted_conditions.failures,
        )

        from .condition_matcher import ConditionMatcherStage
        delta_application = ConditionMatcherStage().run(
            client,
            facts=facts,
            verification=delta_verification,
            extraction=delta_conditions,
        )
        if not delta_application.publishable_records:
            return None

        merged_retrieval = _append_retrieval(
            retrieval, target.issue.issue_id, action, contexts
        )
        merged_evidence = _append_evidence(evidence, selected_result)
        merged_claims = ClaimExtractionResult(
            claims=(*claims.claims, *delta_claims.claims),
            failures=(*claims.failures, *delta_claims.failures),
        )
        merged_verification = ClaimVerificationResult(
            records=(*verification.records, *delta_verification.records),
            failures=(*verification.failures, *delta_verification.failures),
        )
        merged_application = ConditionApplicationResult(
            records=(*application.records, *delta_application.records),
        )
        return (
            merged_retrieval,
            merged_evidence,
            merged_claims,
            merged_verification,
            merged_application,
        )


__all__ = [
    "IncrementalRecoveryResult",
    "IncrementalRecoveryStage",
    "RecoveryTarget",
    "incremental_recovery_enabled",
    "requirements_for_recovery",
]
