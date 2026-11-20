"""Typed output of source entailment and Requirement relevance verification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .claim_contract import ClaimRecord


class SourceEntailment(str, Enum):
    YES = "YES"
    NO = "NO"


class RequirementRelevance(str, Enum):
    DIRECT = "DIRECT"
    COMPONENT_SUPPORT = "COMPONENT_SUPPORT"
    ADJACENT = "ADJACENT"
    WRONG_RELATION = "WRONG_RELATION"
    IRRELEVANT = "IRRELEVANT"


@dataclass(frozen=True, slots=True)
class ClaimVerificationRecord:
    claim: ClaimRecord
    source_entailment: SourceEntailment
    requirement_relevance: RequirementRelevance
    grounding_evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    reason: str

    @property
    def usable_for_application(self) -> bool:
        return (
            self.source_entailment is SourceEntailment.YES
            and self.requirement_relevance
            in {
                RequirementRelevance.DIRECT,
                RequirementRelevance.COMPONENT_SUPPORT,
            }
        )


@dataclass(frozen=True, slots=True)
class ClaimVerificationFailure:
    issue_id: str
    requirement_id: str
    claim_ids: tuple[str, ...]
    reason_code: str


@dataclass(frozen=True, slots=True)
class ClaimVerificationResult:
    records: tuple[ClaimVerificationRecord, ...]
    failures: tuple[ClaimVerificationFailure, ...]

    @property
    def usable_records(self) -> tuple[ClaimVerificationRecord, ...]:
        return tuple(record for record in self.records if record.usable_for_application)


__all__ = [
    "ClaimVerificationFailure",
    "ClaimVerificationRecord",
    "ClaimVerificationResult",
    "RequirementRelevance",
    "SourceEntailment",
]
