"""Stage 6 - extract source-bound claims; Python owns every identifier."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re

from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.evidence import strip_retrieval_metadata
from core.json_contracts import reject_duplicate_object_keys
from core.llm import LocalLLMClient
from core.telemetry import record_retry

from .claim_contract import (
    ClaimExtractionFailure,
    ClaimExtractionResult,
    ClaimRecord,
)
from .contracts import PlanningResult
from .evidence_contract import EvidenceSelectionResult
from .prompts import (
    CLAIM_EXTRACTOR_RETRY_INSTRUCTION,
    CLAIM_EXTRACTOR_SPEC,
    claim_extractor_schema,
)


@dataclass(frozen=True, slots=True)
class ClaimExtractionBudget:
    max_claims_per_source: int

    @classmethod
    def baseline(cls) -> "ClaimExtractionBudget":
        return cls(max_claims_per_source=3)

    def validate(self) -> None:
        if self.max_claims_per_source < 1:
            raise ValueError("max_claims_per_source phải dương")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" .;:").casefold()


def _source_span(source: str, quote: str) -> tuple[int, int] | None:
    """Locate a quote while tolerating only whitespace-layout differences."""

    tokens = re.split(r"\s+", str(quote or "").strip())
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(token) for token in tokens if token)
    match = re.search(pattern, source, flags=re.IGNORECASE)
    return (match.start(), match.end()) if match else None


def _parse_claims(
    raw_output: str,
    source: str,
    max_claims: int,
) -> list[tuple[str, str, int, int]] | None:
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
    if not isinstance(payload, dict) or set(payload) != {"claims"}:
        return None
    items = payload.get("claims")
    if not isinstance(items, list) or len(items) > max_claims:
        return None
    output: list[tuple[str, str, int, int]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"proposition", "source_quote"}:
            return None
        proposition = re.sub(
            r"\s+", " ", str(item.get("proposition", ""))
        ).strip(" .;:")
        source_quote = str(item.get("source_quote", "")).strip()
        span = _source_span(source, source_quote)
        key = _normalize(proposition)
        if not proposition or not source_quote or span is None or not key:
            return None
        if key in seen:
            continue
        seen.add(key)
        output.append((proposition, source_quote, span[0], span[1]))
    return output


class ClaimExtractorStage:
    def __init__(self, budget: ClaimExtractionBudget | None = None) -> None:
        self.budget = budget or ClaimExtractionBudget.baseline()
        self.budget.validate()

    def run(
        self,
        client: LocalLLMClient,
        planning: PlanningResult,
        evidence: EvidenceSelectionResult,
    ) -> ClaimExtractionResult:
        settings = get_active_settings()
        requirement_by_id = {
            requirement.requirement_id: (issue, requirement)
            for issue in planning.issues
            for requirement in issue.requirements
        }
        claims: list[ClaimRecord] = []
        failures: list[ClaimExtractionFailure] = []
        next_claim_id = 1
        seen_per_requirement: dict[str, set[str]] = {}

        for selection in evidence.requirements:
            issue_requirement = requirement_by_id.get(selection.requirement_id)
            if issue_requirement is None:
                failures.append(
                    ClaimExtractionFailure(
                        issue_id=selection.issue_id,
                        requirement_id=selection.requirement_id,
                        evidence_id="",
                        context_id="",
                        reason_code="UNKNOWN_REQUIREMENT_ID",
                    )
                )
                continue
            issue, requirement = issue_requirement
            requirement_seen = seen_per_requirement.setdefault(
                requirement.requirement_id, set()
            )
            for selected_source in selection.selected_evidence:
                context = selected_source.context
                source_text = strip_retrieval_metadata(context.raw_text)
                message = json.dumps(
                    {
                        "issue": issue.display_text,
                        "requirement": {
                            "target_kind": requirement.target_kind,
                            "objective": requirement.objective,
                            "query": requirement.query,
                        },
                        "source": {
                            "citation": context.citation,
                            "text": source_text,
                        },
                    },
                    ensure_ascii=False,
                )
                schema = claim_extractor_schema(
                    self.budget.max_claims_per_source
                )
                response = client.complete(
                    message,
                    model=settings.evidence_model,
                    system_prompt=CLAIM_EXTRACTOR_SPEC.text,
                    temperature=0.0,
                    max_tokens=1000,
                    json_mode=True,
                    json_schema=schema,
                )
                debug_dump(
                    f"PIPELINE :: CLAIM EXTRACTOR :: {selected_source.evidence_id} :: INPUT",
                    json.loads(message),
                )
                debug_dump(
                    f"PIPELINE :: CLAIM EXTRACTOR :: {selected_source.evidence_id} :: RAW",
                    response.text,
                )
                extracted = _parse_claims(
                    response.text,
                    source_text,
                    self.budget.max_claims_per_source,
                )
                if extracted is None:
                    record_retry(
                        "Claim Extractor output contract",
                        stage_name="Claim Extractor",
                    )
                    retry = client.complete(
                        message
                        + "\n\nVALIDATION_ERRORS: SOURCE_QUOTE_OR_SCHEMA_INVALID\n"
                        + CLAIM_EXTRACTOR_RETRY_INSTRUCTION,
                        model=settings.evidence_model,
                        system_prompt=CLAIM_EXTRACTOR_SPEC.text,
                        temperature=0.0,
                        max_tokens=1000,
                        json_mode=True,
                        json_schema=schema,
                    )
                    debug_dump(
                        f"PIPELINE :: CLAIM EXTRACTOR :: {selected_source.evidence_id} :: RETRY RAW",
                        retry.text,
                    )
                    extracted = _parse_claims(
                        retry.text,
                        source_text,
                        self.budget.max_claims_per_source,
                    )
                if extracted is None:
                    failures.append(
                        ClaimExtractionFailure(
                            issue_id=issue.issue_id,
                            requirement_id=requirement.requirement_id,
                            evidence_id=selected_source.evidence_id,
                            context_id=context.context_id,
                            reason_code="CLAIM_EXTRACTION_CONTRACT_FAILED",
                        )
                    )
                    continue

                for proposition, quote, start, end in extracted:
                    normalized = _normalize(proposition)
                    if normalized in requirement_seen:
                        continue
                    requirement_seen.add(normalized)
                    exact_span = source_text[start:end]
                    claims.append(
                        ClaimRecord(
                            claim_id=f"C{next_claim_id:03d}",
                            issue_id=issue.issue_id,
                            requirement_id=requirement.requirement_id,
                            evidence_id=selected_source.evidence_id,
                            context_id=context.context_id,
                            citation=context.citation,
                            proposition=proposition,
                            source_quote=exact_span,
                            source_span_start=start,
                            source_span_end=end,
                            source_span_sha256=sha256(
                                exact_span.encode("utf-8")
                            ).hexdigest(),
                        )
                    )
                    next_claim_id += 1

        result = ClaimExtractionResult(
            claims=tuple(claims),
            failures=tuple(failures),
        )
        debug_dump("PIPELINE :: CLAIM EXTRACTOR :: VALIDATED", asdict(result))
        return result


__all__ = ["ClaimExtractionBudget", "ClaimExtractorStage"]
