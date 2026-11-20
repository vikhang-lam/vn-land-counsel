"""Grounded one-pass summary for exact Article lookup results."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from time import perf_counter

from core.config import get_active_settings
from core.json_contracts import reject_duplicate_object_keys
from core.llm import LocalLLMClient

from .article_lookup import ArticleLookupResult
from .fast_grounding import FastSource, GroundedFastUnit, validate_grounded_units
from .prompts import ARTICLE_SUMMARIZER_SPEC, article_summarizer_schema


@dataclass(frozen=True, slots=True)
class ArticleSummaryBudget:
    max_source_chars_per_call: int
    max_units_per_call: int
    max_repair_calls: int = 1

    @classmethod
    def baseline(cls) -> "ArticleSummaryBudget":
        # Keep one Article batch below a 12.8k-token local context even for
        # Vietnamese legal text, which can tokenize more densely than English.
        return cls(max_source_chars_per_call=20_000, max_units_per_call=6)

    def validate(self) -> None:
        if (
            self.max_source_chars_per_call < 1
            or self.max_units_per_call < 1
            or self.max_repair_calls < 0
        ):
            raise ValueError("Article summary budget phải dương")


@dataclass(frozen=True, slots=True)
class ArticleAnswerResult:
    text: str
    article: str
    source_count: int
    summary_calls: int
    grounded_unit_count: int
    found: bool
    latency_seconds: float


def _payload(raw_output: str) -> dict | None:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(raw_output or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        value = json.loads(
            cleaned,
            object_pairs_hook=reject_duplicate_object_keys,
        )
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) and set(value) == {"units"} else None


def _batches(lookup: ArticleLookupResult, max_chars: int):
    current = []
    current_chars = 0
    for source in lookup.sources:
        source_chars = len(source.text)
        if current and current_chars + source_chars > max_chars:
            yield tuple(current)
            current = []
            current_chars = 0
        current.append(source)
        current_chars += source_chars
    if current:
        yield tuple(current)


class ArticleAnswerStage:
    def __init__(self, budget: ArticleSummaryBudget | None = None) -> None:
        self.budget = budget or ArticleSummaryBudget.baseline()
        self.budget.validate()

    def run(
        self,
        client: LocalLLMClient,
        question: str,
        lookup: ArticleLookupResult,
    ) -> ArticleAnswerResult:
        started = perf_counter()
        if not lookup.found:
            return ArticleAnswerResult(
                text=lookup.message,
                article=lookup.article,
                source_count=0,
                summary_calls=0,
                grounded_unit_count=0,
                found=False,
                latency_seconds=round(perf_counter() - started, 4),
            )
        settings = get_active_settings()
        all_units: list[GroundedFastUnit] = []
        summary_calls = 0
        for batch in _batches(lookup, self.budget.max_source_chars_per_call):
            sources = tuple(
                FastSource(
                    source_index=index,
                    citation=source.citation,
                    text=source.text,
                )
                for index, source in enumerate(batch)
            )
            base_payload = {
                "question": question,
                "article": lookup.article,
                "sources": [
                    {
                        "source_index": source.source_index,
                        "citation_hint": source.citation,
                        "text": source.text,
                    }
                    for source in sources
                ],
            }
            units: tuple[GroundedFastUnit, ...] = ()
            previous_output = ""
            for attempt in range(self.budget.max_repair_calls + 1):
                request_payload = dict(base_payload)
                if attempt:
                    request_payload["repair"] = {
                        "reason": "Không có ý nào vượt qua kiểm tra đoạn trích.",
                        "previous_output": previous_output[:3000],
                    }
                message = json.dumps(request_payload, ensure_ascii=False)
                response = client.complete(
                    message,
                    model=settings.adjudicator_model,
                    system_prompt=ARTICLE_SUMMARIZER_SPEC.text,
                    temperature=0.0,
                    max_tokens=650,
                    json_mode=True,
                    json_schema=article_summarizer_schema(
                        self.budget.max_units_per_call,
                        len(sources),
                    ),
                )
                summary_calls += 1
                previous_output = str(response.text or "")
                payload = _payload(previous_output)
                units = validate_grounded_units(
                    payload.get("units", []) if payload else [],
                    sources,
                    allowed_numbers_text=question,
                )
                if units:
                    break
            all_units.extend(units)

        unique_units: list[GroundedFastUnit] = []
        seen: set[str] = set()
        for unit in all_units:
            key = unit.text.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique_units.append(unit)
        if not unique_units:
            return ArticleAnswerResult(
                text="Không thể tạo bản tóm tắt có căn cứ cho Điều được yêu cầu.",
                article=lookup.article,
                source_count=lookup.chunk_count,
                summary_calls=summary_calls,
                grounded_unit_count=0,
                found=True,
                latency_seconds=round(perf_counter() - started, 4),
            )
        body = "\n\n".join(
            f"{unit.text} ({unit.citation})" for unit in unique_units
        )
        return ArticleAnswerResult(
            text=f"**Nội dung chính của Điều {lookup.article}**\n\n{body}",
            article=lookup.article,
            source_count=lookup.chunk_count,
            summary_calls=summary_calls,
            grounded_unit_count=len(unique_units),
            found=True,
            latency_seconds=round(perf_counter() - started, 4),
        )


__all__ = ["ArticleAnswerResult", "ArticleAnswerStage", "ArticleSummaryBudget"]
