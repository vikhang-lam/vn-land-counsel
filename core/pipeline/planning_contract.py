"""Operational contract for legal research planning.

Budgets control latency and context size.  They are request/runtime settings,
not legal rules and therefore do not belong in the semantic system prompt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from core.decomposition import (
    VALID_EVIDENCE_TARGETS,
    VALID_ISSUE_TYPES,
    VALID_TIME_BASES,
)


@dataclass(frozen=True, slots=True)
class PlanningBudget:
    max_issues: int
    max_requirements_per_issue: int
    max_fact_links_per_requirement: int
    max_dependencies_per_issue: int
    max_issue_chars: int
    max_objective_chars: int
    max_query_chars: int
    max_requirements_total: int = 6

    @classmethod
    def baseline(cls) -> "PlanningBudget":
        """Limits used by the currently deployed Planner adapter."""

        return cls(
            max_issues=3,
            max_requirements_per_issue=2,
            max_fact_links_per_requirement=6,
            max_dependencies_per_issue=2,
            max_issue_chars=240,
            max_objective_chars=240,
            max_query_chars=220,
            max_requirements_total=6,
        )

    @classmethod
    def candidate(cls) -> "PlanningBudget":
        """Limits used by the Planner trained on the 3,000-record dataset."""

        return cls(
            max_issues=5,
            max_requirements_per_issue=5,
            max_fact_links_per_requirement=6,
            max_dependencies_per_issue=4,
            max_issue_chars=240,
            max_objective_chars=240,
            max_query_chars=220,
            max_requirements_total=16,
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def planner_json_schema(budget: PlanningBudget) -> dict:
    """Build the output schema from the runtime budget."""

    requirement_schema = {
        "type": "object",
        "properties": {
            # Model IDs are accepted for transport compatibility; Python
            # replaces them with canonical sequential IDs after parsing.
            "requirement_id": {"type": "string", "minLength": 1, "maxLength": 32},
            "target_kind": {
                "type": "string",
                "enum": sorted(VALID_EVIDENCE_TARGETS),
            },
            "objective": {
                "type": "string",
                "minLength": 1,
                "maxLength": budget.max_objective_chars,
            },
            "fact_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": budget.max_fact_links_per_requirement,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^F[0-9]{3}$"},
            },
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": budget.max_query_chars,
            },
        },
        "required": [
            "requirement_id",
            "target_kind",
            "objective",
            "fact_ids",
            "query",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "issues": {
                "type": "array",
                "minItems": 1,
                "maxItems": budget.max_issues,
                "items": {
                    "type": "object",
                    "properties": {
                        "issue_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 32,
                        },
                        "issue": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": budget.max_issue_chars,
                        },
                        "issue_type": {
                            "type": "string",
                            "enum": sorted(VALID_ISSUE_TYPES),
                        },
                        "required_evidence": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": budget.max_requirements_per_issue,
                            "items": requirement_schema,
                        },
                        "depends_on": {
                            "type": "array",
                            "maxItems": budget.max_dependencies_per_issue,
                            "uniqueItems": True,
                            "items": {"type": "string", "maxLength": 32},
                        },
                        "time_basis": {
                            "type": "string",
                            "enum": sorted(VALID_TIME_BASES),
                        },
                    },
                    "required": [
                        "issue_id",
                        "issue",
                        "issue_type",
                        "required_evidence",
                        "depends_on",
                        "time_basis",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["issues"],
        "additionalProperties": False,
    }


__all__ = ["PlanningBudget", "planner_json_schema"]
