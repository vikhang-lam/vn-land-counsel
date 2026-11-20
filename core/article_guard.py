"""Prevent scenario numbers and other facts from becoming invented article IDs."""

from __future__ import annotations

import re


def explicit_article_numbers(question: str) -> set[str]:
    return {
        number.casefold()
        for number in re.findall(r"\bđiều\s+(\d+[a-zđ]?)\b", str(question or ""), re.IGNORECASE)
    }


def article_request_warning(question: str, requested_article: object, depth: int = 0) -> str:
    """Return a model-facing recovery instruction when an article was invented."""
    if depth > 0:
        return ""
    requested = {
        number.casefold()
        for number in re.findall(r"\d+[a-zđ]?", str(requested_article or ""), re.IGNORECASE)
    }
    allowed = explicit_article_numbers(question)
    if requested and requested.issubset(allowed):
        return ""
    return (
        "ARTICLE_GUARD_REJECTED: Câu hỏi gốc không nêu rõ số Điều được yêu cầu. "
        "Không được biến số thứ tự tình huống, năm, diện tích, số tiền hoặc số lượng thành số Điều. "
        "Hãy gọi search_law bằng nội dung pháp lý của câu hỏi."
    )
