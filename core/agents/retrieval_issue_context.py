"""Deterministic accessors for issue-scoped retrieval context."""

from __future__ import annotations

import json
from typing import Any


def issue_retrieval_hints(
    temporal_context: str,
    index: int,
) -> tuple[str, list[dict[str, Any]], bool, str | None, str | None]:
    """Read issue type, requirements, fallback, and temporal retrieval hints."""
    try:
        payload = json.loads(temporal_context)
    except (json.JSONDecodeError, TypeError):
        return "OTHER", [], False, None, None
    specs = payload.get("issue_specs", []) if isinstance(payload, dict) else []
    safe_fallback = (
        bool(payload.get("safe_fallback", False))
        if isinstance(payload, dict)
        else False
    )
    if not isinstance(specs, list) or index < 1 or index > len(specs):
        return "OTHER", [], safe_fallback, None, None
    spec = specs[index - 1]
    if not isinstance(spec, dict):
        return "OTHER", [], safe_fallback, None, None
    issue_type = str(spec.get("issue_type", "OTHER")).strip().upper()
    time_basis = str(spec.get("time_basis", "hien_hanh")).strip().lower()
    target_date = (
        str(payload.get(time_basis) or "").strip() or None
        if time_basis in {"giao_dich", "vi_pham"}
        else None
    )
    named_document = (
        str(payload.get("van_ban_dich_danh") or "").strip() or None
        if time_basis == "van_ban_dich_danh"
        else None
    )
    raw_requirements = spec.get("required_evidence", [])
    requirements = (
        [
            dict(value)
            for value in raw_requirements
            if isinstance(value, dict)
            and str(value.get("objective", "")).strip()
        ]
        if isinstance(raw_requirements, list)
        else []
    )
    return issue_type, requirements, safe_fallback, target_date, named_document


def issue_linked_fact_ids(temporal_context: str, index: int) -> list[str]:
    """Carry fact links across agent-authored dependency edges.

    ``depends_on`` is produced by the Decomposer. A downstream issue may need
    material conditions already attached to its prerequisite issue. Python
    follows declared edges only and does not classify legal fact relationships.
    """
    try:
        payload = json.loads(temporal_context)
    except (json.JSONDecodeError, TypeError):
        return []
    specs = payload.get("issue_specs", []) if isinstance(payload, dict) else []
    if not isinstance(specs, list) or index < 1 or index > len(specs):
        return []

    specs_by_id = {
        str(spec.get("issue_id", "")).strip().upper(): spec
        for spec in specs
        if isinstance(spec, dict) and str(spec.get("issue_id", "")).strip()
    }
    root = specs[index - 1]
    if not isinstance(root, dict):
        return []

    fact_ids: list[str] = []
    visited: set[str] = set()

    def collect(spec: dict[str, Any]) -> None:
        issue_id = str(spec.get("issue_id", "")).strip().upper()
        if not issue_id or issue_id in visited:
            return
        visited.add(issue_id)
        requirements = spec.get("required_evidence", [])
        if isinstance(requirements, list):
            for requirement in requirements:
                if not isinstance(requirement, dict):
                    continue
                raw_ids = requirement.get("fact_ids", [])
                if isinstance(raw_ids, list):
                    fact_ids.extend(
                        str(value).strip()
                        for value in raw_ids
                        if str(value).strip()
                    )
        dependencies = spec.get("depends_on", [])
        if isinstance(dependencies, list):
            for dependency in dependencies:
                parent = specs_by_id.get(str(dependency).strip().upper())
                if isinstance(parent, dict):
                    collect(parent)

    collect(root)
    return list(dict.fromkeys(fact_ids))[:6]
