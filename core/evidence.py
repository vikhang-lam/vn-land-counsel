"""Metadata helpers shared by retrieval and the clean pipeline.

The legal interpretation stages live in ``core.pipeline``.  This module only
parses transport metadata that retrieval attaches to source text and formats a
source label for the final answer.
"""

from __future__ import annotations

import re


_RERANK_SCORE_LINE_RE = re.compile(
    r"(?mi)^[ \t]*\[RERANK_SCORE:\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
    r"\s*\][ \t]*\r?\n?"
)
_RETRIEVAL_REQUIREMENT_LINE_RE = re.compile(
    r"(?mi)^[ \t]*\[RETRIEVAL_REQUIREMENT_ID:\s*"
    r"([A-Z][A-Z0-9_]{1,63})\s*\][ \t]*\r?\n?"
)
_RETRIEVAL_QUERY_FACET_LINE_RE = re.compile(
    r"(?mi)^[ \t]*\[RETRIEVAL_QUERY_FACET:\s*"
    r"([A-Z][A-Z0-9_]{1,63})\s*\][ \t]*\r?\n?"
)


def split_source_records(context_text: str) -> list[str]:
    """Split a tool response into source records marked by ``NGUỒN``."""

    text = str(context_text or "")
    matches = list(
        re.finditer(
            r"(?=^[ \t]*-\s*NGUỒN\s*:)",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
    )
    records: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        record = text[match.start():end].strip()
        if record:
            records.append(record)
    return records


def retrieval_rerank_score(source_text: str) -> float | None:
    """Return the reranker score attached to one retrieved source."""

    match = _RERANK_SCORE_LINE_RE.search(str(source_text or ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def retrieval_requirement_id(source_text: str) -> str:
    """Return the requirement identifier attached by retrieval."""

    match = _RETRIEVAL_REQUIREMENT_LINE_RE.search(str(source_text or ""))
    return match.group(1).strip().upper() if match else ""


def retrieval_query_facet(source_text: str) -> str:
    """Return the query facet attached by retrieval."""

    match = _RETRIEVAL_QUERY_FACET_LINE_RE.search(str(source_text or ""))
    return match.group(1).strip().upper() if match else ""


def strip_retrieval_metadata(source_text: str) -> str:
    """Remove retrieval-only lines without changing the legal source text."""

    text = _RERANK_SCORE_LINE_RE.sub("", str(source_text or ""))
    text = _RETRIEVAL_REQUIREMENT_LINE_RE.sub("", text)
    return _RETRIEVAL_QUERY_FACET_LINE_RE.sub("", text).strip()


def source_citation(source_text: str) -> str:
    """Build a readable citation from a retrieved source header."""

    text = str(source_text or "").strip()
    if not text:
        return ""
    first_line = text.splitlines()[0]
    citation = re.sub(
        r"^\s*-\s*NGUỒN\s*:\s*",
        "",
        first_line,
        flags=re.IGNORECASE,
    )
    citation = re.sub(r"^\s*\[[^]]+\]\s*-\s*", "", citation)
    citation = re.sub(
        r"^(?:BỘ\s+LUẬT|LUẬT|NGHỊ\s+ĐỊNH|THÔNG\s+TƯ|NGHỊ\s+QUYẾT)\s+"
        r"(?=(?:Bộ\s+luật|Luật|Nghị\s+định|Thông\s+tư|Nghị\s+quyết)\b)",
        "",
        citation,
        flags=re.IGNORECASE,
    )
    citation = re.sub(
        r"(\bĐiều\s+\d+[A-Za-zđĐ]?)\s*-\s*.+$",
        r"\1",
        citation,
        flags=re.IGNORECASE,
    ).strip()
    clause = re.search(r"-\s*Khoản\s+(\d+)", text, re.IGNORECASE)
    if clause and not re.search(
        rf"\bKhoản\s+{clause.group(1)}\b",
        citation,
        re.IGNORECASE,
    ):
        citation += f", Khoản {clause.group(1)}"
    return citation


__all__ = [
    "retrieval_query_facet",
    "retrieval_rerank_score",
    "retrieval_requirement_id",
    "source_citation",
    "split_source_records",
    "strip_retrieval_metadata",
]
