"""Typed public-answer units with immutable provenance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .condition_contract import ApplicationStatus


class AnswerPurpose(str, Enum):
    APPLICATION = "APPLICATION"
    GENERAL_RULE = "GENERAL_RULE"
    LIMIT = "LIMIT"
    UNMET_CONDITION = "UNMET_CONDITION"
    EXCEPTION = "EXCEPTION"


class PublicationStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    NO_PUBLISHABLE_CONTENT = "NO_PUBLISHABLE_CONTENT"


@dataclass(frozen=True, slots=True)
class AnswerUnit:
    unit_id: str
    issue_id: str
    requirement_id: str
    claim_id: str
    evidence_id: str
    application_status: ApplicationStatus
    purpose: AnswerPurpose
    fact_ids: tuple[str, ...]
    citation: str
    proposition: str
    analysis: str
    conclusion: str
    next_step: str


@dataclass(frozen=True, slots=True)
class AnswerUnitFailure:
    claim_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class AnswerDraftResult:
    units: tuple[AnswerUnit, ...]
    failures: tuple[AnswerUnitFailure, ...]


@dataclass(frozen=True, slots=True)
class PublishedAnswer:
    text: str
    status: PublicationStatus
    published_unit_ids: tuple[str, ...]
    published_evidence_ids: tuple[str, ...]
    omitted_claim_ids: tuple[str, ...]


__all__ = [
    "AnswerDraftResult",
    "AnswerPurpose",
    "AnswerUnit",
    "AnswerUnitFailure",
    "PublicationStatus",
    "PublishedAnswer",
]
