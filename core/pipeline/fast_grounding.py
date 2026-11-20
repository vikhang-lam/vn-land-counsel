"""Shared structural checks for low-latency grounded answer paths."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from core.text_normalization import fold_vietnamese


_INTERNAL_ID_RE = re.compile(r"\b(?:I|R|RC|E|C|K|KC|AF|S)\d{3,}(?:_\d{2})?\b")
_LOCATOR_RE = re.compile(
    r"\b(?:Điều\s+\d+|Khoản\s+\d+|Điểm\s+[A-Za-zĐđ])\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)*\b")
_NUMBER_UNITS = {
    "khong": 0,
    "mot": 1,
    "mots": 1,
    "hai": 2,
    "ba": 3,
    "bon": 4,
    "tu": 4,
    "nam": 5,
    "lam": 5,
    "sau": 6,
    "bay": 7,
    "tam": 8,
    "chin": 9,
}


def _number_values_from_words(text: str) -> set[str]:
    folded = fold_vietnamese(text)
    values: set[str] = set()
    tokens = re.findall(r"[a-z]+", folded)
    for index, token in enumerate(tokens):
        if token == "muoi":
            unit = _NUMBER_UNITS.get(tokens[index + 1], 0) if index + 1 < len(tokens) else 0
            values.add(str(10 + unit))
        if index + 1 < len(tokens) and tokens[index + 1] == "muoi":
            tens = _NUMBER_UNITS.get(token)
            if tens is not None and tens >= 2:
                unit = (
                    _NUMBER_UNITS.get(tokens[index + 2], 0)
                    if index + 2 < len(tokens)
                    else 0
                )
                values.add(str(tens * 10 + unit))
    return values


def _legal_locators(text: str) -> set[str]:
    return {
        re.sub(r"\s+", " ", match.group(0)).strip().casefold()
        for match in _LOCATOR_RE.finditer(str(text or ""))
    }


@dataclass(frozen=True, slots=True)
class FastSource:
    source_index: int
    citation: str
    text: str


@dataclass(frozen=True, slots=True)
class GroundedFastUnit:
    source_index: int
    citation: str
    source_quote: str
    text: str


def evaluation_source_text(source: FastSource) -> str:
    """Represent exactly the legal identity and text visible to the writer."""

    return f"[NGUỒN: {source.citation}]\n{source.text}"


def source_quote_span(source: str, quote: str) -> tuple[int, int] | None:
    quote_text = str(quote or "").strip()
    quote_text = re.sub(r"\\r\\n|\\n|\\r|\\t", " ", quote_text)
    quote_text = re.sub(
        r"(?:\.{3}|…)+$",
        "",
        quote_text,
    ).rstrip()
    tokens = re.split(r"\s+", quote_text)
    if not tokens:
        return None
    match = re.search(
        r"\s+".join(re.escape(token) for token in tokens if token),
        str(source or ""),
        flags=re.IGNORECASE,
    )
    return (match.start(), match.end()) if match else None


def validate_grounded_units(
    raw_units: Any,
    sources: tuple[FastSource, ...],
    *,
    allowed_numbers_text: str,
) -> tuple[GroundedFastUnit, ...]:
    if not isinstance(raw_units, list):
        return ()
    source_by_index = {source.source_index: source for source in sources}
    allowed_numbers = set(_NUMBER_RE.findall(str(allowed_numbers_text or "")))
    output: list[GroundedFastUnit] = []
    seen: set[tuple[int, str]] = set()
    for item in raw_units:
        if not isinstance(item, dict) or set(item) != {
            "source_index",
            "source_quote",
            "text",
        }:
            continue
        try:
            source_index = int(item.get("source_index"))
        except (TypeError, ValueError):
            continue
        source = source_by_index.get(source_index)
        quote = str(item.get("source_quote", "")).strip()
        public_text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
        public_text = re.sub(r"(?:\.{3}|…)+$", ".", public_text).rstrip()
        if source is None or not quote or not public_text:
            continue
        if "…" in public_text or "..." in public_text:
            continue
        span = source_quote_span(source.text, quote)
        if span is None:
            continue
        if _INTERNAL_ID_RE.search(public_text):
            continue
        exact_quote = source.text[span[0] : span[1]]
        allowed_locators = (
            _legal_locators(exact_quote)
            | _legal_locators(source.citation)
            | _legal_locators(allowed_numbers_text)
        )
        if _legal_locators(public_text) - allowed_locators:
            continue
        unit_allowed_numbers = (
            allowed_numbers
            | set(_NUMBER_RE.findall(exact_quote))
            | set(_NUMBER_RE.findall(source.citation))
            | _number_values_from_words(exact_quote)
        )
        if set(_NUMBER_RE.findall(public_text)) - unit_allowed_numbers:
            continue
        key = (source_index, public_text.casefold())
        if key in seen:
            continue
        seen.add(key)
        output.append(
            GroundedFastUnit(
                source_index=source_index,
                citation=source.citation,
                source_quote=exact_quote,
                text=public_text,
            )
        )
    return tuple(output)


__all__ = [
    "FastSource",
    "GroundedFastUnit",
    "evaluation_source_text",
    "source_quote_span",
    "validate_grounded_units",
]
