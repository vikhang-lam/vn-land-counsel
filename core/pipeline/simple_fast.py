"""Low-latency SIMPLE path: structured retrieval, one writer, Python integrity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
from time import perf_counter

from core.answer_mode import is_procedure_question
from core.config import get_active_settings
from core.json_contracts import reject_duplicate_object_keys
from core.llm import LocalLLMClient

from .fast_grounding import (
    FastSource,
    GroundedFastUnit,
    evaluation_source_text,
    validate_grounded_units,
)
from .fast_retrieval import retrieve_fast_sources
from .prompts import (
    SIMPLE_GROUNDED_WRITER_SPEC,
    SIMPLE_SOURCE_GATE_SPEC,
    simple_grounded_writer_schema,
    simple_source_gate_schema,
)
from .retrieval_contract import RetrievalBudget


class SimpleCoverage(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NO_SUPPORT = "NO_SUPPORT"
    WRITER_FAILED = "WRITER_FAILED"


@dataclass(frozen=True, slots=True)
class SimpleFastBudget:
    retrieval: RetrievalBudget
    max_answer_units: int = 3
    max_repair_calls: int = 1

    @classmethod
    def baseline(cls) -> "SimpleFastBudget":
        return cls(retrieval=RetrievalBudget.baseline())

    def validate(self) -> None:
        self.retrieval.validate()
        if self.max_answer_units < 1 or self.max_repair_calls < 0:
            raise ValueError("Ngân sách SIMPLE không hợp lệ")


@dataclass(frozen=True, slots=True)
class SimpleWriterResult:
    coverage: SimpleCoverage
    missing_aspects: tuple[str, ...]
    direct_answer: GroundedFastUnit | None
    units: tuple[GroundedFastUnit, ...]
    failure_reason: str = ""
    raw_output_chars: int = 0
    raw_output_preview: str = ""


@dataclass(frozen=True, slots=True)
class SimpleFastResult:
    text: str
    coverage: SimpleCoverage
    source_count: int
    unit_count: int
    latency_seconds: float
    writer_calls: int
    writer_failure_reason: str
    writer_raw_output_chars: int
    writer_raw_output_preview: str
    source_texts: tuple[str, ...] = ()
    source_gate_calls: int = 0
    source_gate_failure_reason: str = ""


def _parse_payload(raw_output: str) -> dict | None:
    cleaned = re.sub(
        r"^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$",
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
    expected = {"coverage", "missing_aspects", "direct_answer", "units"}
    return payload if isinstance(payload, dict) and set(payload) == expected else None


def _parse_source_gate_payload(raw_output: str, source_count: int) -> dict | None:
    cleaned = re.sub(
        r"^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$",
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
    if not isinstance(payload, dict) or set(payload) != {"decisions"}:
        return None
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != source_count:
        return None
    normalized = []
    seen: set[int] = set()
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
            "source_index",
            "verdict",
            "reason",
        }:
            return None
        try:
            source_index = int(decision["source_index"])
        except (TypeError, ValueError):
            return None
        verdict = str(decision["verdict"]).upper()
        reason = re.sub(r"\s+", " ", str(decision["reason"])).strip()
        if (
            source_index < 0
            or source_index >= source_count
            or source_index in seen
            or verdict not in {"YES", "NO"}
            or not reason
        ):
            return None
        seen.add(source_index)
        normalized.append(
            {
                "source_index": source_index,
                "verdict": verdict,
                "reason": reason,
            }
        )
    if seen != set(range(source_count)):
        return None
    normalized.sort(key=lambda value: value["source_index"])
    return {"decisions": normalized}


def _failure_reason(raw_output: str) -> str:
    return "EMPTY_OUTPUT" if not str(raw_output or "").strip() else "INVALID_JSON"


def _reindex_sources(sources: tuple[FastSource, ...]) -> tuple[FastSource, ...]:
    return tuple(
        FastSource(index, source.citation, source.text)
        for index, source in enumerate(sources)
    )


def _deduplicate_units(
    direct: GroundedFastUnit | None,
    units: tuple[GroundedFastUnit, ...],
) -> tuple[GroundedFastUnit, ...]:
    if direct is None:
        return units
    return tuple(
        unit
        for unit in units
        if not (
            unit.text.casefold() == direct.text.casefold()
            or (
                unit.source_index == direct.source_index
                and unit.source_quote.casefold() == direct.source_quote.casefold()
            )
        )
    )


def _sentence(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[0].upper() + text[1:]


class SimpleFastStage:
    """Answer one legal goal with source selection and one bounded repair."""

    def __init__(
        self,
        budget: SimpleFastBudget | None = None,
    ) -> None:
        self.budget = budget or SimpleFastBudget.baseline()
        self.budget.validate()

    def _write(
        self,
        client: LocalLLMClient,
        question: str,
        sources: tuple[FastSource, ...],
        repair_from: SimpleWriterResult | None = None,
    ) -> SimpleWriterResult:
        message = json.dumps(
            {
                "question": question,
                "response_mode": (
                    "PROCEDURE"
                    if is_procedure_question(question)
                    else "EXPLANATION"
                ),
                "sources": [
                    {
                        "source_index": source.source_index,
                        "citation_hint": source.citation,
                        "text": source.text,
                    }
                    for source in sources
                ],
                "repair": (
                    {
                        "reason": repair_from.failure_reason,
                        "previous_output": repair_from.raw_output_preview,
                        "instruction": (
                            "Sửa đúng cấu trúc. Nếu một nguồn trực tiếp trả lời "
                            "câu hỏi, phải tạo direct_answer và chép source_quote "
                            "nguyên văn từ nguồn đó. direct_answer phải là câu "
                            "hoàn chỉnh dưới 500 ký tự, không dùng dấu ba chấm. "
                            "Không thêm nội dung ngoài nguồn."
                        ),
                    }
                    if repair_from is not None
                    else None
                ),
            },
            ensure_ascii=False,
        )
        settings = get_active_settings()
        response = client.complete(
            message,
            model=settings.adjudicator_model,
            system_prompt=SIMPLE_GROUNDED_WRITER_SPEC.text,
            temperature=0.0,
            max_tokens=900,
            json_mode=True,
            json_schema=simple_grounded_writer_schema(
                self.budget.max_answer_units,
                len(sources),
            ),
        )
        raw_output = str(response.text or "")
        payload = _parse_payload(raw_output)
        if payload is None:
            return SimpleWriterResult(
                coverage=SimpleCoverage.WRITER_FAILED,
                missing_aspects=(),
                direct_answer=None,
                units=(),
                failure_reason=_failure_reason(raw_output),
                raw_output_chars=len(raw_output),
                raw_output_preview=raw_output[:3000],
            )

        try:
            declared = SimpleCoverage(str(payload["coverage"]).upper())
        except ValueError:
            declared = SimpleCoverage.WRITER_FAILED
        missing = tuple(
            re.sub(r"\s+", " ", str(value or "")).strip()[:220]
            for value in payload.get("missing_aspects", [])
            if str(value or "").strip()
        )[:3]
        direct_payload = payload.get("direct_answer")
        try:
            direct_index = (
                int(direct_payload.get("source_index", -1))
                if isinstance(direct_payload, dict)
                else -1
            )
        except (TypeError, ValueError):
            direct_index = -1
        direct_units = validate_grounded_units(
            [direct_payload] if direct_index >= 0 else [],
            sources,
            allowed_numbers_text=question,
        )
        direct = direct_units[0] if direct_units else None
        units = _deduplicate_units(
            direct,
            validate_grounded_units(
                payload.get("units"),
                sources,
                allowed_numbers_text=question,
            ),
        )

        units_can_stand_alone = (
            direct is None
            and len(units) >= 2
            and not is_procedure_question(question)
        )
        if direct is None and not units_can_stand_alone:
            coverage = (
                SimpleCoverage.WRITER_FAILED
                if declared is SimpleCoverage.WRITER_FAILED
                else SimpleCoverage.NO_SUPPORT
            )
            missing = missing or ("Chưa có nguồn trực tiếp để trả lời.",)
        elif declared is SimpleCoverage.COMPLETE and not missing:
            coverage = SimpleCoverage.COMPLETE
        else:
            coverage = SimpleCoverage.PARTIAL
            missing = missing or ("Một phần yêu cầu chưa được nguồn làm rõ.",)
        return SimpleWriterResult(
            coverage=coverage,
            missing_aspects=missing,
            direct_answer=direct,
            units=units if direct is not None or units_can_stand_alone else (),
            failure_reason=(
                ""
                if direct
                else "MODEL_DECLARED_NO_DIRECT"
                if direct_index < 0
                else "DIRECT_GROUNDING_INVALID"
            ),
            raw_output_chars=len(raw_output),
            raw_output_preview=raw_output[:3000],
        )

    def _select_sources(
        self,
        client: LocalLLMClient,
        question: str,
        sources: tuple[FastSource, ...],
    ) -> tuple[tuple[FastSource, ...], str, int]:
        """Let the model rank legal relevance; Python only validates indices."""

        if len(sources) <= 1:
            return sources, "", 0
        settings = get_active_settings()
        message = json.dumps(
            {
                "question": question,
                "sources": [
                    {
                        "source_index": source.source_index,
                        "citation_hint": source.citation,
                        "text": source.text,
                    }
                    for source in sources
                ],
            },
            ensure_ascii=False,
        )
        try:
            response = client.complete(
                message,
                model=settings.adjudicator_model,
                system_prompt=SIMPLE_SOURCE_GATE_SPEC.text,
                temperature=0.0,
                max_tokens=600,
                json_mode=True,
                json_schema=simple_source_gate_schema(len(sources)),
            )
        except Exception as error:
            return sources, f"SOURCE_GATE_ERROR:{type(error).__name__}", 1
        payload = _parse_source_gate_payload(response.text, len(sources))
        if payload is None:
            return sources, "SOURCE_GATE_INVALID_JSON", 1
        selected_indices = [
            decision["source_index"]
            for decision in payload["decisions"]
            if decision["verdict"] == "YES"
        ]
        if not selected_indices:
            # A relevance model may be over-cautious. Keep the best retrieved
            # sources so the grounded writer gets an independent decision.
            return (
                _reindex_sources(sources[:3]),
                "SOURCE_GATE_ALL_REJECTED",
                1,
            )
        selected = tuple(sources[index] for index in selected_indices)
        return _reindex_sources(selected), "", 1

    @staticmethod
    def _render(question: str, result: SimpleWriterResult) -> str:
        if result.direct_answer is None and not result.units:
            detail = (
                " Phần còn thiếu: "
                + "; ".join(result.missing_aspects).rstrip(" .")
                + "."
                if result.missing_aspects
                else ""
            )
            return "Chưa tìm thấy căn cứ trực tiếp đủ để trả lời yêu cầu này." + detail

        direct = (
            f"{_sentence(result.direct_answer.text)} "
            f"({result.direct_answer.citation})"
            if result.direct_answer is not None
            else ""
        )
        detail_lines = [
            f"{_sentence(unit.text)} ({unit.citation})"
            for unit in result.units
        ]
        if direct:
            sections = ["**Trả lời trực tiếp**\n\n" + direct]
        else:
            sections = ["**Trả lời trực tiếp**\n\n" + "\n\n".join(detail_lines)]
            detail_lines = []
        if detail_lines:
            if is_procedure_question(question):
                body = "\n\n".join(
                    f"{index}. {line}"
                    for index, line in enumerate(detail_lines, 1)
                )
                sections.append("**Quy trình và lưu ý**\n\n" + body)
            else:
                sections.append("**Giải thích**\n\n" + "\n\n".join(detail_lines))
        if result.coverage is SimpleCoverage.PARTIAL and result.missing_aspects:
            sections.append(
                "**Giới hạn/Lưu ý**\n\n"
                + "; ".join(result.missing_aspects).rstrip(" .")
                + "."
            )
        citations = list(
            dict.fromkeys(
                [
                    *(
                        [result.direct_answer.citation]
                        if result.direct_answer is not None
                        else []
                    ),
                    *(unit.citation for unit in result.units),
                ]
            )
        )
        sections.append(
            "**Căn cứ pháp luật đã sử dụng**\n\n"
            + "\n".join(f"- {citation}" for citation in citations)
        )
        return "\n\n".join(sections)

    def run(self, client: LocalLLMClient, question: str) -> SimpleFastResult:
        started = perf_counter()
        query = str(question or "").strip()
        sources = retrieve_fast_sources(query, query, self.budget.retrieval)
        if not sources:
            written = SimpleWriterResult(
                coverage=SimpleCoverage.NO_SUPPORT,
                missing_aspects=("Không có nguồn truy xuất phù hợp.",),
                direct_answer=None,
                units=(),
                failure_reason="NO_RETRIEVAL_CONTEXT",
            )
            writer_calls = 0
            source_gate_calls = 0
            source_gate_failure_reason = ""
        else:
            sources, source_gate_failure_reason, source_gate_calls = self._select_sources(
                client, query, sources
            )
            written = self._write(client, query, sources)
            writer_calls = 1
            if (
                written.direct_answer is None
                and not written.units
                and self.budget.max_repair_calls > 0
            ):
                written = self._write(
                    client,
                    query,
                    sources,
                    repair_from=written,
                )
                writer_calls += 1
        return SimpleFastResult(
            text=self._render(query, written),
            coverage=written.coverage,
            source_count=len(sources),
            unit_count=len(written.units) + (1 if written.direct_answer else 0),
            latency_seconds=round(perf_counter() - started, 4),
            writer_calls=writer_calls,
            writer_failure_reason=written.failure_reason,
            writer_raw_output_chars=written.raw_output_chars,
            writer_raw_output_preview=written.raw_output_preview,
            source_texts=tuple(evaluation_source_text(source) for source in sources),
            source_gate_calls=source_gate_calls,
            source_gate_failure_reason=source_gate_failure_reason,
        )


__all__ = [
    "SimpleCoverage",
    "SimpleFastBudget",
    "SimpleFastResult",
    "SimpleFastStage",
    "SimpleWriterResult",
]
