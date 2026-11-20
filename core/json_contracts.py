"""Shared JSON parsing primitives with explicit failure policies."""

from __future__ import annotations

import json
import re
from typing import Any


def reject_duplicate_object_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    """Build an object while rejecting ambiguous duplicate JSON keys."""

    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"JSON chứa khóa trùng: {key}")
        output[key] = value
    return output


def parse_json_object_tolerant(text: str) -> dict[str, Any]:
    """Parse a top-level JSON object and return an empty object on failure.

    This preserves the previous Case Fact and Decomposition contract. Evidence
    parsing deliberately remains strict and uses only the duplicate-key hook.
    """

    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
