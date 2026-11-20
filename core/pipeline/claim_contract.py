"""Typed, Python-owned provenance contract for atomic legal claims."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    claim_id: str
    issue_id: str
    requirement_id: str
    evidence_id: str
    context_id: str
    citation: str
    proposition: str
    source_quote: str
    source_span_start: int
    source_span_end: int
    source_span_sha256: str


@dataclass(frozen=True, slots=True)
class ClaimExtractionFailure:
    issue_id: str
    requirement_id: str
    evidence_id: str
    context_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ClaimExtractionResult:
    claims: tuple[ClaimRecord, ...]
    failures: tuple[ClaimExtractionFailure, ...]

    def by_requirement_id(self) -> dict[str, tuple[ClaimRecord, ...]]:
        requirement_ids = {
            claim.requirement_id for claim in self.claims
        } | {
            failure.requirement_id for failure in self.failures
        }
        return {
            requirement_id: tuple(
                claim
                for claim in self.claims
                if claim.requirement_id == requirement_id
            )
            for requirement_id in requirement_ids
        }


__all__ = [
    "ClaimExtractionFailure",
    "ClaimExtractionResult",
    "ClaimRecord",
]
