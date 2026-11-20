"""Stage 2 - trích xuất và xác nhận dữ kiện của vụ việc."""

from __future__ import annotations

from dataclasses import dataclass

from core.case_facts import case_fact_extraction_text, validate_case_facts
from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.llm import LocalLLMClient
from core.telemetry import record_counter, record_retry

from .contracts import FactRecord
from .prompts import (
    FACT_EXTRACTION_RETRY_INSTRUCTION,
    FACT_EXTRACTOR_BASELINE_SPEC,
)


@dataclass(frozen=True, slots=True)
class FactExtractionResult:
    facts: list[FactRecord]
    raw_output: str
    retried: bool = False
    retry_output: str = ""
    planner_facts: tuple[FactRecord, ...] = ()

    def fact_payloads(self) -> list[dict[str, str]]:
        return [fact.to_dict() for fact in self.facts]

    def planner_fact_payloads(self) -> list[dict[str, str]]:
        """Planner sees the REQUEST record used by its SFT input contract."""

        records = self.planner_facts or tuple(self.facts)
        return [fact.to_dict() for fact in records]


def _material_fact_count(facts: list[dict[str, str]]) -> int:
    return sum(
        1
        for fact in facts
        if str(fact.get("category", "")).strip().upper() != "REQUEST"
    )


def _material_facts_only(facts: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the request in ``state.question``, not inside the Fact Ledger."""

    output = [
        dict(fact)
        for fact in facts
        if str(fact.get("category", "")).strip().upper() != "REQUEST"
    ]
    for index, fact in enumerate(output, 1):
        fact["fact_id"] = f"F{index:03d}"
    return output


class FactExtractorStage:
    """Tách dữ kiện bằng model; Python chỉ giữ quote có thật trong câu hỏi."""

    def run(self, client: LocalLLMClient, question: str) -> FactExtractionResult:
        query = str(question or "").strip()
        if not query:
            raise ValueError("Fact Extractor không nhận câu hỏi rỗng.")

        settings = get_active_settings()
        # The current adapter remains locked to its training prompt.  The clean
        # candidate prompt is registered separately and cannot be activated
        # until a new adapter records the matching hash.
        FACT_EXTRACTOR_BASELINE_SPEC.assert_sft_alignment()
        # Giữ giao diện đã vận hành cùng adapter: model chỉ tách phần tình
        # huống; validate_case_facts chép nguyên văn yêu cầu cuối thành REQUEST.
        # Python chỉ nhận diện ranh giới "Hỏi/Câu hỏi", không diễn giải pháp lý.
        extraction_text = case_fact_extraction_text(query)
        response = client.complete(
            extraction_text,
            model=settings.fact_model,
            system_prompt=FACT_EXTRACTOR_BASELINE_SPEC.text,
            temperature=0.0,
            max_tokens=1200,
            json_mode=True,
        )
        planner_facts = validate_case_facts(response.text, query)
        facts = _material_facts_only(planner_facts)
        debug_dump("PIPELINE :: FACT EXTRACTOR :: RAW", response.text)
        debug_dump("PIPELINE :: FACT EXTRACTOR :: VALIDATED", facts)
        debug_dump(
            "PIPELINE :: FACT EXTRACTOR :: PLANNER VIEW",
            planner_facts,
        )

        material_count = _material_fact_count(facts)
        retry_output = ""
        retried = False

        # Retry only when no material Fact survived structural/source-quote
        # validation. A valid one-Fact question must not pay for a second call.
        if material_count == 0:
            retried = True
            record_retry(
                "Pipeline Fact Extractor contract recovery",
                stage_name="Fact Extractor",
            )
            retry = client.complete(
                extraction_text
                + "\n\n"
                + FACT_EXTRACTION_RETRY_INSTRUCTION,
                model=settings.fact_model,
                system_prompt=FACT_EXTRACTOR_BASELINE_SPEC.text,
                temperature=0.0,
                max_tokens=1200,
                json_mode=True,
            )
            retry_output = retry.text
            repaired_planner_facts = validate_case_facts(retry.text, query)
            repaired = _material_facts_only(repaired_planner_facts)
            repaired_count = _material_fact_count(repaired)
            debug_dump("PIPELINE :: FACT EXTRACTOR :: RETRY RAW", retry.text)
            debug_dump("PIPELINE :: FACT EXTRACTOR :: RETRY VALIDATED", repaired)
            if repaired_count > material_count:
                facts = repaired
                planner_facts = repaired_planner_facts
                record_counter("pipeline_fact_recovery_improved")
            else:
                record_counter("pipeline_fact_recovery_no_improvement")

        return FactExtractionResult(
            facts=[FactRecord.from_mapping(fact) for fact in facts],
            raw_output=response.text,
            retried=retried,
            retry_output=retry_output,
            planner_facts=tuple(
                FactRecord.from_mapping(fact) for fact in planner_facts
            ),
        )


__all__ = ["FactExtractionResult", "FactExtractorStage"]
