"""Stage 5 - classify evidence semantically, then rank inside each class."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.evidence import strip_retrieval_metadata
from core.json_contracts import reject_duplicate_object_keys
from core.llm import LocalLLMClient
from core.telemetry import record_retry

from .contracts import PlanningResult, RetrievalResult, RetrievedContextRecord
from .evidence_contract import (
    CandidateCoverage,
    EvidenceDecisionRecord,
    EvidenceRelevance,
    EvidenceSelectionResult,
    RequirementEvidenceResult,
    SelectedEvidenceRecord,
)
from .prompts import (
    EVIDENCE_CLASSIFIER_RETRY_INSTRUCTION,
    EVIDENCE_CLASSIFIER_SPEC,
    evidence_classifier_schema,
)


@dataclass(frozen=True, slots=True)
class EvidenceSelectionBudget:
    max_selected_per_requirement: int

    @classmethod
    def baseline(cls) -> "EvidenceSelectionBudget":
        """Reproduce the current four-source downstream ceiling."""

        return cls(max_selected_per_requirement=4)

    def validate(self) -> None:
        if self.max_selected_per_requirement < 1:
            raise ValueError("max_selected_per_requirement phải dương")


def _parse_decisions(
    raw_output: str,
    contexts: list[RetrievedContextRecord],
) -> tuple[EvidenceDecisionRecord, ...] | None:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(raw_output or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        payload = json.loads(
            cleaned,
            object_pairs_hook=reject_duplicate_object_keys,
        )
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"decisions"}:
        return None
    items = payload.get("decisions")
    if not isinstance(items, list):
        return None
    expected_ids = {context.context_id for context in contexts}
    decisions: list[EvidenceDecisionRecord] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "context_id",
            "relevance",
            "reason",
        }:
            return None
        context_id = str(item.get("context_id", "")).strip().upper()
        reason = re.sub(r"\s+", " ", str(item.get("reason", ""))).strip()[:300]
        try:
            relevance = EvidenceRelevance(
                str(item.get("relevance", "")).strip().upper()
            )
        except ValueError:
            return None
        if context_id not in expected_ids or context_id in seen or not reason:
            return None
        seen.add(context_id)
        decisions.append(
            EvidenceDecisionRecord(
                context_id=context_id,
                relevance=relevance,
                reason=reason,
            )
        )
    if seen != expected_ids:
        return None
    order = {context.context_id: index for index, context in enumerate(contexts)}
    decisions.sort(key=lambda decision: order[decision.context_id])
    return tuple(decisions)


def _rank_key(
    context: RetrievedContextRecord,
    original_order: dict[str, int],
) -> tuple[float, int]:
    score = context.rerank_score
    return (
        -(score if score is not None else float("-inf")),
        original_order[context.context_id],
    )


class EvidenceSelectorStage:
    """The model labels meaning; Python ranks only within semantic classes."""

    def __init__(self, budget: EvidenceSelectionBudget | None = None) -> None:
        self.budget = budget or EvidenceSelectionBudget.baseline()
        self.budget.validate()

    def run(
        self,
        client: LocalLLMClient,
        planning: PlanningResult,
        retrieval: RetrievalResult,
    ) -> EvidenceSelectionResult:
        settings = get_active_settings()
        contexts_by_requirement: dict[str, list[RetrievedContextRecord]] = {}
        for context in retrieval.contexts:
            contexts_by_requirement.setdefault(context.requirement_id, []).append(context)

        results: list[RequirementEvidenceResult] = []
        next_evidence_id = 1
        for issue in planning.issues:
            for requirement in issue.requirements:
                contexts = contexts_by_requirement.get(requirement.requirement_id, [])
                if not contexts:
                    results.append(
                        RequirementEvidenceResult(
                            issue_id=issue.issue_id,
                            requirement_id=requirement.requirement_id,
                            coverage=CandidateCoverage.NO_USABLE_CANDIDATE,
                            selected_evidence=(),
                            decisions=(),
                        )
                    )
                    continue

                # Retrieval scores and origins are deliberately absent.  The
                # classifier sees only immutable IDs and legal source text.
                source_payload = [
                    {
                        "context_id": context.context_id,
                        "citation": context.citation,
                        "text": strip_retrieval_metadata(context.raw_text),
                    }
                    for context in contexts
                ]
                message = json.dumps(
                    {
                        "issue": {
                            "issue_id": issue.issue_id,
                            "text": issue.display_text,
                        },
                        "requirement": {
                            "requirement_id": requirement.requirement_id,
                            "target_kind": requirement.target_kind,
                            "objective": requirement.objective,
                            "query": requirement.query,
                        },
                        "sources": source_payload,
                    },
                    ensure_ascii=False,
                )
                schema = evidence_classifier_schema(len(contexts))
                response = client.complete(
                    message,
                    model=settings.evidence_model,
                    system_prompt=EVIDENCE_CLASSIFIER_SPEC.text,
                    temperature=0.0,
                    max_tokens=max(500, 220 * len(contexts)),
                    json_mode=True,
                    json_schema=schema,
                )
                debug_dump(
                    f"PIPELINE :: EVIDENCE CLASSIFIER :: {requirement.requirement_id} :: INPUT",
                    json.loads(message),
                )
                debug_dump(
                    f"PIPELINE :: EVIDENCE CLASSIFIER :: {requirement.requirement_id} :: RAW",
                    response.text,
                )
                decisions = _parse_decisions(response.text, contexts)
                if decisions is None:
                    record_retry(
                        "Evidence classifier output contract",
                        stage_name="Evidence Selector",
                    )
                    retry = client.complete(
                        message
                        + "\n\nVALIDATION_ERRORS: ONE_DECISION_PER_CONTEXT_REQUIRED\n"
                        + EVIDENCE_CLASSIFIER_RETRY_INSTRUCTION,
                        model=settings.evidence_model,
                        system_prompt=EVIDENCE_CLASSIFIER_SPEC.text,
                        temperature=0.0,
                        max_tokens=max(500, 220 * len(contexts)),
                        json_mode=True,
                        json_schema=schema,
                    )
                    debug_dump(
                        f"PIPELINE :: EVIDENCE CLASSIFIER :: {requirement.requirement_id} :: RETRY RAW",
                        retry.text,
                    )
                    decisions = _parse_decisions(retry.text, contexts)

                if decisions is None:
                    results.append(
                        RequirementEvidenceResult(
                            issue_id=issue.issue_id,
                            requirement_id=requirement.requirement_id,
                            coverage=CandidateCoverage.CLASSIFICATION_FAILED,
                            selected_evidence=(),
                            decisions=(),
                            classification_failed=True,
                        )
                    )
                    continue

                by_id = {context.context_id: context for context in contexts}
                order = {context.context_id: index for index, context in enumerate(contexts)}
                direct = sorted(
                    (
                        by_id[decision.context_id]
                        for decision in decisions
                        if decision.relevance is EvidenceRelevance.DIRECT
                    ),
                    key=lambda context: _rank_key(context, order),
                )
                component = sorted(
                    (
                        by_id[decision.context_id]
                        for decision in decisions
                        if decision.relevance is EvidenceRelevance.COMPONENT
                    ),
                    key=lambda context: _rank_key(context, order),
                )
                selected_contexts = tuple(
                    [*direct, *component][
                        : self.budget.max_selected_per_requirement
                    ]
                )
                selected = tuple(
                    SelectedEvidenceRecord(
                        evidence_id=f"E{next_evidence_id + index:03d}",
                        issue_id=issue.issue_id,
                        requirement_id=requirement.requirement_id,
                        context=context,
                    )
                    for index, context in enumerate(selected_contexts)
                )
                next_evidence_id += len(selected)
                coverage = (
                    CandidateCoverage.DIRECT_AVAILABLE
                    if direct
                    else CandidateCoverage.COMPONENT_ONLY
                    if component
                    else CandidateCoverage.NO_USABLE_CANDIDATE
                )
                results.append(
                    RequirementEvidenceResult(
                        issue_id=issue.issue_id,
                        requirement_id=requirement.requirement_id,
                        coverage=coverage,
                        selected_evidence=selected,
                        decisions=decisions,
                    )
                )
                debug_dump(
                    "PIPELINE :: EVIDENCE CLASSIFICATION",
                    {
                        "requirement_id": requirement.requirement_id,
                        "coverage": coverage.value,
                        "selected_context_ids": [
                            item.context.context_id for item in selected
                        ],
                        "selected_evidence_ids": [
                            item.evidence_id for item in selected
                        ],
                        "decisions": [
                            {
                                "context_id": decision.context_id,
                                "relevance": decision.relevance.value,
                                "reason": decision.reason,
                            }
                            for decision in decisions
                        ],
                    },
                )
        return EvidenceSelectionResult(requirements=tuple(results))


__all__ = ["EvidenceSelectionBudget", "EvidenceSelectorStage"]
