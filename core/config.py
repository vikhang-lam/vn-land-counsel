"""Cấu hình mô hình cho pipeline chạy cục bộ."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


SUPPORTED_MODEL_PROFILES = frozenset({"all_4b", "answer_8b", "two_phase"})
DEFAULT_PLANNING_MODEL = "Qwen3-4B-Q4_K_M"
DEFAULT_ANSWER_MODEL = "Qwen3-8B-Q5_K_M"
DEFAULT_ROUTER_MODEL = DEFAULT_ANSWER_MODEL
DEFAULT_FACT_MODEL = "Fact-Qwen3-8B-LoRA"
DEFAULT_PLANNER_MODEL = "Planner-Qwen3-4B-LoRA"
BALANCED_PLANNER_MODEL = "Planner-Qwen3-8B-LoRA"
DEFAULT_PLANNER_REVISE_MODEL = "Planner-Revise-Qwen3-8B-LoRA"
DEFAULT_PLANNER_FULL_REVISE_MODEL = "Planner-Full-Revise-Qwen3-8B-LoRA"


def _planner_model_for_profile(profile: str) -> str:
    return BALANCED_PLANNER_MODEL if profile == "answer_8b" else DEFAULT_PLANNER_MODEL


@dataclass(frozen=True, slots=True)
class AgentSettings:
    profile: str
    provider: str
    base_model: str
    research_model: str
    router_model: str
    fact_model: str
    planner_model: str
    planner_revise_model: str
    decomposer_model: str
    evidence_model: str
    adjudicator_model: str
    critique_model: str
    max_plan_refine_loops: int
    max_refine_loops: int
    planner_full_revise_model: str = DEFAULT_PLANNER_FULL_REVISE_MODEL

    @classmethod
    def from_env(cls) -> "AgentSettings":
        profile = os.getenv("MODEL_PROFILE", "all_4b").strip().lower()
        if profile not in SUPPORTED_MODEL_PROFILES:
            profile = "all_4b"
        planning_model = os.getenv("PLANNING_MODEL", DEFAULT_PLANNING_MODEL)
        uses_8b = profile in {"two_phase", "answer_8b"}
        answer_model = DEFAULT_ANSWER_MODEL if uses_8b else planning_model
        planner_model = os.getenv(
            "PLANNER_MODEL",
            _planner_model_for_profile(profile),
        )
        research_model = planner_model if profile == "answer_8b" else planning_model
        return cls(
            profile=profile,
            provider="local",
            base_model=os.getenv("LOCAL_LLM_MODEL", answer_model),
            research_model=os.getenv("AGENT_MODEL", research_model),
            router_model=os.getenv("ROUTER_MODEL", DEFAULT_ROUTER_MODEL),
            fact_model=os.getenv("FACT_MODEL", DEFAULT_FACT_MODEL),
            planner_model=planner_model,
            planner_revise_model=os.getenv(
                "PLANNER_REVISE_MODEL",
                DEFAULT_PLANNER_REVISE_MODEL,
            ),
            planner_full_revise_model=os.getenv(
                "PLANNER_FULL_REVISE_MODEL",
                DEFAULT_PLANNER_FULL_REVISE_MODEL,
            ),
            decomposer_model=os.getenv("DECOMPOSER_MODEL", answer_model),
            evidence_model=os.getenv("EVIDENCE_MODEL", answer_model),
            adjudicator_model=os.getenv("ADJUDICATOR_MODEL", answer_model),
            critique_model=os.getenv("CRITIQUE_MODEL", answer_model),
            max_plan_refine_loops=max(
                0,
                min(2, int(os.getenv("MAX_PLAN_REFINE_LOOPS", "1"))),
            ),
            max_refine_loops=int(os.getenv("MAX_REFINE_LOOPS", "2")),
        )

    @classmethod
    def for_profile(cls, profile: str) -> "AgentSettings":
        normalized = str(profile or "").strip().lower()
        if normalized not in SUPPORTED_MODEL_PROFILES:
            allowed = ", ".join(sorted(SUPPORTED_MODEL_PROFILES))
            raise ValueError(f"Profile không hợp lệ. Chỉ hỗ trợ: {allowed}.")
        planning_model = os.getenv("PLANNING_MODEL", DEFAULT_PLANNING_MODEL)
        answer_model = os.getenv("ANSWER_MODEL", DEFAULT_ANSWER_MODEL)
        uses_8b = normalized in {"answer_8b", "two_phase"}
        planner_model = (
            os.getenv("PLANNER_8B_MODEL", BALANCED_PLANNER_MODEL)
            if normalized == "answer_8b"
            else os.getenv("PLANNER_4B_MODEL", DEFAULT_PLANNER_MODEL)
        )
        return cls(
            profile=normalized,
            provider="local",
            base_model=answer_model if uses_8b else planning_model,
            research_model=planner_model if normalized == "answer_8b" else planning_model,
            router_model=os.getenv("ROUTER_MODEL", DEFAULT_ROUTER_MODEL),
            fact_model=os.getenv("FACT_MODEL", DEFAULT_FACT_MODEL),
            planner_model=planner_model,
            planner_revise_model=os.getenv(
                "PLANNER_REVISE_MODEL",
                DEFAULT_PLANNER_REVISE_MODEL,
            ),
            planner_full_revise_model=os.getenv(
                "PLANNER_FULL_REVISE_MODEL",
                DEFAULT_PLANNER_FULL_REVISE_MODEL,
            ),
            decomposer_model=answer_model if uses_8b else planning_model,
            evidence_model=answer_model if uses_8b else planning_model,
            adjudicator_model=answer_model if uses_8b else planning_model,
            critique_model=answer_model if uses_8b else planning_model,
            max_plan_refine_loops=max(
                0,
                min(2, int(os.getenv("MAX_PLAN_REFINE_LOOPS", "1"))),
            ),
            max_refine_loops=int(os.getenv("MAX_REFINE_LOOPS", "2")),
        )


_default_settings = AgentSettings.from_env()
_active_settings: ContextVar[AgentSettings | None] = ContextVar(
    "active_agent_settings",
    default=None,
)


def get_active_settings() -> AgentSettings:
    return _active_settings.get() or _default_settings


@contextmanager
def use_model_profile(profile: str) -> Iterator[AgentSettings]:
    settings = AgentSettings.for_profile(profile)
    token = _active_settings.set(settings)
    try:
        yield settings
    finally:
        _active_settings.reset(token)


class _SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_active_settings(), name)


SETTINGS = _SettingsProxy()
