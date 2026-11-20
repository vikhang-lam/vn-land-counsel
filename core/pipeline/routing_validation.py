"""Structural validation for the clean Router contract.

Semantic routing belongs to the model. Python validates only JSON types and
the mechanical requirement that ARTICLE contains exactly one explicit Article.
"""

from __future__ import annotations

import json
import re

from core.article_guard import explicit_article_numbers
from core.json_contracts import reject_duplicate_object_keys

from .contracts import Route


def is_exact_article_lookup(question: str) -> bool:
    """ARTICLE can execute only when one Article number is extractable."""

    return len(explicit_article_numbers(str(question or ""))) == 1


def syntax_proven_route(question: str) -> Route | None:
    """The clean Router makes semantic decisions; no keyword route bypass."""

    return None


def parse_router_payload(raw_output: str) -> Route:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(raw_output or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        payload = json.loads(
            cleaned,
            object_pairs_hook=reject_duplicate_object_keys,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError("Router trả JSON không hợp lệ") from error
    if not isinstance(payload, dict) or set(payload) != {"route"}:
        raise ValueError("Router trả sai trường dữ liệu")
    return Route.parse(str(payload["route"]))


def validate_router_decision(question: str, raw_output: str) -> Route:
    route = parse_router_payload(raw_output)
    if route is Route.ARTICLE:
        return Route.ARTICLE if is_exact_article_lookup(question) else Route.SIMPLE
    return route


def parse_scope_review(raw_output: str) -> bool | None:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(raw_output or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        payload = json.loads(
            cleaned,
            object_pairs_hook=reject_duplicate_object_keys,
        )
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"in_scope"}:
        return None
    value = payload["in_scope"]
    return value if isinstance(value, bool) else None


__all__ = [
    "is_exact_article_lookup",
    "parse_router_payload",
    "parse_scope_review",
    "syntax_proven_route",
    "validate_router_decision",
]
