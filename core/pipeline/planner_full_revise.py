"""Sửa toàn bộ kế hoạch bằng adapter đã SFT; không ghép Issue theo ID cũ."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from core.config import get_active_settings
from core.debug_trace import debug_dump
from .planner_audit import PlannerAuditResult
from .planning_contract import PlanningBudget, planner_json_schema
from .prompts import PLANNER_FULL_REVISE_SPEC


def full_revise_message(*, question, facts, temporal_context, plan, audit):
    """Giữ nguyên thứ tự và tên các khối đầu vào đã dùng trong dataset SFT."""
    return (
        "CÂU HỎI ĐẦY ĐỦ:\n" + question
        + "\n\nFACT LEDGER:\n" + json.dumps(facts, ensure_ascii=False)
        + "\n\nTEMPORAL CONTEXT:\n" + temporal_context
        + "\n\nKẾ HOẠCH BAN ĐẦU:\n" + json.dumps(plan, ensure_ascii=False)
        + "\n\nPLANNER AUDIT:\n" + json.dumps(audit, ensure_ascii=False)
    )


@dataclass(frozen=True, slots=True)
class PlannerFullReviseResult:
    raw_output: str


class PlannerFullReviseStage:
    def run(self, client, *, question: str, facts: list[dict[str, Any]],
            temporal_context: str, plan: dict[str, Any], audit: PlannerAuditResult,
            budget: PlanningBudget) -> PlannerFullReviseResult:
        PLANNER_FULL_REVISE_SPEC.assert_sft_alignment()
        settings = get_active_settings()
        valid_ids = sorted({str(f.get('fact_id', '')).strip().upper() for f in facts
            if f.get('fact_id') and str(f.get('category', '')).upper() != 'REQUEST'})
        if not valid_ids:
            return PlannerFullReviseResult('')
        schema = planner_json_schema(budget)
        fact_schema = schema['properties']['issues']['items']['properties']['required_evidence']['items']['properties']['fact_ids']
        # REQUEST có trong ngữ cảnh nhưng không phải Fact được phép viện dẫn.
        fact_schema['items'] = {'type': 'string', 'enum': valid_ids}
        message = full_revise_message(question=question, facts=facts,
            temporal_context=temporal_context, plan=plan, audit=audit.to_dict())
        call_args = dict(system_prompt=PLANNER_FULL_REVISE_SPEC.text, temperature=0.0,
            max_tokens=2048, json_mode=True, json_schema=schema)
        try:
            response = client.complete(message, model=settings.planner_full_revise_model, **call_args)
        except Exception as error:
            debug_dump('CLEAN :: PLANNER FULL REVISE :: MODEL ERROR', {'error': str(error)})
            if settings.planner_full_revise_model == settings.adjudicator_model:
                return PlannerFullReviseResult('')
            try:
                response = client.complete(message, model=settings.adjudicator_model, **call_args)
            except Exception as fallback_error:
                debug_dump('CLEAN :: PLANNER FULL REVISE :: FALLBACK ERROR', {'error': str(fallback_error)})
                return PlannerFullReviseResult('')
        return PlannerFullReviseResult(str(response.text or ''))
