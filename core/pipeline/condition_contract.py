"""Structured condition logic and deterministic application states."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .verification_contract import ClaimVerificationRecord


class ConditionLogic(str, Enum):
    ALL = "ALL"
    ANY = "ANY"
    EXCEPTION = "EXCEPTION"


class ConditionRole(str, Enum):
    SCOPE = "SCOPE"
    TRIGGER = "TRIGGER"
    REMEDY_PRECONDITION = "REMEDY_PRECONDITION"


class ConditionMatchStatus(str, Enum):
    SATISFIED = "SATISFIED"
    CONTRADICTED = "CONTRADICTED"
    UNKNOWN = "UNKNOWN"


class ApplicationStatus(str, Enum):
    APPLIES = "APPLIES"
    GENERAL_RULE = "GENERAL_RULE"
    INSUFFICIENT_FACTS = "INSUFFICIENT_FACTS"
    CONDITION_NOT_MET = "CONDITION_NOT_MET"
    DOES_NOT_APPLY = "DOES_NOT_APPLY"
    EXCEPTION_APPLIES = "EXCEPTION_APPLIES"
    MATCHING_FAILED = "MATCHING_FAILED"


@dataclass(frozen=True, slots=True)
class ConditionRecord:
    condition_id: str
    claim_id: str
    group_id: str
    logic: ConditionLogic
    role: ConditionRole
    condition: str
    source_quote: str
    source_span_start: int
    source_span_end: int
    source_span_sha256: str


@dataclass(frozen=True, slots=True)
class ConditionExtractionFailure:
    claim_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ConditionExtractionResult:
    conditions: tuple[ConditionRecord, ...]
    failures: tuple[ConditionExtractionFailure, ...]

    def for_claim(self, claim_id: str) -> tuple[ConditionRecord, ...]:
        return tuple(
            condition
            for condition in self.conditions
            if condition.claim_id == claim_id
        )


@dataclass(frozen=True, slots=True)
class ConditionMatchRecord:
    condition: ConditionRecord
    status: ConditionMatchStatus
    fact_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ClaimApplicationRecord:
    verification: ClaimVerificationRecord
    status: ApplicationStatus
    matches: tuple[ConditionMatchRecord, ...]
    supporting_fact_ids: tuple[str, ...]
    contradicting_fact_ids: tuple[str, ...]
    exception_fact_ids: tuple[str, ...]
    contradicted_condition_ids: tuple[str, ...]
    unknown_condition_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConditionApplicationResult:
    records: tuple[ClaimApplicationRecord, ...]

    @property
    def publishable_records(self) -> tuple[ClaimApplicationRecord, ...]:
        return tuple(
            record
            for record in self.records
            if record.status
            not in {
                ApplicationStatus.DOES_NOT_APPLY,
                ApplicationStatus.MATCHING_FAILED,
            }
        )


def resolve_application_status(
    verification: ClaimVerificationRecord,
    conditions: tuple[ConditionRecord, ...],
    matches: tuple[ConditionMatchRecord, ...] | None,
) -> ClaimApplicationRecord:
    """Resolve Boolean condition structure without interpreting Vietnamese."""

    if not conditions:
        return ClaimApplicationRecord(
            verification=verification,
            status=ApplicationStatus.GENERAL_RULE,
            matches=(),
            supporting_fact_ids=(),
            contradicting_fact_ids=(),
            exception_fact_ids=(),
            contradicted_condition_ids=(),
            unknown_condition_ids=(),
        )
    if matches is None or {m.condition.condition_id for m in matches} != {
        c.condition_id for c in conditions
    }:
        return ClaimApplicationRecord(
            verification=verification,
            status=ApplicationStatus.MATCHING_FAILED,
            matches=tuple(matches or ()),
            supporting_fact_ids=(),
            contradicting_fact_ids=(),
            exception_fact_ids=(),
            contradicted_condition_ids=(),
            unknown_condition_ids=(),
        )

    by_id = {match.condition.condition_id: match for match in matches}
    exception_matches = [
        by_id[condition.condition_id]
        for condition in conditions
        if condition.logic is ConditionLogic.EXCEPTION
    ]
    all_matches = [
        by_id[condition.condition_id]
        for condition in conditions
        if condition.logic is ConditionLogic.ALL
    ]
    any_groups: dict[str, list[ConditionMatchRecord]] = {}
    for condition in conditions:
        if condition.logic is ConditionLogic.ANY:
            any_groups.setdefault(condition.group_id, []).append(
                by_id[condition.condition_id]
            )

    status = ApplicationStatus.APPLIES
    if any(match.status is ConditionMatchStatus.SATISFIED for match in exception_matches):
        status = ApplicationStatus.EXCEPTION_APPLIES
    else:
        contradicted_all = [
            match
            for match in all_matches
            if match.status is ConditionMatchStatus.CONTRADICTED
        ]
        if any(match.condition.role is ConditionRole.SCOPE for match in contradicted_all):
            status = ApplicationStatus.DOES_NOT_APPLY
        elif contradicted_all:
            status = ApplicationStatus.CONDITION_NOT_MET
        else:
            failed_any_groups = [
                group
                for group in any_groups.values()
                if group
                and all(
                    match.status is ConditionMatchStatus.CONTRADICTED
                    for match in group
                )
            ]
            if failed_any_groups:
                status = (
                    ApplicationStatus.DOES_NOT_APPLY
                    if any(
                        all(match.condition.role is ConditionRole.SCOPE for match in group)
                        for group in failed_any_groups
                    )
                    else ApplicationStatus.CONDITION_NOT_MET
                )
            else:
                unresolved_any = any(
                    not any(
                        match.status is ConditionMatchStatus.SATISFIED
                        for match in group
                    )
                    for group in any_groups.values()
                )
                unresolved = (
                    any(
                        match.status is ConditionMatchStatus.UNKNOWN
                        for match in [*all_matches, *exception_matches]
                    )
                    or unresolved_any
                )
                if unresolved:
                    status = ApplicationStatus.INSUFFICIENT_FACTS

    supporting_fact_ids = tuple(
        dict.fromkeys(
            fact_id
            for match in matches
            if match.status is ConditionMatchStatus.SATISFIED
            and match.condition.logic is not ConditionLogic.EXCEPTION
            for fact_id in match.fact_ids
        )
    )
    contradicting_fact_ids = tuple(
        dict.fromkeys(
            fact_id
            for match in matches
            if match.status is ConditionMatchStatus.CONTRADICTED
            for fact_id in match.fact_ids
        )
    )
    exception_fact_ids = tuple(
        dict.fromkeys(
            fact_id
            for match in matches
            if match.status is ConditionMatchStatus.SATISFIED
            and match.condition.logic is ConditionLogic.EXCEPTION
            for fact_id in match.fact_ids
        )
    )
    return ClaimApplicationRecord(
        verification=verification,
        status=status,
        matches=matches,
        supporting_fact_ids=supporting_fact_ids,
        contradicting_fact_ids=contradicting_fact_ids,
        exception_fact_ids=exception_fact_ids,
        contradicted_condition_ids=tuple(
            match.condition.condition_id
            for match in matches
            if match.status is ConditionMatchStatus.CONTRADICTED
        ),
        unknown_condition_ids=tuple(
            match.condition.condition_id
            for match in matches
            if match.status is ConditionMatchStatus.UNKNOWN
        ),
    )


__all__ = [
    "ApplicationStatus",
    "ClaimApplicationRecord",
    "ConditionApplicationResult",
    "ConditionExtractionFailure",
    "ConditionExtractionResult",
    "ConditionLogic",
    "ConditionMatchRecord",
    "ConditionMatchStatus",
    "ConditionRecord",
    "ConditionRole",
    "resolve_application_status",
]
