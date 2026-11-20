"""Lightweight intent checks used only to maintain terminal conversation state.

Route selection belongs to ``core.pipeline.router``.  These checks never choose
ARTICLE, SIMPLE or COMPLEX; they only decide whether a short user turn needs the
previous turn to remain understandable.
"""

from __future__ import annotations

import re

from core.text_normalization import fold_vietnamese


_GREETING_RE = re.compile(
    r"\s*(?:hi|hello|hey|xin chao|chao|chao ban|ban la ai)[?!. ]*\s*"
)
_CAPABILITY_RE = re.compile(
    r"\s*(?:(?:ban|he thong|tro ly) )?"
    r"(?:co the lam gi|lam duoc gi|ho tro (?:duoc )?gi|"
    r"co chuc nang gi|chuc nang (?:cua ban )?la gi|giup (?:duoc )?gi|"
    r"help|tro giup)\s*[?!.]*\s*"
)
_VAGUE_RE = re.compile(
    r"\s*(?:toi )?(?:muon|can) (?:hoi|tu van|nho tu van)|"
    r"\s*(?:toi )?co (?:mot )?tinh huong|"
    r"\s*(?:tu van|ho tro|xem) (?:giup )?(?:toi|minh)?\s*[?!.]*\s*"
)
_LIGHT_TURN_RE = re.compile(
    r"\s*(?:toi|minh|em|anh|chi) (?:nam nay )?\d{1,3} tuoi\s*[?!.]*\s*|"
    r"\s*(?:toi|minh|em) ten (?:la )?[^?!.]{1,60}[?!.]*\s*|"
    r"\s*(?:cam on|ok|okay|duoc roi|hieu roi|tot|hay)\s*[?!.]*\s*"
)
_LEGAL_SIGNAL_RE = re.compile(
    r"\b(?:dat|thua dat|quyen su dung dat|so do|giay chung nhan|"
    r"thu hoi|boi thuong|tai dinh cu|lan chiem|tranh chap|chuyen nhuong|"
    r"tang cho|thua ke|dia chinh|luat|bo luat|nghi dinh|thong tu|"
    r"nghi quyet|an le|phap luat|phap ly|toa an|khoi kien|khieu nai|"
    r"to cao|dieu \d+|khoan \d+)\b"
)
_ANSWER_INTENT_RE = re.compile(
    r"\?|\b(?:hoi|nhu the nao|the nao|la gi|co duoc khong|noi gi|"
    r"so sanh|phan biet|khac nhau|khi nao|dung khong|bao nhieu|"
    r"tham quyen|xu ly|muc phat|thu tuc|quy trinh|ho so|thoi han|"
    r"cap lai|cap doi|dieu kien|quy dinh|du tuoi)\b"
)
_LOOKUP_PREFIX_RE = re.compile(
    r"^\s*(?:quyen su dung|nghia vu|thu tuc|quy trinh|ho so|thoi han|"
    r"cap lai|cap doi|dieu kien|quy dinh|luat lien quan|can cu phap ly)\b"
)
_DECLARATIVE_FACT_RE = re.compile(
    r"\b(?:ong|ba|anh|chi|gia dinh|ho gia dinh|ubnd|uy ban|da|dang|"
    r"vua|bi|duoc cap|co dien tich)\b"
)


def has_legal_signal(query: str) -> bool:
    return bool(_LEGAL_SIGNAL_RE.search(fold_vietnamese(str(query or ""))))


def is_intake_query(query: str) -> bool:
    """Return whether one turn records context without asking for an answer."""

    text = str(query or "").strip()
    folded = fold_vietnamese(text)
    contextualized = re.fullmatch(
        r"Câu hỏi trước:\s*(.*?)\nCâu hỏi nối tiếp:\s*(.*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if contextualized:
        return is_intake_query(contextualized.group(1)) and is_intake_query(
            contextualized.group(2)
        )
    if "\nBổ sung của người dùng:" in text:
        parts = re.split(
            r"\nBổ sung của người dùng:\s*",
            text,
            flags=re.IGNORECASE,
        )
        return bool(parts) and all(
            is_intake_query(part) for part in parts if part.strip()
        )
    if any(
        pattern.fullmatch(folded)
        for pattern in (_GREETING_RE, _CAPABILITY_RE, _VAGUE_RE, _LIGHT_TURN_RE)
    ):
        return True
    if _LOOKUP_PREFIX_RE.search(folded) and not _DECLARATIVE_FACT_RE.search(folded):
        return False
    if has_legal_signal(text) and not _ANSWER_INTENT_RE.search(folded):
        return True
    return len(text.split()) <= 20 and not _ANSWER_INTENT_RE.search(folded)


__all__ = ["has_legal_signal", "is_intake_query"]
