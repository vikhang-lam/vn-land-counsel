"""Planner Audit: kiểm tra planned coverage, không phán quyết Evidence coverage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.json_contracts import reject_duplicate_object_keys
from core.llm import LocalLLMClient

from .prompts import (
    PLANNER_AUDIT_JSON_SCHEMA,
    PLANNER_AUDIT_RETRY_INSTRUCTION,
    PLANNER_AUDIT_SPEC,
    PLANNER_REPAIR_DIRECTIVE_JSON_SCHEMA,
    PLANNER_REPAIR_DIRECTIVE_SPEC,
)


@dataclass(frozen=True, slots=True)
class PlannerRepairDirective:
    issue_id: str
    requirement_ids: tuple[str, ...]
    problem: str
    required_questions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "requirement_ids": list(self.requirement_ids),
            "problem": self.problem,
            "required_questions": list(self.required_questions),
        }


@dataclass(frozen=True, slots=True)
class PlannerAuditResult:
    decision: str
    uncovered_requests: tuple[str, ...] = ()
    misdirected_issue_ids: tuple[str, ...] = ()
    unsearchable_requirement_ids: tuple[str, ...] = ()
    repair_directives: tuple[PlannerRepairDirective, ...] = ()
    errors: tuple[str, ...] = ()
    raw_output: str = ""
    valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "uncovered_requests": list(self.uncovered_requests),
            "misdirected_issue_ids": list(self.misdirected_issue_ids),
            "unsearchable_requirement_ids": list(self.unsearchable_requirement_ids),
            "repair_directives": [
                directive.to_dict() for directive in self.repair_directives
            ],
            "errors": list(self.errors),
        }


def _parse_audit(raw: str) -> dict[str, Any]:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(raw or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        value = json.loads(cleaned, object_pairs_hook=reject_duplicate_object_keys)
    except (json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def validate_planner_audit(
    raw: str,
    plan: dict[str, Any],
) -> PlannerAuditResult:
    payload = _parse_audit(raw)
    required_keys = {
        "decision",
        "uncovered_requests",
        "misdirected_issue_ids",
        "unsearchable_requirement_ids",
        "errors",
    }
    if set(payload) != required_keys:
        return PlannerAuditResult(
            decision="UNAVAILABLE",
            errors=("Planner Audit sai contract.",),
            raw_output=raw,
            valid=False,
        )
    decision = str(payload.get("decision", "")).strip().upper()
    if decision not in {"PASS", "REVISE"}:
        return PlannerAuditResult(
            decision="UNAVAILABLE",
            errors=("Planner Audit trả decision không hợp lệ.",),
            raw_output=raw,
            valid=False,
        )
    issue_ids = {
        str(issue.get("issue_id", "")).strip().upper()
        for issue in plan.get("issues", [])
        if isinstance(issue, dict)
    }
    requirement_ids = {
        str(requirement.get("requirement_id", "")).strip().upper()
        for issue in plan.get("issues", [])
        if isinstance(issue, dict)
        for requirement in issue.get("required_evidence", [])
        if isinstance(requirement, dict)
    }
    uncovered = tuple(
        str(value).strip()[:240]
        for value in payload.get("uncovered_requests", [])[:4]
        if str(value).strip()
    )
    misdirected = tuple(
        dict.fromkeys(
            str(value).strip().upper()
            for value in payload.get("misdirected_issue_ids", [])[:4]
            if str(value).strip().upper() in issue_ids
        )
    )
    unsearchable = tuple(
        dict.fromkeys(
            str(value).strip().upper()
            for value in payload.get("unsearchable_requirement_ids", [])[:8]
            if str(value).strip().upper() in requirement_ids
        )
    )
    errors = tuple(
        str(value).strip()[:300]
        for value in payload.get("errors", [])[:8]
        if str(value).strip()
    )
    has_gap = bool(uncovered or misdirected or unsearchable or errors)
    normalized_decision = "REVISE" if has_gap else "PASS"
    return PlannerAuditResult(
        decision=normalized_decision,
        uncovered_requests=uncovered,
        misdirected_issue_ids=misdirected,
        unsearchable_requirement_ids=unsearchable,
        errors=errors,
        raw_output=raw,
        valid=True,
    )


def validate_planner_repair_directives(
    raw: str,
    plan: dict[str, Any],
) -> tuple[PlannerRepairDirective, ...]:
    payload = _parse_audit(raw)
    if set(payload) != {"repair_directives"}:
        return ()
    issue_ids = {
        str(issue.get("issue_id", "")).strip().upper()
        for issue in plan.get("issues", [])
        if isinstance(issue, dict)
    }
    requirements_by_issue = {
        str(issue.get("issue_id", "")).strip().upper(): {
            str(requirement.get("requirement_id", "")).strip().upper()
            for requirement in issue.get("required_evidence", [])
            if isinstance(requirement, dict)
        }
        for issue in plan.get("issues", [])
        if isinstance(issue, dict)
    }
    directives: list[PlannerRepairDirective] = []
    seen_directive_issues: set[str] = set()
    for value in payload.get("repair_directives", [])[:4]:
        if not isinstance(value, dict):
            continue
        issue_id = str(value.get("issue_id", "")).strip().upper()
        if issue_id not in issue_ids or issue_id in seen_directive_issues:
            continue
        local_requirement_ids = requirements_by_issue.get(issue_id, set())
        affected = tuple(
            dict.fromkeys(
                str(item).strip().upper()
                for item in value.get("requirement_ids", [])[:4]
                if str(item).strip().upper() in local_requirement_ids
            )
        )
        problem = re.sub(r"\s+", " ", str(value.get("problem", ""))).strip()[:300]
        required_questions = tuple(
            dict.fromkeys(
                re.sub(r"\s+", " ", str(item)).strip()[:240]
                for item in value.get("required_questions", [])[:2]
                if str(item).strip()
            )
        )
        if not problem or not required_questions:
            continue
        seen_directive_issues.add(issue_id)
        directives.append(
            PlannerRepairDirective(
                issue_id=issue_id,
                requirement_ids=affected,
                problem=problem,
                required_questions=required_questions,
            )
        )

    return tuple(directives)


class PlannerAuditStage:
    """Gọi audit độc lập và retry contract tối đa một lần."""

    def run(
        self,
        client: LocalLLMClient,
        *,
        question: str,
        facts: list[dict[str, str]],
        plan: dict[str, Any],
        include_repair_directives: bool = False,
    ) -> PlannerAuditResult:
        settings = get_active_settings()
        message = (
            f"CÂU HỎI GỐC:\n{question}\n\n"
            f"FACT LEDGER:\n{json.dumps(facts, ensure_ascii=False)}\n\n"
            f"KẾ HOẠCH CẦN AUDIT:\n{json.dumps(plan, ensure_ascii=False)}"
        )
        response = client.complete(
            message,
            model=settings.adjudicator_model,
            system_prompt=PLANNER_AUDIT_SPEC.text,
            temperature=0.0,
            max_tokens=700,
            json_mode=True,
            json_schema=PLANNER_AUDIT_JSON_SCHEMA,
        )
        debug_dump("PIPELINE :: PLANNER AUDIT :: RAW", response.text)
        result = validate_planner_audit(response.text, plan)
        if result.valid:
            debug_dump("PIPELINE :: PLANNER AUDIT :: VALIDATED", result.to_dict())
            return self._with_repair_directives(
                client,
                message=message,
                plan=plan,
                result=result,
                enabled=include_repair_directives,
            )
        retry = client.complete(
            message
            + "\n\nVALIDATION_ERRORS: AUDIT_OUTPUT_CONTRACT_INVALID\n"
            + PLANNER_AUDIT_RETRY_INSTRUCTION,
            model=settings.adjudicator_model,
            system_prompt=PLANNER_AUDIT_SPEC.text,
            temperature=0.0,
            max_tokens=700,
            json_mode=True,
            json_schema=PLANNER_AUDIT_JSON_SCHEMA,
        )
        debug_dump("PIPELINE :: PLANNER AUDIT :: RETRY RAW", retry.text)
        result = validate_planner_audit(retry.text, plan)
        debug_dump("PIPELINE :: PLANNER AUDIT :: VALIDATED", result.to_dict())
        return self._with_repair_directives(
            client,
            message=message,
            plan=plan,
            result=result,
            enabled=include_repair_directives,
        )

    @staticmethod
    def _with_repair_directives(
        client: LocalLLMClient,
        *,
        message: str,
        plan: dict[str, Any],
        result: PlannerAuditResult,
        enabled: bool,
    ) -> PlannerAuditResult:
        if not enabled or not result.valid or result.decision != "REVISE":
            return result
        settings = get_active_settings()
        directive_message = (
            message
            + "\n\nKẾT QUẢ AUDIT ĐÃ XÁC NHẬN:\n"
            + json.dumps(result.to_dict(), ensure_ascii=False)
        )
        response = client.complete(
            directive_message,
            model=settings.adjudicator_model,
            system_prompt=PLANNER_REPAIR_DIRECTIVE_SPEC.text,
            temperature=0.0,
            max_tokens=800,
            json_mode=True,
            json_schema=PLANNER_REPAIR_DIRECTIVE_JSON_SCHEMA,
        )
        debug_dump(
            "PIPELINE :: PLANNER AUDIT :: REPAIR DIRECTIVES RAW",
            response.text,
        )
        directives = validate_planner_repair_directives(response.text, plan)
        enriched = PlannerAuditResult(
            decision=result.decision,
            uncovered_requests=result.uncovered_requests,
            misdirected_issue_ids=result.misdirected_issue_ids,
            unsearchable_requirement_ids=result.unsearchable_requirement_ids,
            repair_directives=directives,
            errors=result.errors,
            raw_output=result.raw_output,
            valid=result.valid,
        )
        debug_dump(
            "PIPELINE :: PLANNER AUDIT :: WITH REPAIR DIRECTIVES",
            enriched.to_dict(),
        )
        return enriched


__all__ = [
    "PlannerAuditResult",
    "PlannerRepairDirective",
    "PlannerAuditStage",
    "validate_planner_audit",
    "validate_planner_repair_directives",
]
