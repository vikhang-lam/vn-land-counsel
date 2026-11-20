"""Input normalization that removes benchmark/UI labels without changing facts."""

from __future__ import annotations

import json
import re

from core.text_normalization import fold_vietnamese


_VIETNAMESE_UNACCENTED_MARKERS = frozenset(
    {
        "xin", "chao", "toi", "tui", "minh", "ban", "muon", "can", "biet", "hoi", "giup",
        "quy", "trinh", "thu", "tuc", "ho", "so", "cap", "lai", "doi", "dat", "do", "giay",
        "chung", "nhan", "tranh", "chap", "chuyen", "nhuong", "thua", "ke", "boi", "thuong",
        "hoi", "xu", "phat", "quyen", "su", "dung", "luat", "nghi", "dinh", "dieu", "khoan",
        "nhu", "the", "nao", "khong", "duoc", "bao", "nhieu",
    }
)
_TEEN_OR_TYPO_MARKERS = frozenset(
    {
        "tui", "mun", "bit", "biet", "ko", "khum", "hok", "hong", "hem", "dc", "duoc", "j", "z",
        "r", "roi", "mik", "minh", "bn", "mng", "vs", "qtrinh", "qtr", "sdo", "ntn", "nt", "bh",
        "nha", "ne", "nhe", "ua", "a", "ah", "oi", "o",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-zÀ-ỹĐđ0-9]+")

# These are only colloquial abbreviations whose expansion does not add legal facts.
# Values stay unaccented because comparison happens on folded tokens.
_SAFE_CHAT_ALIASES = {
    "ko": "khong",
    "khum": "khong",
    "hok": "khong",
    "hong": "khong",
    "hem": "khong",
    "dc": "duoc",
    "j": "gi",
    "vs": "voi",
}
_SAFE_CHAT_TOKEN_SPANS = {
    "qtrinh": ("quy", "trinh"),
    "qtr": ("quy", "trinh"),
    "sdo": ("so", "do"),
    "ntn": ("nhu", "the", "nao"),
    "bh": ("bay", "gio"),
}
_EDGE_CHAT_PARTICLES = frozenset({"a", "ah", "oi", "o", "nha", "ne", "nhe", "ha", "hen", "roi"})
_PROTECTED_LEGAL_TOKENS = frozenset(
    {
        "dieu", "khoan", "diem", "luat", "bo", "nghi", "dinh", "thong", "tu", "nghiquyet",
        "quyen", "sudung", "dat", "giay", "chungnhan", "chuyennhuong", "tangcho", "thechap",
        "gopvon", "thuhoi", "boithuong", "taidinhcu", "xuphat", "vipham", "khieunai", "tocao",
    }
)
_LEGAL_QUERY_HINTS = frozenset(
    {
        "dat", "sodo", "sohong", "giay", "chungnhan", "quytrinh", "thutuc", "hoso", "cap", "lai",
        "luat", "nghi", "dinh", "thong", "tu", "dieu", "khoan", "diem", "tranh", "chap",
        "chuyennhuong", "tangcho", "thua", "ke", "thechap", "gopvon", "thuhoi", "boithuong",
        "taidinhcu", "xuphat", "vipham", "khieunai", "thamdinh", "quyen", "sudung", "muccich",
        "quy", "trinh", "thu", "tuc", "ho", "so", "chuyen", "nhuong", "xu", "phat",
    }
)


def fold_vietnamese_text(value: str) -> str:
    """Compare Vietnamese text without diacritics while retaining digits and word order."""

    return fold_vietnamese(value)


def needs_diacritic_restoration(question: str) -> bool:
    """Detect unaccented Vietnamese, teen code, Telex and mild typing mistakes."""
    text = str(question or "").strip()
    if not text:
        return False
    tokens = [fold_vietnamese_text(token) for token in _TOKEN_RE.findall(text)]
    markers = sum(token in _VIETNAMESE_UNACCENTED_MARKERS for token in tokens)
    teen_or_typo = any(token in _TEEN_OR_TYPO_MARKERS for token in tokens)
    has_diacritic = bool(re.search(r"[à-ỹÀ-ỸĐđ]", text))
    return len(tokens) >= 2 and ((not has_diacritic and markers >= 1) or teen_or_typo)


def should_restore_diacritics_for_legal_query(question: str) -> bool:
    """Avoid a needless LLM call for casual chat while restoring legal queries early."""
    if not needs_diacritic_restoration(question):
        return False
    tokens = [_canonical_typed_token(token) for token in _TOKEN_RE.findall(question)]
    return any(token in _LEGAL_QUERY_HINTS for token in tokens)


def _canonical_typed_token(value: str) -> str:
    """Reduce common Telex key sequences to the same skeleton as accented Vietnamese."""
    token = fold_vietnamese_text(value)
    for source, replacement in (("dd", "d"), ("aw", "a"), ("aa", "a"), ("ee", "e"), ("ow", "o"), ("oo", "o"), ("uw", "u")):
        token = token.replace(source, replacement)
    if len(token) > 1 and token[-1] in "sfrxj":
        token = token[:-1]
    return _SAFE_CHAT_ALIASES.get(token, token)


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    """Accept one missing, repeated or substituted character without broad fuzzy matching."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    index_left = index_right = edits = 0
    while index_left < len(left) and index_right < len(right):
        if left[index_left] == right[index_right]:
            index_left += 1
            index_right += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if len(left) > len(right):
            index_left += 1
        elif len(right) > len(left):
            index_right += 1
        else:
            index_left += 1
            index_right += 1
    return True


def _token_matches_after_diacritic_restoration(source: str, restored: str) -> bool:
    source = _canonical_typed_token(source)
    restored = _canonical_typed_token(restored)
    # Facts such as years, article numbers and quantities must never be fuzzy-matched.
    if source.isdigit() or restored.isdigit():
        return source == restored
    if source == restored:
        return True
    # Do not turn a legal term into a near-spelled but different term.
    if source in _PROTECTED_LEGAL_TOKENS or restored in _PROTECTED_LEGAL_TOKENS:
        return False
    return len(source) >= 2 and len(restored) >= 2 and _edit_distance_at_most_one(source, restored)


def validate_diacritic_restoration(raw_output: str, original_question: str) -> str:
    """Accept accent restoration only when every user token remains unchanged.

    This permits accents and narrow Telex cleanup but rejects paraphrases,
    changed numbers, changed named documents, and new legal facts.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw_output or "").strip(), flags=re.IGNORECASE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return original_question
    candidate = str(payload.get("restored_question", "")).strip() if isinstance(payload, dict) else ""
    candidate = re.sub(r"\s+", " ", candidate)
    if not candidate or len(candidate) > max(1800, len(original_question) * 2):
        return original_question

    source_tokens = [fold_vietnamese_text(token) for token in _TOKEN_RE.findall(original_question)]
    candidate_tokens = [fold_vietnamese_text(token) for token in _TOKEN_RE.findall(candidate)]
    source_index = candidate_index = 0
    while source_index < len(source_tokens) and candidate_index < len(candidate_tokens):
        source = source_tokens[source_index]
        restored = candidate_tokens[candidate_index]
        expected_span = _SAFE_CHAT_TOKEN_SPANS.get(source)
        if expected_span:
            actual_span = tuple(
                _canonical_typed_token(token)
                for token in candidate_tokens[candidate_index:candidate_index + len(expected_span)]
            )
            if actual_span == expected_span:
                source_index += 1
                candidate_index += len(expected_span)
                continue
        if _token_matches_after_diacritic_restoration(source, restored):
            source_index += 1
            candidate_index += 1
            continue
        # Conversational particles at the beginning/end ("oi", "nha", "ó") carry
        # no legal fact and may be omitted by the normalizer.
        if (
            source in _EDGE_CHAT_PARTICLES
            and source_index in {0, len(source_tokens) - 1}
        ):
            source_index += 1
            continue
        # A space accidentally inserted inside a word, for example "tu i" -> "tôi".
        if (
            source_index + 1 < len(source_tokens)
            and len(source) <= 2
            and _token_matches_after_diacritic_restoration(source + source_tokens[source_index + 1], restored)
        ):
            source_index += 2
            candidate_index += 1
            continue
        return original_question
    while (
        source_index < len(source_tokens)
        and source_tokens[source_index] in _EDGE_CHAT_PARTICLES
        and source_index in {0, len(source_tokens) - 1}
    ):
        source_index += 1
    if source_index != len(source_tokens) or candidate_index != len(candidate_tokens):
        return original_question
    return candidate


def normalize_question_text(question: str) -> str:
    """Remove a leading case number so it cannot be mistaken for an article."""
    text = str(question or "").strip()
    text = re.sub(r"\\r\\n|\\n", "\n", text)
    text = re.sub(
        r"^(?:(?:tình(?:\s*huống)?|câu\s*hỏi|bài|case|question)\s*(?:số\s*)?\d+\s*[.:)\-]*\s*)",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    return text.strip()
