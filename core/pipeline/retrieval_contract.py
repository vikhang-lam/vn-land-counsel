"""Operational limits for requirement-scoped retrieval.

Values are centralized so experiments can vary them without changing prompts
or semantic stage code.  The baseline values reproduce the currently selected
20-candidate/5-reranked configuration; they are not claimed to be optimal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class RetrievalBudget:
    candidate_k: int
    rerank_k: int
    max_actions_per_requirement: int
    max_cross_references_per_requirement: int
    max_query_chars: int

    @classmethod
    def baseline(cls) -> "RetrievalBudget":
        return cls(
            candidate_k=20,
            rerank_k=5,
            max_actions_per_requirement=2,
            max_cross_references_per_requirement=2,
            max_query_chars=300,
        )

    def validate(self) -> None:
        if self.candidate_k < 1:
            raise ValueError("candidate_k phải dương")
        if not 1 <= self.rerank_k <= self.candidate_k:
            raise ValueError("rerank_k phải nằm trong [1, candidate_k]")
        if self.max_actions_per_requirement < 1:
            raise ValueError("max_actions_per_requirement phải dương")
        if self.max_cross_references_per_requirement < 0:
            raise ValueError("max_cross_references_per_requirement không được âm")
        if self.max_query_chars < 1:
            raise ValueError("max_query_chars phải dương")

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


__all__ = ["RetrievalBudget"]
