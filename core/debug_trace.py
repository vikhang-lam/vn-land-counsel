"""Opt-in terminal traces for inspecting every pipeline contract."""

from __future__ import annotations

import json
import os
from typing import Any


def debug_enabled() -> bool:
    return os.getenv("PIPELINE_DEBUG", "false").strip().casefold() in {"1", "true", "yes", "on"}


def debug_log(message: Any) -> None:
    """Print one compact internal event only when pipeline debugging is enabled."""
    if debug_enabled():
        print(str(message), flush=True)


def debug_dump(title: str, value: Any) -> None:
    """Print inspectable state without feeding it into the public answer."""
    if not debug_enabled():
        return
    # Retry telemetry consumes only the event title. The import stays local so
    # this low-level debug helper remains independent from pipeline startup.
    from core.telemetry import observe_debug_event

    observe_debug_event(title)
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    else:
        text = str(value)
    try:
        max_chars = max(1000, int(os.getenv("PIPELINE_DEBUG_MAX_CHARS", "200000")))
    except ValueError:
        max_chars = 200000
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [DEBUG TRUNCATED: {len(text) - max_chars} chars]"
    border = "=" * 88
    print(f"\n{border}\nDEBUG :: {title}\n{border}\n{text}\n{border}")
