"""Reject temporal and document filters that are not stated by the user."""

from __future__ import annotations

import re
import unicodedata


_active_question = ""


def set_active_question(question: str) -> None:
    """Set the current user question for synchronous tool calls in the CLI agent."""
    global _active_question
    _active_question = str(question or "")


def get_active_question() -> str:
    return _active_question


def sanitize_active_temporal_arguments(
    target_date: object = None,
    named_document: object = None,
    is_transitional: bool = False,
) -> tuple[str | None, str | None, bool]:
    return sanitize_temporal_arguments(_active_question, target_date, named_document, is_transitional)


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("đ", "d")
    return re.sub(r"[^a-z0-9]", "", text)


def _explicit_dates(question: str) -> list[str]:
    dates: set[str] = set()
    for year, month, day in re.findall(r"\b((?:19|20)\d{2})[-/]([01]?\d)[-/]([0-3]?\d)\b", question):
        dates.add(f"{year}-{int(month):02d}-{int(day):02d}")
    for day, month, year in re.findall(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+((?:19|20)\d{2})", question, re.IGNORECASE):
        dates.add(f"{year}-{int(month):02d}-{int(day):02d}")
    for month, year in re.findall(r"tháng\s+(\d{1,2})\s+năm\s+((?:19|20)\d{2})", question, re.IGNORECASE):
        dates.add(f"{year}-{int(month):02d}")
    dates.update(re.findall(r"(?:năm\s+)?((?:19|20)\d{2})\b", question, re.IGNORECASE))
    return sorted(dates, key=len, reverse=True)


def _looks_like_document_year(question: str, position: int) -> bool:
    prefix = question[max(0, position - 90):position]
    document_prefix = (
        r"(?:bộ\s+luật\s+\S+|luật\s+(?:đất(?:\s+đai)?|nhà\s+ở|hôn\s+nhân|"
        r"công\s+chứng|khiếu\s+nại|tố\s+cáo|tố\s+tụng|kinh\s+doanh)|"
        r"nghị\s*định(?:\s+số)?|thông\s*tư(?:\s+số)?|nghị\s*quyết(?:\s+số)?|"
        r"văn\s*bản\s*hợp\s*nhất(?:\s+số)?)[^.!?\n]{0,70}$"
    )
    return bool(re.search(document_prefix, prefix, re.IGNORECASE))


def _fact_dates(question: str) -> list[str]:
    """Extract dates describing the facts, excluding years that only name a document."""
    dates: set[str] = set()
    for year, month, day in re.findall(r"\b((?:19|20)\d{2})[-/]([01]?\d)[-/]([0-3]?\d)\b", question):
        dates.add(f"{year}-{int(month):02d}-{int(day):02d}")
    for day, month, year in re.findall(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+((?:19|20)\d{2})", question, re.IGNORECASE):
        dates.add(f"{year}-{int(month):02d}-{int(day):02d}")
    for month, year in re.findall(r"tháng\s+(\d{1,2})\s+năm\s+((?:19|20)\d{2})", question, re.IGNORECASE):
        dates.add(f"{year}-{int(month):02d}")
    for match in re.finditer(r"\b(?:19|20)\d{2}\b", question):
        if not _looks_like_document_year(question, match.start()):
            dates.add(match.group(0))
    return sorted(dates, key=len, reverse=True)


def _date_key(value: str) -> tuple[int, int, int]:
    parts = [int(part) for part in value.split("-")]
    return tuple((parts + [0, 0, 0])[:3])


def inferred_target_date(question: str) -> str | None:
    """Choose the latest explicit fact date when the agent omitted a time filter."""
    dates = _fact_dates(question)
    return max(dates, key=_date_key) if dates else None


def inferred_named_document(question: str) -> str | None:
    """Recover a directly named document without relying on an agent tool argument."""
    land_law = re.search(
        r"\bluật\s+đất(?:\s+đai)?\s+(?:năm\s+)?((?:19|20)\d{2})\b",
        question,
        re.IGNORECASE,
    )
    if land_law:
        return f"Luật Đất đai {land_law.group(1)}"

    designation = re.search(
        r"\b((?:nghị\s*định|thông\s*tư|nghị\s*quyết)\s+(?:số\s+)?\d{1,4}/(?:19|20)\d{2}(?:/[\w\-]+)?)",
        question,
        re.IGNORECASE,
    )
    return designation.group(1) if designation else None


def allowed_target_date(question: str, requested: object) -> str | None:
    """Return only the precision that is explicit in the original question."""
    value = str(requested or "").strip()
    if not value:
        return None
    fact_dates = _fact_dates(question)
    if fact_dates:
        allowed_dates = fact_dates
    elif inferred_named_document(question):
        # A year that only identifies a statute is not the event date.
        return None
    else:
        allowed_dates = _explicit_dates(question)

    for allowed in allowed_dates:
        if value == allowed:
            return allowed
        if value.startswith(allowed + "-"):
            return allowed
        if allowed.startswith(value + "-"):
            return allowed
    return None


def allowed_named_document(question: str, requested: object) -> str | None:
    """Allow a named document only when it appears in the user question."""
    value = str(requested or "").strip()
    if not value:
        return None
    normalized_question = _normalize(question)
    normalized_value = _normalize(value)
    if normalized_value and normalized_value in normalized_question:
        return value

    designation = re.search(r"\d{1,4}/(?:19|20)\d{2}", value)
    if designation and _normalize(designation.group(0)) in normalized_question:
        return value
    return None


def sanitize_temporal_arguments(
    question: str,
    target_date: object = None,
    named_document: object = None,
    is_transitional: bool = False,
) -> tuple[str | None, str | None, bool]:
    """Drop filters invented by an agent while preserving explicit user inputs."""
    safe_date = allowed_target_date(question, target_date) or inferred_target_date(question)
    safe_document = allowed_named_document(question, named_document) or inferred_named_document(question)
    return safe_date, safe_document, bool(is_transitional and safe_date)


def target_date_to_int(target_date: object) -> int | None:
    """Convert a YYYY, YYYY-MM, or YYYY-MM-DD filter to an effective-date integer."""
    value = str(target_date or "").strip()
    if not value or value.lower() == "all":
        return None
    try:
        parts = value.split("-")
        if len(parts) == 1:
            return int(f"{parts[0]}0101")
        if len(parts) == 2:
            return int(f"{parts[0]}{int(parts[1]):02d}01")
        if len(parts) == 3:
            return int(f"{parts[0]}{int(parts[1]):02d}{int(parts[2]):02d}")
    except (TypeError, ValueError):
        return None
    return None
