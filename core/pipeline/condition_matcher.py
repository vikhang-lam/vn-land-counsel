"""Stage 9 - match conditions to Facts and resolve application in Python."""

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

from .condition_contract import (
    ApplicationStatus,
    ClaimApplicationRecord,
    ConditionApplicationResult,
    ConditionExtractionResult,
    ConditionMatchRecord,
    ConditionMatchStatus,
    ConditionRecord,
    resolve_application_status,
)
from .contracts import FactRecord
from .prompts import (
    CONDITION_MATCHER_RETRY_INSTRUCTION,
    CONDITION_MATCHER_SPEC,
    condition_matcher_schema,
)
from .verification_contract import ClaimVerificationResult


def _parse_matches(
    raw_output: str,
    conditions: tuple[ConditionRecord, ...],
    valid_fact_ids: set[str],
) -> tuple[ConditionMatchRecord, ...] | None:
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
    if not isinstance(payload, dict) or set(payload) != {"matches"}:
        return None
    items = payload.get("matches")
    if not isinstance(items, list):
        return None
    by_id = {condition.condition_id: condition for condition in conditions}
    output: list[ConditionMatchRecord] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "condition_id",
            "status",
            "fact_ids",
            "reason",
        }:
            return None
        condition_id = str(item.get("condition_id", "")).strip().upper()
        try:
            status = ConditionMatchStatus(
                str(item.get("status", "")).strip().upper()
            )
        except ValueError:
            return None
        raw_fact_ids = item.get("fact_ids")
        if not isinstance(raw_fact_ids, list):
            return None
        fact_ids = tuple(
            dict.fromkeys(
                str(value).strip().upper()
                for value in raw_fact_ids
                if str(value).strip()
            )
        )
        reason = re.sub(r"\s+", " ", str(item.get("reason", ""))).strip()[:300]
        if (
            condition_id not in by_id
            or condition_id in seen
            or not reason
            or any(fact_id not in valid_fact_ids for fact_id in fact_ids)
        ):
            return None
        if status is ConditionMatchStatus.UNKNOWN and fact_ids:
            return None
        if status is not ConditionMatchStatus.UNKNOWN and not fact_ids:
            return None
        seen.add(condition_id)
        output.append(
            ConditionMatchRecord(
                condition=by_id[condition_id],
                status=status,
                fact_ids=fact_ids,
                reason=reason,
            )
        )
    if seen != set(by_id):
        return None
    order = {
        condition.condition_id: index
        for index, condition in enumerate(conditions)
    }
    output.sort(key=lambda match: order[match.condition.condition_id])
    return tuple(output)


def _failed_application(verification) -> ClaimApplicationRecord:
    return ClaimApplicationRecord(
        verification=verification,
        status=ApplicationStatus.MATCHING_FAILED,
        matches=(),
        supporting_fact_ids=(),
        contradicting_fact_ids=(),
        exception_fact_ids=(),
        contradicted_condition_ids=(),
        unknown_condition_ids=(),
    )


class ConditionMatcherStage:
    def run(
        self,
        client: LocalLLMClient,
        *,
        facts: list[FactRecord],
        verification: ClaimVerificationResult,
        extraction: ConditionExtractionResult,
    ) -> ConditionApplicationResult:
        settings = get_active_settings()
        fact_payload = [
            {
                "fact_id": fact.fact_id,
                "category": fact.category,
                "text": fact.value,
            }
            for fact in facts
            if fact.category != "REQUEST"
        ]
        valid_fact_ids = {item["fact_id"] for item in fact_payload}
        failed_claim_ids = {failure.claim_id for failure in extraction.failures}
        applications: list[ClaimApplicationRecord] = []

        for verified in verification.usable_records:
            claim_id = verified.claim.claim_id
            if claim_id in failed_claim_ids:
                applications.append(_failed_application(verified))
                continue
            conditions = extraction.for_claim(claim_id)
            if not conditions:
                applications.append(
                    resolve_application_status(verified, (), ())
                )
                continue

            message = json.dumps(
                {
                    "claim": {
                        "claim_id": claim_id,
                        "proposition": verified.claim.proposition,
                    },
                    "conditions": [
                        {
                            "condition_id": condition.condition_id,
                            "group_id": condition.group_id,
                            "logic": condition.logic.value,
                            "role": condition.role.value,
                            "condition": condition.condition,
                        }
                        for condition in conditions
                    ],
                    "facts": fact_payload,
                },
                ensure_ascii=False,
            )
            schema = condition_matcher_schema(len(conditions))
            response = client.complete(
                message,
                model=settings.adjudicator_model,
                system_prompt=CONDITION_MATCHER_SPEC.text,
                temperature=0.0,
                max_tokens=max(600, 180 * len(conditions)),
                json_mode=True,
                json_schema=schema,
            )
            debug_dump(
                f"PIPELINE :: CONDITION MATCHER :: {claim_id} :: INPUT",
                json.loads(message),
            )
            debug_dump(
                f"PIPELINE :: CONDITION MATCHER :: {claim_id} :: RAW",
                response.text,
            )
            matches = _parse_matches(
                response.text,
                conditions,
                valid_fact_ids,
            )
            if matches is None:
                record_retry(
                    "Condition Matcher output contract",
                    stage_name="Condition Matcher",
                )
                retry = client.complete(
                    message
                    + "\n\nVALIDATION_ERRORS: ONE_MATCH_PER_CONDITION_REQUIRED\n"
                    + CONDITION_MATCHER_RETRY_INSTRUCTION,
                    model=settings.adjudicator_model,
                    system_prompt=CONDITION_MATCHER_SPEC.text,
                    temperature=0.0,
                    max_tokens=max(600, 180 * len(conditions)),
                    json_mode=True,
                    json_schema=schema,
                )
                debug_dump(
                    f"PIPELINE :: CONDITION MATCHER :: {claim_id} :: RETRY RAW",
                    retry.text,
                )
                matches = _parse_matches(
                    retry.text,
                    conditions,
                    valid_fact_ids,
                )
            applications.append(
                resolve_application_status(
                    verified,
                    conditions,
                    matches,
                )
            )

        result = ConditionApplicationResult(records=tuple(applications))
        debug_dump("PIPELINE :: CONDITION MATCHER :: VALIDATED", asdict(result))
        return result


__all__ = ["ConditionMatcherStage"]
