"""Điều phối Planner với đầu vào tương thích bộ dữ liệu SFT."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from core.agents.transport import (
    pseudonymize_planning_text,
    pseudonymized_planning_facts,
)
from core.config import get_active_settings
from core.debug_trace import debug_dump
from core.decomposition import validate_temporal_context
from core.llm import LocalLLMClient
from core.telemetry import record_retry

from .planner_audit import PlannerAuditResult, PlannerAuditStage
from .planner_full_revise import PlannerFullReviseStage
from .planner_revision_scope import validate_revision_scope
from .planning_contract import PlanningBudget, planner_json_schema
from .prompts import (
    PLANNER_BASELINE_SPEC,
    PLANNER_CANDIDATE_SPEC,
    PLANNER_REPAIR_INSTRUCTION,
    TEMPORAL_EXTRACTOR_JSON_SCHEMA,
    TEMPORAL_EXTRACTOR_SPEC,
    PromptSpec,
)
from .planner_validation import planner_issue_texts, validate_planner_output


@dataclass(frozen=True, slots=True)
class PlannerEngineOutput:
    issue_texts: list[str]
    temporal_context: str
    initial_plan: dict[str, Any]
    final_plan: dict[str, Any]
    audit: PlannerAuditResult
    revised: bool
    used_fallback: bool


class PlannerContractError(RuntimeError):
    """Planner failed its output contract after the bounded retry."""


def _build_sft_aligned_planner_message(
    question: str,
    facts_text: str,
    temporal_context: str,
) -> str:
    """Giữ đúng tên và thứ tự các khối mà Planner đã thấy khi SFT."""

    return (
        f"CAU HOI:\n{question}\n\n"
        f"CASE_FACTS:\n{facts_text}\n\n"
        f"TEMPORAL_CONTEXT:\n{temporal_context}"
    )


class PlannerEngine:
    """Sinh kế hoạch, audit planned coverage và sửa tối đa một lần."""

    def __init__(
        self,
        audit_stage: PlannerAuditStage | None = None,
        *,
        prompt_spec: PromptSpec = PLANNER_BASELINE_SPEC,
        budget: PlanningBudget | None = None,
        structured_repair: bool | None = None,
        revise_stage: PlannerFullReviseStage | None = None,
    ) -> None:
        self.audit_stage = audit_stage or PlannerAuditStage()
        self.revise_stage = revise_stage or PlannerFullReviseStage()
        self.prompt_spec = prompt_spec
        self.budget = budget or PlanningBudget.baseline()
        self.structured_repair = (
            structured_repair
            if structured_repair is not None
            else os.getenv(
                "PLANNER_STRUCTURED_REPAIR_ENABLED", "false"
            ).strip().casefold()
            in {"1", "true", "yes", "on"}
        )

    def run(
        self,
        client: LocalLLMClient,
        question: str,
        facts: list[dict[str, str]],
    ) -> PlannerEngineOutput:
        settings = get_active_settings()
        self.prompt_spec.assert_sft_alignment()
        valid_fact_ids = {
            str(fact.get("fact_id", "")).strip().upper()
            for fact in facts
            if str(fact.get("fact_id", "")).strip()
            and str(fact.get("category", "")).strip().upper() != "REQUEST"
        }
        anonymized_question = pseudonymize_planning_text(question, facts)
        anonymized_facts = [
            fact
            for fact in pseudonymized_planning_facts(facts)
            if str(fact.get("value", "")).strip()
            and str(fact.get("source_quote", "")).strip()
            and str(fact.get("category", "")).strip().upper() != "REQUEST"
        ]
        facts_text = "\n".join(
            f"- {fact['fact_id']} [{fact['category']}]: {fact['value']}"
            for fact in anonymized_facts
        ) or "NONE"

        temporal_response = client.complete(
            question,
            model=settings.decomposer_model,
            system_prompt=TEMPORAL_EXTRACTOR_SPEC.text,
            temperature=0.0,
            max_tokens=240,
            json_mode=True,
            json_schema=TEMPORAL_EXTRACTOR_JSON_SCHEMA,
        )
        temporal_context = validate_temporal_context(
            temporal_response.text,
            question,
        )
        # Không chèn Request Anchor vào lần lập kế hoạch đầu tiên. Adapter
        # Planner được SFT với đúng ba khối dưới đây; thêm một khối ưu tiên ở
        # phía trước sẽ làm thay đổi hợp đồng đầu vào dù system prompt còn nguyên.
        planner_message = _build_sft_aligned_planner_message(
            anonymized_question,
            facts_text,
            temporal_context,
        )
        output_schema = planner_json_schema(self.budget)
        response = client.complete(
            planner_message,
            model=settings.planner_model,
            system_prompt=self.prompt_spec.text,
            temperature=0.0,
            max_tokens=1200,
            json_mode=True,
            json_schema=output_schema,
        )
        debug_dump("PIPELINE :: PLANNER :: RAW", response.text)
        initial_plan, contract_errors = validate_planner_output(
            response.text,
            valid_fact_ids,
            self.budget,
        )
        if contract_errors:
            debug_dump("PIPELINE :: PLANNER :: CONTRACT ERRORS", contract_errors)
        used_fallback = False
        if not initial_plan:
            record_retry(
                "Pipeline Planner contract recovery",
                stage_name="Planner",
            )
            retry = client.complete(
                planner_message
                + "\n\nKẾT QUẢ TRƯỚC SAI CONTRACT:\n- "
                + "\n- ".join(contract_errors)
                + "\n\n"
                + PLANNER_REPAIR_INSTRUCTION,
                model=settings.planner_model,
                system_prompt=self.prompt_spec.text,
                temperature=0.0,
                max_tokens=1200,
                json_mode=True,
                json_schema=output_schema,
            )
            initial_plan, contract_errors = validate_planner_output(
                retry.text,
                valid_fact_ids,
                self.budget,
            )
            debug_dump("PIPELINE :: PLANNER :: RETRY RAW", retry.text)
            if contract_errors:
                debug_dump(
                    "PIPELINE :: PLANNER :: RETRY CONTRACT ERRORS",
                    contract_errors,
                )
        if not initial_plan:
            raise PlannerContractError(
                "Planner không trả kế hoạch hợp lệ sau một lần sửa contract: "
                + "; ".join(contract_errors[:6])
            )

        audit = self.audit_stage.run(
            client,
            question=anonymized_question,
            facts=anonymized_facts,
            plan=initial_plan,
            include_repair_directives=self.structured_repair,
        )
        final_plan = initial_plan
        revised = False
        revision_errors: list[str] = []
        if audit.valid and audit.decision == "REVISE" and settings.max_plan_refine_loops > 0:
            used_fallback = True
            record_retry(
                "Clean Planner full-plan revision",
                stage_name="Planner Audit",
            )
            revision = self.revise_stage.run(
                client,
                question=anonymized_question,
                facts=anonymized_facts,
                temporal_context=temporal_context,
                plan=initial_plan,
                audit=audit,
                budget=self.budget,
            )
            raw_revision = revision.raw_output
            merged_plan = raw_revision
            candidate, repair_errors = validate_planner_output(
                merged_plan,
                valid_fact_ids,
                self.budget,
            )
            if candidate:
                scope_errors = validate_revision_scope(initial_plan, candidate, audit)
                if scope_errors:
                    repair_errors.extend(scope_errors)
                    candidate = {}
            revision_errors = repair_errors
            debug_dump(
                "CLEAN :: PLANNER REVISE :: RAW",
                raw_revision,
            )
            debug_dump(
                "CLEAN :: PLANNER REVISE :: CANDIDATE",
                merged_plan,
            )
            if candidate:
                final_plan = candidate
                revised = candidate != initial_plan
                audit = self.audit_stage.run(
                    client,
                    question=anonymized_question,
                    facts=anonymized_facts,
                    plan=final_plan,
                    include_repair_directives=False,
                )
            else:
                debug_dump(
                    "PIPELINE :: PLANNER REPAIR :: REJECTED",
                    {"errors": repair_errors},
                )

        # Audit chưa đạt sau một lần sửa không được xóa toàn bộ Fact Ledger và
        # làm pipeline dừng. Giữ candidate đã qua schema/ID validation, đánh
        # dấu degraded để retrieval/evidence gates tiếp tục kiểm soát ngữ nghĩa.
        # Không thực hiện thêm vòng sửa để tránh loop và phình latency.
        unresolved_semantic_audit = bool(
            audit.valid and audit.decision == "REVISE"
        )

        temporal_payload = json.loads(temporal_context)
        temporal_payload["issue_specs"] = final_plan["issues"]
        temporal_payload["planner_audit"] = audit.to_dict()
        temporal_payload["planner_revised"] = revised
        temporal_payload["planner_safe_fallback"] = used_fallback
        temporal_payload["planner_revision_errors"] = revision_errors
        temporal_payload["planner_semantic_audit_unresolved"] = (
            unresolved_semantic_audit
        )
        final_temporal_context = json.dumps(temporal_payload, ensure_ascii=False)
        issue_texts = planner_issue_texts(final_plan)
        debug_dump(
            "PIPELINE :: PLANNER ENGINE :: FINAL",
            {
                "issues": issue_texts,
                "plan": final_plan,
                "audit": audit.to_dict(),
                "revised": revised,
                "used_fallback": used_fallback,
            },
        )
        return PlannerEngineOutput(
            issue_texts=issue_texts,
            temporal_context=final_temporal_context,
            initial_plan=initial_plan,
            final_plan=final_plan,
            audit=audit,
            revised=revised,
            used_fallback=used_fallback,
        )


def run_planner(
    client: LocalLLMClient,
    question: str,
    facts: list[dict[str, str]],
) -> tuple[list[str], str]:
    """Adapter đúng chữ ký backend mà PlannerStage đang sử dụng."""

    contract_variant = os.getenv(
        "PLANNER_CONTRACT_VARIANT", "baseline"
    ).strip().casefold()
    if contract_variant == "candidate_3000":
        engine = PlannerEngine(
            prompt_spec=PLANNER_CANDIDATE_SPEC,
            budget=PlanningBudget.candidate(),
        )
    else:
        engine = PlannerEngine()
    output = engine.run(client, question, facts)
    return output.issue_texts, output.temporal_context


__all__ = [
    "PlannerContractError",
    "PlannerEngineOutput",
    "PlannerEngine",
    "run_planner",
]
