"""Conversation rules that preserve legal context without sending full chat history."""

from __future__ import annotations

import re

from core.conversation_intent import has_legal_signal, is_intake_query


_FOLLOW_UP_RE = re.compile(
    r"^(?:nếu|nếu như|còn|vậy|thế|trường hợp này|vụ việc này|đối với trường hợp này)\b|"
    r"^(?:tôi\s+(?:hỏi|muốn hỏi|đang hỏi)|ý\s+(?:tôi|là)|không phải|đính chính)\b|"
    r"^(?:cái gì vậy|ý gì|sao vậy|tại sao vậy|quy định đó|trường hợp đó|việc đó|nội dung này)[?!. ]*$|"
    r"\b(?:thì sao|thế nào trong trường hợp này|cơ mà)\??$",
    re.IGNORECASE,
)

_ELLIPTICAL_LEGAL_DETAIL_RE = re.compile(
    r"^(?:(?:mức|khung)\s+(?:phạt|bồi\s+thường|hỗ\s+trợ)|phạt)\s+"
    r"(?:là\s+)?(?:bao\s+nhiêu|thế\s+nào|ra\s+sao)\??$|"
    r"^(?:thời\s+hạn|thời\s+hiệu)\s+(?:là\s+)?(?:bao\s+lâu|bao\s+nhiêu)\??$|"
    r"^(?:ai|cơ\s+quan\s+nào)\s+(?:có\s+)?thẩm\s+quyền\??$|"
    r"^(?:thẩm\s+quyền|thủ\s+tục|hồ\s+sơ|căn\s+cứ|điều\s+kiện|"
    r"biện\s+pháp\s+khắc\s+phục|hậu\s+quả)\s+"
    r"(?:là\s+gì|thế\s+nào|ra\s+sao)\??$|"
    r"^(?:quy\s+định|pháp\s+luật\s+quy\s+định)\s+(?:thế\s+nào|ra\s+sao)\??$|"
    r"^(?:theo\s+)?điều\s+nào\??$",
    re.IGNORECASE,
)
_REFERENTIAL_CASE_RE = re.compile(
    r"\b(?:"
    r"(?:mảnh|miếng|thửa|phần)\s+đất\s+(?:này|đó|kia|ấy)"
    r"|đất\s+(?:này|đó|kia|ấy|trên)"
    r"|trường\s+hợp\s+(?:này|đó|kia)"
    r"|vụ\s+việc\s+(?:này|đó|kia)"
    r"|(?:con\s+cháu|người\s+nhà|gia\s+đình)\s+(?:của\s+)?họ"
    r"|bên\s+(?:này|kia|đó)"
    r"|họ\s+(?:lại|đang|muốn|đòi|không)"
    r"|(?:lại|giờ)\s+đòi\s+đất"
    r"|sao\s+giờ"
    r")\b",
    re.IGNORECASE,
)
_ELLIPTICAL_LAND_USE_RE = re.compile(
    r"^(?:ở|sống|sử\s+dụng|canh\s+tác|xây\s+nhà)\s+"
    r"(?:ở\s+|trên\s+)?(?:mảnh|miếng|thửa|phần)?\s*đất\b",
    re.IGNORECASE,
)
_PROCEDURAL_STATUS_UPDATE_RE = re.compile(
    r"^(?:(?:tôi|chúng\s+tôi|các\s+bên|bên\s+(?:bán|mua|chuyển\s+nhượng|nhận))\s+)?"
    r"(?:đã|chưa|vẫn\s+chưa)\s+(?:hoàn\s+tất\s+)?"
    r"(?:đăng\s+ký(?:\s+biến\s+động)?|sang\s+tên|nộp\s+hồ\s+sơ|"
    r"công\s+chứng|chứng\s+thực)(?:\s+(?:rồi|xong))?[.! ]*$|"
    r"^(?:sổ\s+đỏ|giấy\s+chứng\s+nhận)\s+(?:đã\s+)?"
    r"(?:được\s+)?cấp(?:\s+(?:rồi|xong))?[.! ]*$",
    re.IGNORECASE,
)

_PERSONAL_FACT_RE = re.compile(
    r"\b(?:tôi|tui|mình|em|anh|chị)\s+(?:(?:tên\s+)?(?:là\s+)?[\wÀ-ỹ]{2,40}|"
    r"(?:năm\s+nay\s+)?\d{1,3}\s+tuổi)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_RE = re.compile(r"\b(?:tôi|tui|mình|em|anh|chị)\b", re.IGNORECASE)
_CONTEXT_LABEL_RE = re.compile(
    r"^(?:Câu hỏi trước|Câu hỏi nối tiếp|Bổ sung của người dùng):\s*",
    re.IGNORECASE,
)
_INTAKE_CONTROL_RE = re.compile(
    r"(?:^|(?<=[.!?])\s+)"
    r"(?:"
    r"tôi\s+muốn\s+trình\s+bày\s+từng\s+phần[^.!?]*"
    r"|hãy\s+ghi\s+nhận[^.!?]*(?:chưa\s+cần\s+kết\s+luận)?"
    r")"
    r"(?:[.!?]+|$)",
    re.IGNORECASE,
)
_CORRECTION_RE = re.compile(
    r"\b(?:tôi\s+)?(?:nhớ\s+(?:lộn|nhầm)|đính\s+chính|xin\s+sửa|sửa\s+lại)\b|"
    r"\bkhông\s+phải\b[^.!?]{0,160}\bmà\s+(?:là\s+)?",
    re.IGNORECASE,
)
_CORRECTABLE_FACT_PATTERNS = (
    re.compile(r"\d+(?:[.,]\d+)?\s*(?:héc\s*ta|ha|m²|m2)\b", re.IGNORECASE),
    re.compile(r"\b(?:năm\s+)?(?:19|20)\d{2}\b|\bngày\s+\d{1,2}(?:/\d{1,2})?(?:/\d{4})?", re.IGNORECASE),
    re.compile(
        r"\bđất\s+(?:rừng\s+(?:sản\s+xuất|phòng\s+hộ|đặc\s+dụng)|"
        r"trồng\s+(?:lúa|cây\s+hàng\s+năm|cây\s+lâu\s+năm)|"
        r"nông\s+nghiệp|phi\s+nông\s+nghiệp|ở)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:xã|phường|thị\s+trấn|huyện|quận|tỉnh|thành\s+phố)\s+[\wÀ-ỹ.-]+", re.IGNORECASE),
)


def is_follow_up(query: str) -> bool:
    """Return whether the current turn depends on or corrects the previous turn."""
    text = str(query or "").strip()
    return bool(
        _FOLLOW_UP_RE.search(text)
        or _ELLIPTICAL_LEGAL_DETAIL_RE.fullmatch(text)
        or _REFERENTIAL_CASE_RE.search(text)
        or _ELLIPTICAL_LAND_USE_RE.search(text)
        or _PROCEDURAL_STATUS_UPDATE_RE.fullmatch(text)
    )


def is_personal_fact(query: str) -> bool:
    """Identify profile facts that may materially affect a later legal question."""
    return bool(_PERSONAL_FACT_RE.search(str(query or "")))


def depends_on_previous(query: str, previous_query: str = "") -> bool:
    """Decide whether retrieval must carry prior conversation into the current turn."""
    query = str(query or "").strip()
    previous_query = str(previous_query or "").strip()
    if not previous_query:
        return False
    continues_intake = is_intake_query(previous_query) and is_intake_query(query)
    uses_profile = (
        is_personal_fact(previous_query)
        and bool(_FIRST_PERSON_RE.search(query))
        and has_legal_signal(query)
    )
    supplies_profile_to_legal_request = (
        is_personal_fact(query)
        and has_legal_signal(previous_query)
    )
    supplements_legal_request = (
        has_legal_signal(previous_query)
        and not is_intake_query(previous_query)
        and has_legal_signal(query)
        and is_intake_query(query)
    )
    return (
        is_follow_up(query)
        or continues_intake
        or uses_profile
        or supplies_profile_to_legal_request
        or supplements_legal_request
    )


def contextualize_question(query: str, previous_query: str = "") -> str:
    """Resolve an explicit follow-up against the last legal question."""
    if not depends_on_previous(query, previous_query):
        return query
    previous_query = previous_query.strip()[-3000:]
    return f"Câu hỏi trước: {previous_query}\nCâu hỏi nối tiếp: {query}"


def canonicalize_legal_context(query: str, previous_query: str = "") -> str:
    """Flatten accumulated turns into a clean legal case without chat-control labels."""
    query = str(query or "").strip()
    previous_query = str(previous_query or "").strip()
    if not previous_query or not depends_on_previous(query, previous_query):
        return query

    parts: list[str] = []
    seen: set[str] = set()
    prior_lines = previous_query.splitlines()
    if _CORRECTION_RE.search(query):
        for pattern in _CORRECTABLE_FACT_PATTERNS:
            corrected_values = list(pattern.finditer(query))
            if not corrected_values:
                continue
            replacement = corrected_values[-1].group(0)
            for index in range(len(prior_lines) - 1, -1, -1):
                matches = list(pattern.finditer(prior_lines[index]))
                if not matches:
                    continue
                match = matches[-1]
                prior_lines[index] = (
                    prior_lines[index][: match.start()]
                    + replacement
                    + prior_lines[index][match.end() :]
                )
                break

    for raw_line in [*prior_lines, query]:
        line = _CONTEXT_LABEL_RE.sub("", raw_line.strip())
        line = _INTAKE_CONTROL_RE.sub("", line).strip(" .")
        if not line:
            continue
        key = re.sub(r"\s+", " ", line).casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(line)
    return "\n".join(parts) if parts else query


def update_conversation_context(query: str, previous_query: str = "") -> str:
    """Keep the base scenario while accumulating short follow-up constraints."""
    query = str(query or "").strip()
    previous_query = str(previous_query or "").strip()
    if not query:
        return previous_query
    continues_profile = is_personal_fact(query) and is_personal_fact(previous_query)
    if not previous_query or not (depends_on_previous(query, previous_query) or continues_profile):
        return query
    return f"{previous_query}\nBổ sung của người dùng: {query}"[-3000:]
