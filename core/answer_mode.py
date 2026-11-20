"""Choose a public answer shape from the user's request, not the retrieval route."""

from __future__ import annotations

import re


_PROCEDURE_SIGNAL_RE = re.compile(
    r"(?:quy\s+trình|thủ\s+tục|hồ\s+sơ|cấp\s+lại|cấp\s+đổi|"
    r"nộp\s+(?:ở\s+)?đâu|làm\s+(?:như\s+thế\s+nào|sao)|cần\s+những\s+gì)",
    re.IGNORECASE,
)


def is_procedure_question(question: str) -> bool:
    """Return whether the user explicitly asks how to complete a procedure."""

    return bool(_PROCEDURE_SIGNAL_RE.search(str(question or "").strip()))


def response_mode_for_question(
    question: str,
    has_explicit_article: bool = False,
    route: str = "SIMPLE",
) -> str:
    """Choose a public answer shape from the routed request, not legal subject matter."""
    if has_explicit_article:
        return "article"
    # Presentation follows the requested outcome. A question may require the
    # COMPLEX evidence pipeline and still ask for a practical procedure rather
    # than a six-section dispute memorandum.
    if is_procedure_question(question):
        return "procedure"
    if str(route or "").upper() == "COMPLEX":
        return "consultation"
    return "explanation"
