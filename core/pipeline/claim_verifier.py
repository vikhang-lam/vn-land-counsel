"""Stage 7 - run the locked, fine-tuned Claim Verifier contract."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re

from core.agents.claim_verifier_contract import complete_claim_verifier
from core.config import get_active_settings
from core.evidence import strip_retrieval_metadata
from core.llm import LocalLLMClient
from core.telemetry import record_retry

from .claim_contract import ClaimExtractionResult, ClaimRecord
from .contracts import PlanningResult
from .evidence_contract import EvidenceSelectionResult, SelectedEvidenceRecord
from .prompts import CLAIM_VERIFIER_BASELINE_SPEC
from .verification_contract import (
    ClaimVerificationFailure,
    ClaimVerificationRecord,
    ClaimVerificationResult,
    RequirementRelevance,
    SourceEntailment,
)


@dataclass(frozen=True, slots=True)
class ClaimVerificationBudget:
    max_claims_per_call: int

    @classmethod
    def baseline(cls) -> "ClaimVerificationBudget":
        return cls(max_claims_per_call=2)

    def validate(self) -> None:
        if not 1 <= self.max_claims_per_call <= 2:
            raise ValueError(
                "Adapter Claim Verifier hiện tại chỉ hỗ trợ 1-2 claims mỗi call"
            )


def _temporal_status(source_text: str) -> str:
    match = re.search(
        r"\[THỜI GIAN HIỆU LỰC:\s*([^\]]+)\]",
        str(source_text or ""),
        flags=re.IGNORECASE,
    )
    return match.group(1).strip().upper() if match else "UNKNOWN"


class ClaimVerifierStage:
    def __init__(self, budget: ClaimVerificationBudget | None = None) -> None:
        self.budget = budget or ClaimVerificationBudget.baseline()
        self.budget.validate()

    def run(
        self,
        client: LocalLLMClient,
        *,
        question: str,
        planning: PlanningResult,
        evidence: EvidenceSelectionResult,
        claims: ClaimExtractionResult,
    ) -> ClaimVerificationResult:
        CLAIM_VERIFIER_BASELINE_SPEC.assert_sft_alignment()
        settings = get_active_settings()
        verifier_model = (
            os.getenv("CLAIM_VERIFIER_MODEL", "").strip()
            or settings.adjudicator_model
        )
        issue_by_id = {issue.issue_id: issue for issue in planning.issues}
        requirement_by_id = {
            requirement.requirement_id: requirement
            for issue in planning.issues
            for requirement in issue.requirements
        }
        evidence_by_id: dict[str, SelectedEvidenceRecord] = {
            item.evidence_id: item for item in evidence.selected_evidence
        }
        claims_by_requirement: dict[str, list[ClaimRecord]] = {}
        for claim in claims.claims:
            claims_by_requirement.setdefault(claim.requirement_id, []).append(claim)

        records: list[ClaimVerificationRecord] = []
        failures: list[ClaimVerificationFailure] = []
        for requirement_id, requirement_claims in claims_by_requirement.items():
            requirement = requirement_by_id.get(requirement_id)
            issue = issue_by_id.get(requirement_claims[0].issue_id)
            if requirement is None or issue is None:
                failures.append(
                    ClaimVerificationFailure(
                        issue_id=requirement_claims[0].issue_id,
                        requirement_id=requirement_id,
                        claim_ids=tuple(claim.claim_id for claim in requirement_claims),
                        reason_code="UNKNOWN_PLANNING_ID",
                    )
                )
                continue

            for offset in range(0, len(requirement_claims), self.budget.max_claims_per_call):
                batch = requirement_claims[
                    offset : offset + self.budget.max_claims_per_call
                ]
                source_ids = list(
                    dict.fromkeys(claim.evidence_id for claim in batch)
                )
                selected_sources = [
                    evidence_by_id[evidence_id]
                    for evidence_id in source_ids
                    if evidence_id in evidence_by_id
                ]
                if len(selected_sources) != len(source_ids):
                    failures.append(
                        ClaimVerificationFailure(
                            issue_id=issue.issue_id,
                            requirement_id=requirement_id,
                            claim_ids=tuple(claim.claim_id for claim in batch),
                            reason_code="UNKNOWN_EVIDENCE_ID",
                        )
                    )
                    continue

                call_args = {
                    "model": verifier_model,
                    "question": question,
                    "issue": {
                        "issue_id": issue.issue_id,
                        "issue_type": issue.issue_type,
                        "text": issue.display_text,
                        "time_basis": issue.time_basis,
                    },
                    "requirement": {
                        "requirement_id": requirement.requirement_id,
                        "target_kind": requirement.target_kind,
                        "objective": requirement.objective,
                        "query": requirement.query,
                    },
                    "claims": [
                        {
                            "claim_id": claim.claim_id,
                            "text": claim.proposition,
                            "evidence_ids": [claim.evidence_id],
                        }
                        for claim in batch
                    ],
                    "sources": [
                        {
                            "evidence_id": source.evidence_id,
                            "citation": source.context.citation,
                            "text": strip_retrieval_metadata(
                                source.context.raw_text
                            ),
                            "temporal_status": _temporal_status(
                                source.context.raw_text
                            ),
                        }
                        for source in selected_sources
                    ],
                }
                payload = None
                try:
                    payload = complete_claim_verifier(client, **call_args)
                except Exception:
                    record_retry(
                        "Claim Verifier locked contract",
                        stage_name="Claim Verifier",
                    )
                    try:
                        payload = complete_claim_verifier(client, **call_args)
                    except Exception:
                        payload = None
                if payload is None:
                    failures.append(
                        ClaimVerificationFailure(
                            issue_id=issue.issue_id,
                            requirement_id=requirement_id,
                            claim_ids=tuple(claim.claim_id for claim in batch),
                            reason_code="VERIFIER_CONTRACT_FAILED",
                        )
                    )
                    continue

                batch_by_id = {claim.claim_id: claim for claim in batch}
                for decision in payload.get("decisions", []):
                    claim_id = str(decision["claim_id"]).strip().upper()
                    claim = batch_by_id[claim_id]
                    records.append(
                        ClaimVerificationRecord(
                            claim=claim,
                            source_entailment=SourceEntailment(
                                str(decision["source_entailment"]).upper()
                            ),
                            requirement_relevance=RequirementRelevance(
                                str(decision["requirement_relevance"]).upper()
                            ),
                            grounding_evidence_ids=tuple(
                                str(value).strip().upper()
                                for value in decision["grounding_evidence_ids"]
                            ),
                            reason_codes=tuple(
                                str(value).strip().upper()
                                for value in decision.get("reason_codes", [])
                            ),
                            reason=str(decision.get("reason", "")).strip(),
                        )
                    )

        claim_order = {
            claim.claim_id: index for index, claim in enumerate(claims.claims)
        }
        records.sort(key=lambda record: claim_order[record.claim.claim_id])
        return ClaimVerificationResult(
            records=tuple(records),
            failures=tuple(failures),
        )


__all__ = ["ClaimVerificationBudget", "ClaimVerifierStage"]
