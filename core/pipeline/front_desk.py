"""Response stages for non-legal routing branches."""

from __future__ import annotations

import re

from core.config import get_active_settings
from core.llm import LocalLLMClient

from .prompts import INTAKE_RESPONSE_SPEC, OUT_OF_SCOPE_RESPONSE_SPEC


_INTERNAL_ID_RE = re.compile(r"\b(?:I|R|RC|E|C|K|KC|AF|S)\d{3,}(?:_\d{2})?\b")


def _safe_public_text(text: str) -> str:
    value = str(text or "").strip()
    if not value or _INTERNAL_ID_RE.search(value):
        raise ValueError("Front Desk không trả nội dung công khai hợp lệ")
    return value


class IntakeResponseStage:
    def run(self, client: LocalLLMClient, question: str) -> str:
        settings = get_active_settings()
        response = client.complete(
            str(question or "").strip(),
            model=settings.router_model,
            system_prompt=INTAKE_RESPONSE_SPEC.text,
            temperature=0.2,
            max_tokens=180,
        )
        return _safe_public_text(response.text)


class OutOfScopeResponseStage:
    def run(self, client: LocalLLMClient, question: str) -> str:
        settings = get_active_settings()
        response = client.complete(
            str(question or "").strip(),
            model=settings.router_model,
            system_prompt=OUT_OF_SCOPE_RESPONSE_SPEC.text,
            temperature=0.1,
            max_tokens=160,
        )
        return _safe_public_text(response.text)


__all__ = ["IntakeResponseStage", "OutOfScopeResponseStage"]
