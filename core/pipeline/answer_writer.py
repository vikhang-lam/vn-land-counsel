"""Stage 10 - write one public unit for each publishable application record."""

from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Any

from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.json_contracts import reject_duplicate_object_keys
from core.llm import LocalLLMClient
from core.telemetry import record_retry

from .answer_contract import (
    AnswerDraftResult,
    AnswerPurpose,
    AnswerUnit,
    AnswerUnitFailure,
)
from .condition_contract import (
    ApplicationStatus,
    ConditionApplicationResult,
    ConditionMatchStatus,
)
from .contracts import FactRecord
from .contracts import PlanningResult
from .prompts import (
    ANSWER_UNIT_JSON_SCHEMA,
    ANSWER_UNIT_RETRY_INSTRUCTION,
    ANSWER_UNIT_SPEC,
)


_INTERNAL_ID_RE = re.compile(r"\b(?:Q|F|I|R|RC|E|C|K|KC|AF|S)\d{3,}(?:_\d{2})?\b")
_LEGAL_LOCATOR_RE = re.compile(
    r"\b(?:Điều\s+\d+|Khoản\s+\d+|Điểm\s+[A-Za-zĐđ])\b",
    flags=re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)*\b")


def _purpose(status: ApplicationStatus) -> AnswerPurpose:
    return {
        ApplicationStatus.APPLIES: AnswerPurpose.APPLICATION,
        ApplicationStatus.GENERAL_RULE: AnswerPurpose.GENERAL_RULE,
        ApplicationStatus.INSUFFICIENT_FACTS: AnswerPurpose.LIMIT,
        ApplicationStatus.CONDITION_NOT_MET: AnswerPurpose.UNMET_CONDITION,
        ApplicationStatus.EXCEPTION_APPLIES: AnswerPurpose.EXCEPTION,
    }[status]


def _allowed_fact_ids(record) -> tuple[str, ...]:
    if record.status is ApplicationStatus.APPLIES:
        return record.supporting_fact_ids
    if record.status is ApplicationStatus.CONDITION_NOT_MET:
        return record.contradicting_fact_ids
    if record.status is ApplicationStatus.EXCEPTION_APPLIES:
        return record.exception_fact_ids
    if record.status is ApplicationStatus.INSUFFICIENT_FACTS:
        return record.supporting_fact_ids
    return ()


def _parse_unit(raw_output: str, allowed_input_text: str) -> dict[str, str] | None:
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
    if not isinstance(payload, dict) or set(payload) != {
        "analysis",
        "conclusion",
        "next_step",
    }:
        return None
    output = {
        key: re.sub(r"\s+", " ", str(payload.get(key, ""))).strip()
        for key in ("analysis", "conclusion", "next_step")
    }
    if not output["analysis"]:
        return None
    public_text = " ".join(output.values())
    if _INTERNAL_ID_RE.search(public_text) or _LEGAL_LOCATOR_RE.search(public_text):
        return None
    allowed_numbers = set(_NUMBER_RE.findall(allowed_input_text))
    if set(_NUMBER_RE.findall(public_text)) - allowed_numbers:
        return None
    return output


class AnswerWriterStage:
    def run(
        self,
        client: LocalLLMClient,
        *,
        facts: list[FactRecord],
        application: ConditionApplicationResult,
        question: str = "",
        planning: PlanningResult | None = None,
        response_mode: str = "consultation",
    ) -> AnswerDraftResult:
        settings = get_active_settings()
        facts_by_id = {fact.fact_id: fact for fact in facts}
        units: list[AnswerUnit] = []
        failures: list[AnswerUnitFailure] = []
        issue_by_id = {
            issue.issue_id: issue for issue in getattr(planning, "issues", ())
        }
        requirement_by_id = {
            requirement.requirement_id: requirement
            for issue in getattr(planning, "issues", ())
            for requirement in issue.requirements
        }

        records_by_issue: dict[str, list] = {}
        for record in application.publishable_records:
            records_by_issue.setdefault(
                record.verification.claim.issue_id,
                [],
            ).append(record)
        discourse_positions: dict[str, dict[str, int | str]] = {}
        for issue_records in records_by_issue.values():
            total = len(issue_records)
            for index, record in enumerate(issue_records):
                claim_id = record.verification.claim.claim_id
                discourse_positions[claim_id] = {
                    "position": (
                        "ONLY"
                        if total == 1
                        else "FIRST"
                        if index == 0
                        else "LAST"
                        if index == total - 1
                        else "MIDDLE"
                    ),
                    "index": index + 1,
                    "total": total,
                }

        for record in application.publishable_records:
            if record.status not in {
                ApplicationStatus.APPLIES,
                ApplicationStatus.GENERAL_RULE,
                ApplicationStatus.INSUFFICIENT_FACTS,
                ApplicationStatus.CONDITION_NOT_MET,
                ApplicationStatus.EXCEPTION_APPLIES,
            }:
                continue
            claim = record.verification.claim
            allowed_fact_ids = _allowed_fact_ids(record)
            fact_payload = [
                {
                    "fact_id": fact_id,
                    "text": facts_by_id[fact_id].value,
                }
                for fact_id in allowed_fact_ids
                if fact_id in facts_by_id
            ]
            condition_payload = [
                {
                    "condition": match.condition.condition,
                    "logic": match.condition.logic.value,
                    "role": match.condition.role.value,
                    "status": match.status.value,
                }
                for match in record.matches
                if match.status
                in {
                    ConditionMatchStatus.UNKNOWN,
                    ConditionMatchStatus.CONTRADICTED,
                }
                or match.condition.logic.value == "EXCEPTION"
            ]
            payload: dict[str, Any] = {
                "question": str(question or "").strip(),
                "issue": (
                    {
                        "text": issue_by_id[claim.issue_id].display_text,
                        "issue_type": issue_by_id[claim.issue_id].issue_type,
                    }
                    if claim.issue_id in issue_by_id else {}
                ),
                "requirement": (
                    {
                        "target_kind": requirement_by_id[
                            claim.requirement_id
                        ].target_kind,
                        "objective": requirement_by_id[
                            claim.requirement_id
                        ].objective,
                    }
                    if claim.requirement_id in requirement_by_id else {}
                ),
                "response_mode": str(response_mode or "consultation"),
                "proposition": claim.proposition,
                "application_status": record.status.value,
                "facts": fact_payload,
                "conditions": condition_payload,
                "discourse_position": discourse_positions.get(
                    claim.claim_id,
                    {"position": "ONLY", "index": 1, "total": 1},
                ),
            }
            message = json.dumps(payload, ensure_ascii=False)
            response = client.complete(
                message,
                model=settings.adjudicator_model,
                system_prompt=ANSWER_UNIT_SPEC.text,
                temperature=0.1,
                max_tokens=800,
                json_mode=True,
                json_schema=ANSWER_UNIT_JSON_SCHEMA,
            )
            debug_dump(
                f"PIPELINE :: ANSWER WRITER :: {claim.claim_id} :: INPUT",
                payload,
            )
            debug_dump(
                f"PIPELINE :: ANSWER WRITER :: {claim.claim_id} :: RAW",
                response.text,
            )
            output = _parse_unit(response.text, message)
            if output is None:
                record_retry(
                    "Answer Unit output contract",
                    stage_name="Answer Writer",
                )
                retry = client.complete(
                    message
                    + "\n\nVALIDATION_ERRORS: PUBLIC_UNIT_CONTRACT_OR_PROVENANCE_INVALID\n"
                    + ANSWER_UNIT_RETRY_INSTRUCTION,
                    model=settings.adjudicator_model,
                    system_prompt=ANSWER_UNIT_SPEC.text,
                    temperature=0.0,
                    max_tokens=800,
                    json_mode=True,
                    json_schema=ANSWER_UNIT_JSON_SCHEMA,
                )
                debug_dump(
                    f"PIPELINE :: ANSWER WRITER :: {claim.claim_id} :: RETRY RAW",
                    retry.text,
                )
                output = _parse_unit(retry.text, message)
            if output is None:
                failures.append(
                    AnswerUnitFailure(
                        claim_id=claim.claim_id,
                        reason_code="ANSWER_UNIT_CONTRACT_FAILED",
                    )
                )
                continue
            units.append(
                AnswerUnit(
                    unit_id=f"S{len(units) + 1:03d}",
                    issue_id=claim.issue_id,
                    requirement_id=claim.requirement_id,
                    claim_id=claim.claim_id,
                    evidence_id=claim.evidence_id,
                    application_status=record.status,
                    purpose=_purpose(record.status),
                    fact_ids=allowed_fact_ids,
                    citation=claim.citation,
                    proposition=claim.proposition,
                    analysis=output["analysis"],
                    conclusion=output["conclusion"],
                    next_step=output["next_step"],
                )
            )

        result = AnswerDraftResult(units=tuple(units), failures=tuple(failures))
        debug_dump("PIPELINE :: ANSWER WRITER :: VALIDATED", asdict(result))
        return result


__all__ = ["AnswerWriterStage"]
