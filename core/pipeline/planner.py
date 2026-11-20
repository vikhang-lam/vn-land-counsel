"""Stage 3 - lập kế hoạch vấn đề pháp lý và nhu cầu chứng cứ."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.debug_trace import debug_dump
from core.llm import LocalLLMClient

from .contracts import FactRecord, PlanningResult
from .planner_engine import run_planner


PlannerBackend = Callable[
    [LocalLLMClient, str, list[dict[str, str]]],
    tuple[list[str], str],
]


@dataclass(frozen=True, slots=True)
class PlannerDiagnostics:
    issue_count: int
    requirement_count: int
    dependency_count: int


class PlannerStage:
    """Biên contract mới cho Planner.

    Giai đoạn đầu dùng cùng backend với previous để khóa đầu ra. Các vòng audit và
    recovery sẽ được thay dần phía sau biên này; stage sau không cần biết Planner
    được triển khai nội bộ như thế nào.
    """

    def __init__(self, backend: PlannerBackend | None = None) -> None:
        self._backend = backend or run_planner

    def run(
        self,
        client: LocalLLMClient,
        question: str,
        facts: list[FactRecord],
    ) -> PlanningResult:
        query = str(question or "").strip()
        if not query:
            raise ValueError("Planner không nhận câu hỏi rỗng.")
        fact_payloads = [fact.to_dict() for fact in facts]
        issue_texts, temporal_context = self._backend(
            client,
            query,
            fact_payloads,
        )
        result = PlanningResult.from_payload(issue_texts, temporal_context)
        diagnostics = PlannerDiagnostics(
            issue_count=len(result.issues),
            requirement_count=len(result.requirements),
            dependency_count=sum(len(issue.depends_on) for issue in result.issues),
        )
        debug_dump(
            "PIPELINE :: PLANNER :: CONTRACT",
            {
                "issues": result.issue_text_list(),
                "issue_specs": result.issue_spec_payloads(),
                "diagnostics": {
                    "issue_count": diagnostics.issue_count,
                    "requirement_count": diagnostics.requirement_count,
                    "dependency_count": diagnostics.dependency_count,
                },
            },
        )
        return result


__all__ = ["PlannerDiagnostics", "PlannerStage"]
