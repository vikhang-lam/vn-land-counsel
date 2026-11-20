"""Privacy-preserving transport helpers shared by planning and retrieval.

This module contains deterministic text transport only. It does not call an
LLM, choose a legal issue, select a legal rule, or execute retrieval.
"""

from __future__ import annotations

import json
import re


_VIETNAMESE_UPPER_INITIAL = (
    "A-Z"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬ"
    "Đ"
    "ÈÉẺẼẸÊỀẾỂỄỆ"
    "ÌÍỈĨỊ"
    "ÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢ"
    "ÙÚỦŨỤƯỪỨỬỮỰ"
    "ỲÝỶỸỴ"
)
_PARTY_NAME_RE = re.compile(
    rf"\b(?i:ông|bà|anh|chị|cô|chú|bác)\s+"
    rf"([{_VIETNAMESE_UPPER_INITIAL}][\wÀ-ỹĐđ]*"
    rf"(?:\s+[{_VIETNAMESE_UPPER_INITIAL}][\wÀ-ỹĐđ]*){{0,3}})"
)


def sanitize_retrieval_query(
    query: str,
    facts: list[dict[str, str]],
) -> str:
    """Remove case-specific party names without changing legal query meaning."""

    party_terms: set[str] = set()
    for fact in facts:
        if str(fact.get("category", "")).upper() != "ACTOR":
            continue
        source = str(fact.get("source_quote") or fact.get("value") or "")
        for match in _PARTY_NAME_RE.finditer(source):
            full_name = match.group(1).strip()
            party_terms.add(full_name)
            # A middle name can also be an ordinary legal word (for example
            # ``Văn`` in ``văn bản``). The full name and its final token are
            # sufficient to redact both complete and common short references.
            name_tokens = full_name.split()
            if name_tokens:
                party_terms.add(name_tokens[-1])

    cleaned = str(query or "")
    # In everyday Vietnamese, “nhà tôi ở/sống ...” normally denotes the
    # speaker's family, not a physical house.
    cleaned = re.sub(
        r"\bnhà\s+(tôi|mình|em|anh|chị|họ)\s+(?=(?:ở|sống|cư\s+trú)\b)",
        r"gia đình \1 ",
        cleaned,
        flags=re.IGNORECASE,
    )
    for term in sorted(party_terms, key=len, reverse=True):
        cleaned = re.sub(
            rf"\b{re.escape(term)}\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = _PARTY_NAME_RE.sub(" ", cleaned)
    cleaned = re.sub(
        r"\b(?:ông|bà|anh|chị|cô|chú|bác)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?<!\w)\d[\d\s.,]*(?:đồng|vnđ|vnd|đ)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:với\s+)?số tiền(?:\s+là)?\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bđiều kiện\s+pháp lý\s+(?:(?:của|để|đối với)\s+)?",
        "điều kiện ",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Chuẩn hóa các thuật ngữ giao dịch thửa đất/đất thành quyền sử dụng đất
    cleaned = re.sub(
        r"\bchuyển nhượng\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "chuyển nhượng một phần quyền sử dụng đất" if "một phần" in m.group(0).lower() else "chuyển nhượng quyền sử dụng đất",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\btặng cho\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "tặng cho một phần quyền sử dụng đất" if "một phần" in m.group(0).lower() else "tặng cho quyền sử dụng đất",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bthế chấp\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "thế chấp một phần quyền sử dụng đất" if "một phần" in m.group(0).lower() else "thế chấp quyền sử dụng đất",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bchuyển quyền\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "chuyển quyền một phần sử dụng đất" if "một phần" in m.group(0).lower() else "chuyển quyền sử dụng đất",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bmua bán\s+(?:một\s+phần\s+)?(?:thửa\s+)?đất\b",
        lambda m: "chuyển nhượng một phần quyền sử dụng đất" if "một phần" in m.group(0).lower() else "chuyển nhượng quyền sử dụng đất",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" ,;:-")


def planning_party_aliases(facts: list[dict[str, str]]) -> dict[str, str]:
    """Map every grounded party name to a stable privacy-preserving alias."""

    aliases: dict[str, str] = {}
    full_names: list[str] = []
    for fact in facts:
        source = str(fact.get("source_quote") or fact.get("value") or "")
        for match in _PARTY_NAME_RE.finditer(source):
            full_name = match.group(1).strip()
            if (
                len(full_name.split()) == 1
                and any(
                    existing.split()[-1].casefold() == full_name.casefold()
                    for existing in full_names
                )
            ):
                continue
            if full_name and full_name.casefold() not in {
                value.casefold() for value in full_names
            }:
                full_names.append(full_name)
    for index, full_name in enumerate(full_names):
        alias = f"Bên {chr(ord('A') + index)}"
        aliases[full_name] = alias
        last_name = full_name.split()[-1]
        aliases.setdefault(last_name, alias)
    return aliases


def pseudonymize_planning_text(
    text: str,
    facts: list[dict[str, str]],
) -> str:
    """Preserve party agency for planning while removing real identities."""

    cleaned = str(text or "")
    aliases = planning_party_aliases(facts)
    full_names = [name for name in aliases if len(name.split()) > 1]
    short_names = [name for name in aliases if len(name.split()) == 1]
    for name in sorted(full_names, key=len, reverse=True):
        alias = aliases[name]
        cleaned = re.sub(
            rf"\b(?:ông|bà|anh|chị|cô|chú|bác)\s+{re.escape(name)}\b",
            alias,
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            rf"\b{re.escape(name)}\b",
            alias,
            cleaned,
            flags=re.IGNORECASE,
        )
    for name in sorted(short_names, key=len, reverse=True):
        alias = aliases[name]
        cleaned = re.sub(
            rf"\b(?:ông|bà|anh|chị|cô|chú|bác)\s+{re.escape(name)}\b",
            alias,
            cleaned,
            flags=re.IGNORECASE,
        )
    return sanitize_retrieval_query(cleaned, [])


def pseudonymized_planning_facts(
    facts: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Render planning facts with stable aliases instead of erased parties."""

    output: list[dict[str, str]] = []
    for fact in facts:
        value = pseudonymize_planning_text(str(fact.get("value", "")), facts)
        source_quote = pseudonymize_planning_text(
            str(fact.get("source_quote", "")),
            facts,
        )
        if value and source_quote:
            output.append({**fact, "value": value, "source_quote": source_quote})
    return output


def anonymized_retrieval_facts(
    facts: list[dict[str, str]],
    fact_ledger: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Hide case identities before an LLM turns facts into a search query."""

    anonymized: list[dict[str, str]] = []
    for fact in facts:
        value = sanitize_retrieval_query(
            str(fact.get("value", "")),
            fact_ledger,
        )
        source_quote = sanitize_retrieval_query(
            str(fact.get("source_quote", "")),
            fact_ledger,
        )
        if not value or not source_quote:
            continue
        anonymized.append({**fact, "value": value, "source_quote": source_quote})
    return anonymized


def grounded_search_anchor(
    anchor: str,
    facts: list[dict[str, str]],
) -> str:
    """Keep only short anchor phrases copied from the validated Fact Ledger."""

    candidate = sanitize_retrieval_query(anchor, facts)
    normalized = candidate.casefold()
    if not normalized:
        return ""
    for fact in anonymized_retrieval_facts(facts, facts):
        for field in ("value", "source_quote"):
            fact_text = re.sub(
                r"\s+",
                " ",
                str(fact.get(field, "")),
            ).strip().casefold()
            if normalized in fact_text:
                return candidate
    return ""


def contains_party_identity(
    text: str,
    facts: list[dict[str, str]],
) -> bool:
    """Detect a party-name leak without interpreting legal content."""

    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return bool(normalized) and normalized != sanitize_retrieval_query(
        normalized,
        facts,
    )


def build_fact_anchored_query(
    objective: str,
    search_anchors: list[str],
    facts: list[dict[str, str]],
) -> str:
    """Transport agent-selected factual anchors into one retrieval query."""

    parts = [sanitize_retrieval_query(objective, facts)]
    parts.extend(
        sanitize_retrieval_query(anchor, facts)
        for anchor in search_anchors
    )
    result = re.sub(
        r"\s+",
        " ",
        " ".join(part for part in parts if part),
    ).strip()
    if len(result) <= 160:
        return result
    return result[:160].rsplit(" ", 1)[0]


def anonymize_decomposition_transport(
    issues: list[str],
    temporal_context: str,
    facts: list[dict[str, str]],
) -> tuple[list[str], str]:
    """Remove party identities after planning without changing its fact graph."""

    clean_issues = [sanitize_retrieval_query(issue, facts) for issue in issues]
    try:
        payload = json.loads(temporal_context)
    except (json.JSONDecodeError, TypeError):
        return clean_issues, temporal_context
    if not isinstance(payload, dict):
        return clean_issues, temporal_context

    specs = payload.get("issue_specs", [])
    if not isinstance(specs, list):
        return clean_issues, json.dumps(payload, ensure_ascii=False)
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        requirements = spec.get("required_evidence", [])
        if not isinstance(requirements, list):
            continue
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            requirement["objective"] = sanitize_retrieval_query(
                str(requirement.get("objective", "")),
                facts,
            )
            if str(requirement.get("query", "")).strip():
                requirement["query"] = sanitize_retrieval_query(
                    str(requirement.get("query", "")),
                    facts,
                )
            raw_anchors = requirement.get("search_anchors", [])
            if not isinstance(raw_anchors, list):
                continue
            grounded_anchors = [
                grounded_search_anchor(str(anchor), facts)
                for anchor in raw_anchors
                if isinstance(anchor, str)
            ]
            grounded_anchors = list(
                dict.fromkeys(anchor for anchor in grounded_anchors if anchor)
            )[:4]
            if grounded_anchors:
                requirement["search_anchors"] = grounded_anchors
            else:
                requirement.pop("search_anchors", None)
    return clean_issues, json.dumps(payload, ensure_ascii=False)
