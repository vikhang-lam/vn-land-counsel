"""Validated factual features carried through the complex legal pipeline."""

from __future__ import annotations

import re
from typing import Any

from core.json_contracts import parse_json_object_tolerant


ALLOWED_FACT_CATEGORIES = {
    "ACTOR",
    "CONDUCT",
    "LAND_TYPE",
    "AFFECTED_AREA",
    "TOTAL_AREA",
    "LOCATION",
    "LEGAL_STATUS",
    "ELIGIBILITY_STATUS",
    "TIME",
    "REQUEST",
    "OTHER",
}

_EXPLICIT_PERSON_AGE_RE = re.compile(
    r"\b(?:tôi|tui|mình|em|anh|chị|ông|bà|người)\s+"
    r"(?:năm\s+nay\s+)?\d{1,3}\s+tuổi\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _load_json(text: str) -> dict[str, Any]:
    """Compatibility facade for the shared tolerant object parser."""

    return parse_json_object_tolerant(text)


def _final_request_quote(question: str) -> str:
    """Return the final explicit user request, excluding prior intake instructions."""
    text = str(question or "").strip()
    if "?" not in text:
        return ""
    explicit_request = re.search(r"(?:^|\n)\s*(?:Hỏi|Câu\s+hỏi)\s*:\s*(.+\?)\s*$", text, re.IGNORECASE | re.DOTALL)
    if explicit_request:
        return explicit_request.group(1).strip()
    first_question = text.find("?")
    sentence_start = max(
        text.rfind(".", 0, first_question),
        text.rfind("!", 0, first_question),
        text.rfind("\n", 0, first_question),
    )
    return text[sentence_start + 1 :].strip()


def case_fact_extraction_text(question: str) -> str:
    """Exclude an explicitly labelled final request from the extractor input."""
    text = str(question or "").strip()
    # Dấu hai chấm là ranh giới cú pháp bắt buộc. Câu "Hỏi nếu ..." có thể
    # chứa một tiền đề thực tế sau chữ Hỏi nên phải được giữ nguyên.
    marker = re.search(
        r"(?:^|(?<=[.!?]))\s*(?:Hỏi|Câu\s+hỏi)\s*:\s*",
        text,
        re.IGNORECASE,
    )
    if not marker:
        return text
    narrative = text[: marker.start()].strip()
    return narrative or text


def validate_case_facts(raw_output: str, original_question: str) -> list[dict[str, str]]:
    """Keep only facts backed by a verbatim quote from the original question."""
    payload = _load_json(raw_output)
    raw_facts = payload.get("facts", [])
    if not isinstance(raw_facts, list):
        return []

    normalized_question = _normalize(original_question)
    facts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    # Keep the bounded extractor output in source order, including facts near
    # the end of a long narrative.  The previous 16-record projection could
    # silently discard the decisive consequence paragraph even when the
    # fine-tuned extractor returned it correctly (for example, an authority
    # detecting altered documents and refusing the application).  Downstream
    # Planner requirements already select at most six relevant fact IDs, so a
    # wider immutable ledger does not broaden any individual legal inference.
    for item in raw_facts[:35]:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "OTHER")).strip().upper()
        # The compact extractor contract emits one verbatim field.  Keep
        # accepting the previous shape so stored traces and callers remain valid.
        source_quote = str(item.get("quote") or item.get("source_quote", "")).strip()
        if category not in ALLOWED_FACT_CATEGORIES:
            category = "OTHER"
        if category in {"AFFECTED_AREA", "TOTAL_AREA"} and re.search(
            r"\d[\d\s.,]*(?:đồng|vnđ|vnd|đ)\b",
            source_quote,
            re.IGNORECASE,
        ):
            category = "OTHER"
        if not source_quote or _normalize(source_quote) not in normalized_question:
            continue
        # The quote is the only fact payload Python can safely pass onward.
        # Categories are agent-selected, but values must not introduce a
        # paraphrase the source text never made.
        value = source_quote
        key = (category, _normalize(value))
        if key in seen:
            continue
        seen.add(key)
        facts.append(
            {
                "fact_id": f"F{len(facts) + 1:03d}",
                "category": category,
                "value": value,
                "source_quote": source_quote,
            }
        )

    # Preserve an explicit age even when the small Fact Extractor omits it.
    # Python only copies a verbatim span; it does not decide whether the age
    # satisfies a legal condition.  That legal relation remains the Condition
    # Matcher's responsibility.
    normalized_existing_quotes = {
        _normalize(fact.get("source_quote", ""))
        for fact in facts
    }
    for match in _EXPLICIT_PERSON_AGE_RE.finditer(str(original_question or "")):
        source_quote = re.sub(r"\s+", " ", match.group(0)).strip()
        normalized_quote = _normalize(source_quote)
        if not source_quote or any(
            normalized_quote in existing_quote
            or existing_quote in normalized_quote
            for existing_quote in normalized_existing_quotes
            if existing_quote
        ):
            continue
        normalized_existing_quotes.add(normalized_quote)
        facts.append(
            {
                "fact_id": "",
                "category": "OTHER",
                "value": source_quote,
                "source_quote": source_quote,
            }
        )

    final_request = _final_request_quote(original_question)
    if final_request:
        facts = [fact for fact in facts if fact["category"] != "REQUEST"]
        facts.append(
            {
                "fact_id": "",
                "category": "REQUEST",
                "value": final_request,
                "source_quote": final_request,
            }
        )

    for index, fact in enumerate(facts, 1):
        fact["fact_id"] = f"F{index:03d}"
    return facts


def render_case_facts(facts: list[dict[str, str]]) -> str:
    if not facts:
        return "Không có fact có cấu trúc đã được Python xác nhận."
    return "\n".join(
        f"[{fact['fact_id']}] {fact['category']}: {fact['value']}"
        for fact in facts
    )


def fact_terms_for_ids(facts: list[dict[str, str]], fact_ids: list[str]) -> list[str]:
    """Map LLM-selected fact IDs to validated fact values in the same order."""
    by_id = {str(fact.get("fact_id", "")): fact for fact in facts}
    terms: list[str] = []
    for fact_id in fact_ids:
        fact = by_id.get(str(fact_id))
        value = str(fact.get("value", "")).strip() if fact else ""
        if value and value not in terms:
            terms.append(value)
    return terms
