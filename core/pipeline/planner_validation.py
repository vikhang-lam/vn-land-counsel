"""Validator cấu trúc cho kế hoạch, không chứa policy pháp lý theo lĩnh vực."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from core.decomposition import VALID_EVIDENCE_TARGETS, VALID_ISSUE_TYPES, VALID_TIME_BASES
from core.json_contracts import reject_duplicate_object_keys

from .planning_contract import PlanningBudget


def _parse_object(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return deepcopy(raw)
    text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        str(raw or "").strip(),
        flags=re.IGNORECASE,
    )
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_object_keys)
    except (json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _assign_structural_ids(payload: dict[str, Any]) -> dict[str, Any]:
    """Để Python sở hữu ID tuần tự; model chỉ quyết định nội dung kế hoạch.

    Các quan hệ ``depends_on`` được ánh xạ theo ID Issue mà model đã trả. Tham
    chiếu không tồn tại vẫn được giữ nguyên để validator báo lỗi, thay vì âm
    thầm xóa một quan hệ mà model đã tạo.
    """

    normalized = deepcopy(payload)
    issues = normalized.get("issues")
    if not isinstance(issues, list):
        return normalized

    issue_id_map: dict[str, str] = {}
    for position, issue in enumerate(issues, 1):
        if not isinstance(issue, dict):
            continue
        old_issue_id = str(issue.get("issue_id", "")).strip().upper()
        new_issue_id = f"I{position:03d}"
        if old_issue_id and old_issue_id not in issue_id_map:
            issue_id_map[old_issue_id] = new_issue_id
        issue["issue_id"] = new_issue_id

        requirements = issue.get("required_evidence")
        if not isinstance(requirements, list):
            continue
        for requirement_position, requirement in enumerate(requirements, 1):
            if isinstance(requirement, dict):
                requirement["requirement_id"] = (
                    f"R{position:03d}_{requirement_position:02d}"
                )

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        dependencies = issue.get("depends_on")
        if isinstance(dependencies, list):
            issue["depends_on"] = [
                issue_id_map.get(str(value).strip().upper(), str(value).strip().upper())
                for value in dependencies
            ]
    return normalized


def validate_planner_output(
    raw: str | dict[str, Any],
    valid_fact_ids: set[str],
    budget: PlanningBudget | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Kiểm tra contract kỹ thuật, không sửa hoặc suy diễn nội dung kế hoạch."""

    active_budget = budget or PlanningBudget.baseline()
    payload = _assign_structural_ids(_parse_object(raw))
    if set(payload) != {"issues"}:
        return {}, ["Planner phải trả đúng một khóa issues."]
    issues = payload.get("issues")
    if not isinstance(issues, list) or not 1 <= len(issues) <= active_budget.max_issues:
        return {}, [f"Planner cần 1-{active_budget.max_issues} Issue theo runtime budget."]

    errors: list[str] = []
    seen_issue_ids: set[str] = set()
    seen_requirement_ids: set[str] = set()
    seen_issue_texts: set[str] = set()
    total_requirements = 0

    for issue_position, issue in enumerate(issues, 1):
        expected_issue_id = f"I{issue_position:03d}"
        if not isinstance(issue, dict):
            errors.append(f"{expected_issue_id} không phải object.")
            continue
        required_issue_keys = {
            "issue_id",
            "issue",
            "issue_type",
            "required_evidence",
            "depends_on",
            "time_basis",
        }
        if set(issue) != required_issue_keys:
            errors.append(f"{expected_issue_id} sai tập khóa.")
            continue
        issue_id = str(issue.get("issue_id", "")).strip().upper()
        issue_text = re.sub(r"\s+", " ", str(issue.get("issue", ""))).strip()
        if issue_id != expected_issue_id or issue_id in seen_issue_ids:
            errors.append(f"Issue ID phải tuần tự, nhận {issue_id or '<trống>'}.")
        seen_issue_ids.add(issue_id)
        if not issue_text or len(issue_text) > active_budget.max_issue_chars:
            errors.append(
                f"{expected_issue_id} thiếu nội dung hoặc quá "
                f"{active_budget.max_issue_chars} ký tự."
            )
        if issue_text.casefold() in seen_issue_texts:
            errors.append(f"{expected_issue_id} trùng nội dung Issue trước.")
        seen_issue_texts.add(issue_text.casefold())
        if str(issue.get("issue_type", "")).strip().upper() not in VALID_ISSUE_TYPES:
            errors.append(f"{expected_issue_id} có issue_type không hợp lệ.")
        if str(issue.get("time_basis", "")).strip() not in VALID_TIME_BASES:
            errors.append(f"{expected_issue_id} có time_basis không hợp lệ.")

        dependencies = issue.get("depends_on")
        if (
            not isinstance(dependencies, list)
            or len(dependencies) > active_budget.max_dependencies_per_issue
        ):
            errors.append(f"{expected_issue_id} depends_on không hợp lệ.")
        else:
            dependency_ids = [str(value).strip().upper() for value in dependencies]
            if len(dependency_ids) != len(set(dependency_ids)):
                errors.append(f"{expected_issue_id} có dependency trùng.")
            valid_previous = {f"I{index:03d}" for index in range(1, issue_position)}
            if any(value not in valid_previous for value in dependency_ids):
                errors.append(f"{expected_issue_id} chỉ được phụ thuộc Issue đứng trước.")

        requirements = issue.get("required_evidence")
        if (
            not isinstance(requirements, list)
            or not 1
            <= len(requirements)
            <= active_budget.max_requirements_per_issue
        ):
            errors.append(
                f"{expected_issue_id} cần 1-"
                f"{active_budget.max_requirements_per_issue} Requirement theo runtime budget."
            )
            continue
        total_requirements += len(requirements)
        seen_objectives: set[str] = set()
        seen_queries: set[str] = set()
        for requirement_position, requirement in enumerate(requirements, 1):
            expected_requirement_id = f"R{issue_position:03d}_{requirement_position:02d}"
            if not isinstance(requirement, dict):
                errors.append(f"{expected_requirement_id} không phải object.")
                continue
            required_keys = {
                "requirement_id",
                "target_kind",
                "objective",
                "fact_ids",
                "query",
            }
            if set(requirement) != required_keys:
                errors.append(f"{expected_requirement_id} sai tập khóa.")
                continue
            requirement_id = str(requirement.get("requirement_id", "")).strip().upper()
            if requirement_id != expected_requirement_id or requirement_id in seen_requirement_ids:
                errors.append(
                    f"Requirement ID phải tuần tự, nhận {requirement_id or '<trống>'}."
                )
            seen_requirement_ids.add(requirement_id)
            target_kind = str(requirement.get("target_kind", "")).strip().upper()
            if target_kind not in VALID_EVIDENCE_TARGETS:
                errors.append(f"{expected_requirement_id} có target_kind không hợp lệ.")

            objective = re.sub(r"\s+", " ", str(requirement.get("objective", ""))).strip()
            if not objective or len(objective) > active_budget.max_objective_chars:
                errors.append(
                    f"{expected_requirement_id} objective rỗng hoặc quá "
                    f"{active_budget.max_objective_chars} ký tự."
                )
            if objective.casefold() in seen_objectives:
                errors.append(f"{expected_requirement_id} trùng objective.")
            seen_objectives.add(objective.casefold())

            query = re.sub(r"\s+", " ", str(requirement.get("query", ""))).strip()
            if not query or len(query) > active_budget.max_query_chars:
                errors.append(
                    f"{expected_requirement_id} query rỗng hoặc quá "
                    f"{active_budget.max_query_chars} ký tự."
                )
            if query.casefold() in seen_queries:
                errors.append(f"{expected_requirement_id} trùng query trong Issue.")
            seen_queries.add(query.casefold())

            fact_ids = requirement.get("fact_ids")
            if (
                not isinstance(fact_ids, list)
                or not 1
                <= len(fact_ids)
                <= active_budget.max_fact_links_per_requirement
            ):
                errors.append(
                    f"{expected_requirement_id} cần 1-"
                    f"{active_budget.max_fact_links_per_requirement} Fact ID "
                    "theo runtime budget."
                )
            else:
                normalized_fact_ids = [str(value).strip().upper() for value in fact_ids]
                if len(normalized_fact_ids) != len(set(normalized_fact_ids)):
                    errors.append(f"{expected_requirement_id} có Fact ID trùng.")
                for fact_id in normalized_fact_ids:
                    if not re.fullmatch(r"F\d{3}", fact_id) or fact_id not in valid_fact_ids:
                        errors.append(
                            f"{expected_requirement_id} tham chiếu Fact không tồn tại: {fact_id}."
                        )

    if total_requirements > active_budget.max_requirements_total:
        errors.append(
            f"Kế hoạch có {total_requirements} Requirement, vượt giới hạn "
            f"{active_budget.max_requirements_total}."
        )

    return (deepcopy(payload) if not errors else {}), errors


def planner_issue_texts(payload: dict[str, Any]) -> list[str]:
    """Tạo nhãn hiển thị tương thích với stage Retrieval hiện tại."""

    return [
        f"{str(issue.get('issue', '')).strip()} | MỐC: {str(issue.get('time_basis', 'hien_hanh')).strip()}"
        for issue in payload.get("issues", [])
        if isinstance(issue, dict)
    ]


__all__ = ["planner_issue_texts", "validate_planner_output"]
