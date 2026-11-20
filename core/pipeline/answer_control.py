"""Kiểm tra và sửa từng Answer Unit; tuyệt đối không gọi công cụ truy xuất."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import os
import re

from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.json_contracts import reject_duplicate_object_keys
from core.llm import LocalLLMClient
from core.telemetry import record_retry

from .answer_contract import AnswerDraftResult, AnswerUnit, AnswerUnitFailure
from .answer_writer import _parse_unit
from .condition_contract import ConditionApplicationResult, ConditionMatchStatus
from .contracts import FactRecord, PlanningResult
from .prompts import (
    ANSWER_UNIT_BATCH_REVISER_SPEC,
    ANSWER_UNIT_AUDIT_SPEC,
    ANSWER_UNIT_JSON_SCHEMA,
    ANSWER_UNIT_REVISER_SPEC,
    answer_unit_audit_schema,
    answer_unit_revision_schema,
)


_REVISION_BATCH_SIZE = 4


@dataclass(frozen=True, slots=True)
class AnswerControlResult:
    draft: AnswerDraftResult
    kept_unit_ids: tuple[str, ...]
    revised_unit_ids: tuple[str, ...]
    dropped_unit_ids: tuple[str, ...]
    audit_failed_unit_ids: tuple[str, ...]


def answer_control_enabled() -> bool:
    return os.getenv(
        "PIPELINE_ANSWER_CONTROL_ENABLED", "false"
    ).strip().casefold() in {"1", "true", "yes", "on"}


def _parse_audit(raw: str, unit_ids: tuple[str, ...]):
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", str(raw or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        payload = json.loads(cleaned, object_pairs_hook=reject_duplicate_object_keys)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"decisions"}:
        return None
    items = payload.get("decisions")
    if not isinstance(items, list) or len(items) != len(unit_ids):
        return None
    expected = set(unit_ids)
    allowed_reasons = {
        "OFF_REQUEST", "STATUS_MISAPPLIED", "UNKNOWN_ASSERTED",
        "UNSUPPORTED_ACTION", "UNSUPPORTED_FACT", "OTHER_SCOPE_ERROR",
    }
    output = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "unit_id", "decision", "reason_codes", "feedback"
        }:
            return None
        unit_id = str(item.get("unit_id", "")).strip().upper()
        decision = str(item.get("decision", "")).strip().upper()
        reasons = item.get("reason_codes")
        feedback = re.sub(r"\s+", " ", str(item.get("feedback", ""))).strip()
        if (
            unit_id not in expected or unit_id in output
            or decision not in {"KEEP", "REVISE", "DROP"}
            or not isinstance(reasons, list)
            or any(str(value).strip().upper() not in allowed_reasons for value in reasons)
            or decision in {"REVISE", "DROP"} and not feedback
        ):
            return None
        output[unit_id] = {
            "decision": decision,
            "reason_codes": tuple(str(value).strip().upper() for value in reasons),
            "feedback": feedback,
        }
    return output if set(output) == expected else None


def _parse_batch_revisions(
    raw: str,
    unit_ids: tuple[str, ...],
    allowed_inputs: dict[str, str],
) -> dict[str, dict[str, str]] | None:
    """Parse one revision batch without allowing IDs or facts to cross units."""

    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", str(raw or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        payload = json.loads(cleaned, object_pairs_hook=reject_duplicate_object_keys)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"revisions"}:
        return None
    revisions = payload.get("revisions")
    if not isinstance(revisions, list) or len(revisions) != len(unit_ids):
        return None
    expected = set(unit_ids)
    parsed: dict[str, dict[str, str]] = {}
    for item in revisions:
        if not isinstance(item, dict) or set(item) != {
            "unit_id", "analysis", "conclusion", "next_step"
        }:
            return None
        unit_id = str(item.get("unit_id", "")).strip().upper()
        if unit_id not in expected or unit_id in parsed:
            return None
        public_fields = {
            key: item.get(key, "")
            for key in ("analysis", "conclusion", "next_step")
        }
        checked = _parse_unit(
            json.dumps(public_fields, ensure_ascii=False),
            allowed_inputs[unit_id],
        )
        if checked is None:
            return None
        parsed[unit_id] = checked
    return parsed if set(parsed) == expected else None


def _context_for_unit(
    unit: AnswerUnit,
    *,
    question: str,
    facts_by_id,
    records_by_claim,
    issues_by_id,
    requirements_by_id,
    response_mode: str,
):
    record = records_by_claim.get(unit.claim_id)
    conditions = []
    if record is not None:
        conditions = [
            {
                "condition": match.condition.condition,
                "logic": match.condition.logic.value,
                "role": match.condition.role.value,
                "status": match.status.value,
            }
            for match in record.matches
            if match.status in {
                ConditionMatchStatus.UNKNOWN,
                ConditionMatchStatus.CONTRADICTED,
            }
            or match.condition.logic.value == "EXCEPTION"
        ]
    issue = issues_by_id.get(unit.issue_id)
    requirement = requirements_by_id.get(unit.requirement_id)
    return {
        "question": question,
        "issue": {
            "text": issue.display_text if issue else "",
            "issue_type": issue.issue_type if issue else "",
        },
        "requirement": {
            "target_kind": requirement.target_kind if requirement else "",
            "objective": requirement.objective if requirement else "",
        },
        "response_mode": response_mode,
        "proposition": unit.proposition,
        "application_status": unit.application_status.value,
        "facts": [
            {"fact_id": fact_id, "text": facts_by_id[fact_id].value}
            for fact_id in unit.fact_ids if fact_id in facts_by_id
        ],
        "conditions": conditions,
    }


class AnswerControlStage:
    """Audit theo Issue, chỉ sửa văn bản của unit bị đánh dấu REVISE."""

    def run(
        self,
        client: LocalLLMClient,
        *,
        question: str,
        facts: list[FactRecord],
        planning: PlanningResult,
        application: ConditionApplicationResult,
        draft: AnswerDraftResult,
        response_mode: str,
    ) -> AnswerControlResult:
        if not draft.units:
            return AnswerControlResult(draft, (), (), (), ())
        settings = get_active_settings()
        facts_by_id = {fact.fact_id: fact for fact in facts}
        records_by_claim = {
            record.verification.claim.claim_id: record
            for record in application.records
        }
        issues_by_id = {issue.issue_id: issue for issue in planning.issues}
        requirements_by_id = {
            requirement.requirement_id: requirement
            for issue in planning.issues for requirement in issue.requirements
        }
        contexts = {
            unit.unit_id: _context_for_unit(
                unit,
                question=question,
                facts_by_id=facts_by_id,
                records_by_claim=records_by_claim,
                issues_by_id=issues_by_id,
                requirements_by_id=requirements_by_id,
                response_mode=response_mode,
            )
            for unit in draft.units
        }
        decisions = {}
        audit_failed: list[str] = []
        by_issue: dict[str, list[AnswerUnit]] = {}
        for unit in draft.units:
            by_issue.setdefault(unit.issue_id, []).append(unit)
        for issue_units in by_issue.values():
            for offset in range(0, len(issue_units), 4):
                batch = issue_units[offset:offset + 4]
                ids = tuple(unit.unit_id for unit in batch)
                message = json.dumps({
                    "units": [
                        {
                            "unit_id": unit.unit_id,
                            **contexts[unit.unit_id],
                            "draft": {
                                "analysis": unit.analysis,
                                "conclusion": unit.conclusion,
                                "next_step": unit.next_step,
                            },
                        }
                        for unit in batch
                    ]
                }, ensure_ascii=False)
                payload = None
                for attempt in range(2):
                    try:
                        response = client.complete(
                            message,
                            model=settings.adjudicator_model,
                            system_prompt=ANSWER_UNIT_AUDIT_SPEC.text,
                            temperature=0.0,
                            max_tokens=max(450, 220 * len(batch)),
                            json_mode=True,
                            json_schema=answer_unit_audit_schema(list(ids)),
                        )
                        debug_dump(
                            f"PIPELINE :: ANSWER CONTROL :: AUDIT {','.join(ids)} :: INPUT",
                            json.loads(message),
                        )
                        debug_dump(
                            f"PIPELINE :: ANSWER CONTROL :: AUDIT {','.join(ids)} :: RAW",
                            response.text,
                        )
                        payload = _parse_audit(response.text, ids)
                    except Exception:
                        payload = None
                    if payload is not None:
                        break
                    if attempt == 0:
                        record_retry("Answer Unit audit contract", stage_name="Answer Control")
                if payload is None:
                    audit_failed.extend(ids)
                    decisions.update({unit_id: {"decision": "KEEP", "feedback": ""} for unit_id in ids})
                else:
                    decisions.update(payload)

        revision_inputs: dict[str, dict] = {}
        revision_units_by_issue: dict[str, list[AnswerUnit]] = {}
        for unit in draft.units:
            decision = decisions[unit.unit_id]
            if decision["decision"] != "REVISE":
                continue
            revision_inputs[unit.unit_id] = {
                **contexts[unit.unit_id],
                "draft": {
                    "analysis": unit.analysis,
                    "conclusion": unit.conclusion,
                    "next_step": unit.next_step,
                },
                "feedback": decision["feedback"],
                "reason_codes": list(decision.get("reason_codes", ())),
            }
            revision_units_by_issue.setdefault(unit.issue_id, []).append(unit)

        revised_text_by_id: dict[str, dict[str, str]] = {}
        for issue_units in revision_units_by_issue.values():
            for offset in range(0, len(issue_units), _REVISION_BATCH_SIZE):
                batch = issue_units[offset:offset + _REVISION_BATCH_SIZE]
                ids = tuple(unit.unit_id for unit in batch)
                # Question and response mode are shared once instead of being
                # repeated for every unit, which keeps the batch prompt compact.
                batch_payload = {
                    "question": question,
                        "response_mode": response_mode,
                    "units": [
                        {
                            "unit_id": unit.unit_id,
                            **{
                                key: value
                                for key, value in revision_inputs[unit.unit_id].items()
                                if key not in {"question", "response_mode"}
                            },
                        }
                        for unit in batch
                    ],
                }
                message = json.dumps(batch_payload, ensure_ascii=False)
                allowed_inputs = {
                    unit.unit_id: json.dumps(
                        revision_inputs[unit.unit_id], ensure_ascii=False
                    )
                    for unit in batch
                }
                batch_result = None
                try:
                    response = client.complete(
                        message,
                        model=settings.adjudicator_model,
                        system_prompt=ANSWER_UNIT_BATCH_REVISER_SPEC.text,
                        temperature=0.0,
                        max_tokens=max(800, 650 * len(batch)),
                        json_mode=True,
                        json_schema=answer_unit_revision_schema(list(ids)),
                    )
                    debug_dump(
                        f"PIPELINE :: ANSWER CONTROL :: REVISE BATCH {','.join(ids)} :: INPUT",
                        batch_payload,
                    )
                    debug_dump(
                        f"PIPELINE :: ANSWER CONTROL :: REVISE BATCH {','.join(ids)} :: RAW",
                        response.text,
                    )
                    batch_result = _parse_batch_revisions(
                        response.text,
                        ids,
                        allowed_inputs,
                    )
                except Exception:
                    batch_result = None
                if batch_result is not None:
                    revised_text_by_id.update(batch_result)
                    continue

                # A malformed batch must not lower answer quality. Fall back to
                # the previous provenance-locked one-unit contract only for this
                # failed batch.
                record_retry(
                    "Answer Unit batch revision contract",
                    stage_name="Answer Control",
                )
                for unit in batch:
                    revision_input = revision_inputs[unit.unit_id]
                    single_message = json.dumps(revision_input, ensure_ascii=False)
                    try:
                        response = client.complete(
                            single_message,
                            model=settings.adjudicator_model,
                            system_prompt=ANSWER_UNIT_REVISER_SPEC.text,
                            temperature=0.0,
                            max_tokens=800,
                            json_mode=True,
                            json_schema=ANSWER_UNIT_JSON_SCHEMA,
                        )
                        debug_dump(
                            f"PIPELINE :: ANSWER CONTROL :: REVISE FALLBACK {unit.unit_id} :: INPUT",
                            revision_input,
                        )
                        debug_dump(
                            f"PIPELINE :: ANSWER CONTROL :: REVISE FALLBACK {unit.unit_id} :: RAW",
                            response.text,
                        )
                        revised_text = _parse_unit(
                            response.text,
                            allowed_inputs[unit.unit_id],
                        )
                    except Exception:
                        revised_text = None
                    if revised_text is not None:
                        revised_text_by_id[unit.unit_id] = revised_text

        output_units: list[AnswerUnit] = []
        failures = list(draft.failures)
        kept: list[str] = []
        revised: list[str] = []
        dropped: list[str] = []
        for unit in draft.units:
            decision = decisions[unit.unit_id]
            if decision["decision"] == "KEEP":
                output_units.append(unit)
                kept.append(unit.unit_id)
                continue
            if decision["decision"] == "DROP":
                failures.append(AnswerUnitFailure(
                    claim_id=unit.claim_id,
                    reason_code="ANSWER_UNIT_AUDIT_DROPPED",
                ))
                dropped.append(unit.unit_id)
                continue
            revised_text = revised_text_by_id.get(unit.unit_id)
            if revised_text is None:
                failures.append(AnswerUnitFailure(
                    claim_id=unit.claim_id,
                    reason_code="ANSWER_UNIT_REVISION_FAILED",
                ))
                dropped.append(unit.unit_id)
                continue
            revised_unit = replace(
                unit,
                analysis=revised_text["analysis"],
                conclusion=revised_text["conclusion"],
                next_step=revised_text["next_step"],
            )
            # Ngoài ba trường văn bản, toàn bộ liên kết phải giữ nguyên.
            for field in (
                "unit_id", "issue_id", "requirement_id", "claim_id",
                "evidence_id", "application_status", "purpose", "fact_ids",
                "citation", "proposition",
            ):
                if getattr(revised_unit, field) != getattr(unit, field):
                    raise ValueError("Answer Reviser đã thay đổi liên kết bất biến.")
            output_units.append(revised_unit)
            revised.append(unit.unit_id)
        controlled = AnswerDraftResult(
            units=tuple(output_units),
            failures=tuple(failures),
        )
        result = AnswerControlResult(
            draft=controlled,
            kept_unit_ids=tuple(kept),
            revised_unit_ids=tuple(revised),
            dropped_unit_ids=tuple(dropped),
            audit_failed_unit_ids=tuple(audit_failed),
        )
        debug_dump("PIPELINE :: ANSWER CONTROL :: VALIDATED", asdict(result))
        return result


__all__ = ["AnswerControlResult", "AnswerControlStage", "answer_control_enabled"]
