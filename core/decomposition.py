"""Shared constants and temporal validation for the clean planner."""

from __future__ import annotations

import json
from typing import Any

from core.json_contracts import parse_json_object_tolerant
from core.temporal_guard import allowed_target_date, inferred_named_document


VALID_TIME_BASES = {
    "giao_dich",
    "vi_pham",
    "hien_hanh",
    "van_ban_dich_danh",
}
VALID_ISSUE_TYPES = {
    "LEGAL_BASIS",
    "AUTHORITY_PROCEDURE",
    "RIGHTS_REMEDY",
    "TRANSACTION",
    "REGISTRATION",
    "SANCTION",
    "REMEDY",
    "ELIGIBILITY",
    "DISPUTE",
    "OTHER",
}
VALID_EVIDENCE_TARGETS = {
    "LEGAL_BASIS",
    "SUBJECT_OBJECT_CONDITIONS",
    "FORM_DOCUMENT",
    "REGISTRATION_COMPLETION",
    "AUTHORITY_PROCEDURE",
    "DEADLINE_OBLIGATION",
    "CONDUCT_CLASSIFICATION",
    "SANCTION_REMEDY",
    "LEGAL_CONSEQUENCE",
    "DISPUTE_REMEDY",
    "ELIGIBILITY",
    "OTHER_CONCRETE",
}


def _load_json(text: str) -> dict[str, Any]:
    return parse_json_object_tolerant(text)


def validate_temporal_context(raw_output: str, original_question: str) -> str:
    """Keep only dates and named documents stated in the user question."""

    payload = _load_json(raw_output)
    temporal = payload.get("temporal_context", payload)
    if not isinstance(temporal, dict):
        temporal = {}
    explicit_document = inferred_named_document(original_question)
    requested_document = str(temporal.get("van_ban_dich_danh") or "").strip()
    safe_temporal = {
        "giao_dich": allowed_target_date(
            original_question,
            temporal.get("giao_dich"),
        ),
        "vi_pham": allowed_target_date(
            original_question,
            temporal.get("vi_pham"),
        ),
        "van_ban_dich_danh": (
            explicit_document
            if requested_document and explicit_document
            else None
        ),
    }
    return json.dumps(safe_temporal, ensure_ascii=False)


__all__ = [
    "VALID_EVIDENCE_TARGETS",
    "VALID_ISSUE_TYPES",
    "VALID_TIME_BASES",
    "validate_temporal_context",
]
