"""Typed contract for requirement-scoped evidence classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import RetrievedContextRecord


class EvidenceRelevance(str, Enum):
    DIRECT = "DIRECT"
    COMPONENT = "COMPONENT"
    ADJACENT = "ADJACENT"
    IRRELEVANT = "IRRELEVANT"


class CandidateCoverage(str, Enum):
    DIRECT_AVAILABLE = "DIRECT_AVAILABLE"
    COMPONENT_ONLY = "COMPONENT_ONLY"
    NO_USABLE_CANDIDATE = "NO_USABLE_CANDIDATE"
    CLASSIFICATION_FAILED = "CLASSIFICATION_FAILED"


@dataclass(frozen=True, slots=True)
class EvidenceDecisionRecord:
    context_id: str
    relevance: EvidenceRelevance
    reason: str


@dataclass(frozen=True, slots=True)
class SelectedEvidenceRecord:
    evidence_id: str
    issue_id: str
    requirement_id: str
    context: RetrievedContextRecord


@dataclass(frozen=True, slots=True)
class RequirementEvidenceResult:
    issue_id: str
    requirement_id: str
    coverage: CandidateCoverage
    selected_evidence: tuple[SelectedEvidenceRecord, ...]
    decisions: tuple[EvidenceDecisionRecord, ...]
    classification_failed: bool = False

    @property
    def selected_contexts(self) -> tuple[RetrievedContextRecord, ...]:
        return tuple(item.context for item in self.selected_evidence)


@dataclass(frozen=True, slots=True)
class EvidenceSelectionResult:
    requirements: tuple[RequirementEvidenceResult, ...]

    @property
    def selected_contexts(self) -> tuple[RetrievedContextRecord, ...]:
        return tuple(
            item.context
            for requirement in self.requirements
            for item in requirement.selected_evidence
        )

    @property
    def selected_evidence(self) -> tuple[SelectedEvidenceRecord, ...]:
        return tuple(
            item
            for requirement in self.requirements
            for item in requirement.selected_evidence
        )

    def by_requirement_id(self) -> dict[str, RequirementEvidenceResult]:
        return {
            requirement.requirement_id: requirement
            for requirement in self.requirements
        }


__all__ = [
    "CandidateCoverage",
    "EvidenceDecisionRecord",
    "EvidenceRelevance",
    "EvidenceSelectionResult",
    "RequirementEvidenceResult",
    "SelectedEvidenceRecord",
]
