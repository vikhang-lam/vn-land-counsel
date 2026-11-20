"""Stage 8 - extract explicit ALL/ANY/EXCEPTION condition structure."""

from __future__ import annotations

from hashlib import sha256
from dataclasses import asdict, dataclass
import json
import re
from typing import Any

from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.evidence import strip_retrieval_metadata
from core.json_contracts import reject_duplicate_object_keys
from core.llm import LocalLLMClient
from core.telemetry import record_retry

from .condition_contract import (
    ConditionExtractionFailure,
    ConditionExtractionResult,
    ConditionLogic,
    ConditionRecord,
    ConditionRole,
)
from .prompts import (
    CONDITION_EXTRACTOR_JSON_SCHEMA,
    CONDITION_EXTRACTOR_RETRY_INSTRUCTION,
    CONDITION_EXTRACTOR_SPEC,
)
from .evidence_contract import EvidenceSelectionResult
from .verification_contract import ClaimVerificationResult


@dataclass(frozen=True, slots=True)
class ConditionExtractionBudget:
    safety_max_conditions_per_claim: int

    @classmethod
    def baseline(cls) -> "ConditionExtractionBudget":
        """Runaway protection only; not a semantic completeness target."""

        return cls(safety_max_conditions_per_claim=24)

    def validate(self) -> None:
        if self.safety_max_conditions_per_claim < 1:
            raise ValueError("safety_max_conditions_per_claim phải dương")


def _source_span(source: str, quote: str) -> tuple[int, int] | None:
    tokens = re.split(r"\s+", str(quote or "").strip())
    if not tokens:
        return None
    match = re.search(
        r"\s+".join(re.escape(token) for token in tokens if token),
        source,
        flags=re.IGNORECASE,
    )
    return (match.start(), match.end()) if match else None


def _load_output(raw: str) -> dict[str, Any] | None:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(raw or "").strip(),
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
        "all_of",
        "any_of",
        "exceptions",
    }:
        return None
    return payload


def _validated_items(
    payload: dict[str, Any],
    source: str,
    safety_limit: int,
) -> list[tuple[ConditionLogic, str, dict[str, Any], int, int]] | None:
    flattened: list[tuple[ConditionLogic, str, dict[str, Any]]] = []
    all_items = payload.get("all_of")
    any_groups = payload.get("any_of")
    exceptions = payload.get("exceptions")
    if not isinstance(all_items, list) or not isinstance(any_groups, list) or not isinstance(exceptions, list):
        return None
    flattened.extend((ConditionLogic.ALL, "ALL", item) for item in all_items)
    for group_index, group in enumerate(any_groups, 1):
        if not isinstance(group, dict) or set(group) != {"alternatives"}:
            return None
        alternatives = group.get("alternatives")
        if not isinstance(alternatives, list) or len(alternatives) < 2:
            return None
        flattened.extend(
            (ConditionLogic.ANY, f"ANY_{group_index}", item)
            for item in alternatives
        )
    flattened.extend(
        (ConditionLogic.EXCEPTION, "EXCEPTION", item) for item in exceptions
    )
    if len(flattened) > safety_limit:
        return None

    output: list[tuple[ConditionLogic, str, dict[str, Any], int, int]] = []
    for logic, local_group, item in flattened:
        if not isinstance(item, dict) or set(item) != {
            "condition",
            "source_quote",
            "role",
        }:
            return None
        condition = re.sub(r"\s+", " ", str(item.get("condition", ""))).strip()
        quote = str(item.get("source_quote", "")).strip()
        try:
            role = ConditionRole(str(item.get("role", "")).strip().upper())
        except ValueError:
            return None
        span = _source_span(source, quote)
        if not condition or not quote or span is None:
            return None
        output.append(
            (
                logic,
                local_group,
                {"condition": condition, "source_quote": quote, "role": role},
                span[0],
                span[1],
            )
        )
    return output


class ConditionExtractorStage:
    def __init__(self, budget: ConditionExtractionBudget | None = None) -> None:
        self.budget = budget or ConditionExtractionBudget.baseline()
        self.budget.validate()

    def run(
        self,
        client: LocalLLMClient,
        verification: ClaimVerificationResult,
        evidence: EvidenceSelectionResult,
    ) -> ConditionExtractionResult:
        settings = get_active_settings()
        evidence_by_id = {
            item.evidence_id: item for item in evidence.selected_evidence
        }
        conditions: list[ConditionRecord] = []
        failures: list[ConditionExtractionFailure] = []
        next_condition_id = 1
        next_group_id = 1
        for verified in verification.usable_records:
            claim = verified.claim
            selected_source = evidence_by_id.get(claim.evidence_id)
            if selected_source is None:
                failures.append(
                    ConditionExtractionFailure(
                        claim_id=claim.claim_id,
                        reason_code="UNKNOWN_EVIDENCE_ID",
                    )
                )
                continue
            source = strip_retrieval_metadata(
                selected_source.context.raw_text
            )
            message = json.dumps(
                {
                    "proposition": claim.proposition,
                    "source": source,
                },
                ensure_ascii=False,
            )
            response = client.complete(
                message,
                model=settings.adjudicator_model,
                system_prompt=CONDITION_EXTRACTOR_SPEC.text,
                temperature=0.0,
                max_tokens=1600,
                json_mode=True,
                json_schema=CONDITION_EXTRACTOR_JSON_SCHEMA,
            )
            debug_dump(
                f"PIPELINE :: CONDITION EXTRACTOR :: {claim.claim_id} :: INPUT",
                json.loads(message),
            )
            debug_dump(
                f"PIPELINE :: CONDITION EXTRACTOR :: {claim.claim_id} :: RAW",
                response.text,
            )
            payload = _load_output(response.text)
            extracted = (
                _validated_items(
                    payload,
                    source,
                    self.budget.safety_max_conditions_per_claim,
                )
                if payload
                else None
            )
            if extracted is None:
                record_retry(
                    "Condition Extractor structured logic contract",
                    stage_name="Condition Extractor",
                )
                retry = client.complete(
                    message
                    + "\n\nVALIDATION_ERRORS: CONDITION_STRUCTURE_OR_SOURCE_QUOTE_INVALID\n"
                    + CONDITION_EXTRACTOR_RETRY_INSTRUCTION,
                    model=settings.adjudicator_model,
                    system_prompt=CONDITION_EXTRACTOR_SPEC.text,
                    temperature=0.0,
                    max_tokens=1600,
                    json_mode=True,
                    json_schema=CONDITION_EXTRACTOR_JSON_SCHEMA,
                )
                debug_dump(
                    f"PIPELINE :: CONDITION EXTRACTOR :: {claim.claim_id} :: RETRY RAW",
                    retry.text,
                )
                payload = _load_output(retry.text)
                extracted = (
                    _validated_items(
                        payload,
                        source,
                        self.budget.safety_max_conditions_per_claim,
                    )
                    if payload
                    else None
                )
            if extracted is None:
                failures.append(
                    ConditionExtractionFailure(
                        claim_id=claim.claim_id,
                        reason_code="CONDITION_EXTRACTION_CONTRACT_FAILED",
                    )
                )
                continue

            group_ids: dict[tuple[ConditionLogic, str], str] = {}
            for logic, local_group, item, start, end in extracted:
                group_key = (logic, local_group)
                if group_key not in group_ids:
                    group_ids[group_key] = f"KC{next_group_id:03d}"
                    next_group_id += 1
                exact_span = source[start:end]
                conditions.append(
                    ConditionRecord(
                        condition_id=f"K{next_condition_id:03d}",
                        claim_id=claim.claim_id,
                        group_id=group_ids[group_key],
                        logic=logic,
                        role=item["role"],
                        condition=item["condition"],
                        source_quote=exact_span,
                        source_span_start=start,
                        source_span_end=end,
                        source_span_sha256=sha256(
                            exact_span.encode("utf-8")
                        ).hexdigest(),
                    )
                )
                next_condition_id += 1

        result = ConditionExtractionResult(
            conditions=tuple(conditions),
            failures=tuple(failures),
        )
        debug_dump("PIPELINE :: CONDITION EXTRACTOR :: VALIDATED", asdict(result))
        return result


__all__ = ["ConditionExtractionBudget", "ConditionExtractorStage"]
