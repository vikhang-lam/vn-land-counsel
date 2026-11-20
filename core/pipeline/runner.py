"""Thin, branch-lazy orchestrator for the replacement pipeline."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from core.debug_trace import debug_dump
from core.llm import LocalLLMClient

from .contracts import PipelineState, Route

if TYPE_CHECKING:
    from .answer_writer import AnswerWriterStage
    from .answer_control import AnswerControlStage
    from .article_answer import ArticleAnswerStage
    from .article_lookup import ArticleLookupStage
    from .claim_extractor import ClaimExtractorStage
    from .claim_verifier import ClaimVerifierStage
    from .condition_extractor import ConditionExtractorStage
    from .condition_matcher import ConditionMatcherStage
    from .evidence_selector import EvidenceSelectorStage
    from .fact_extractor import FactExtractorStage
    from .front_desk import IntakeResponseStage, OutOfScopeResponseStage
    from .planner import PlannerStage
    from .publication import PublicationStage
    from .retrieval import RetrievalStage
    from .router import RouterStage
    from .simple_fast import SimpleFastStage
    from .incremental_recovery import IncrementalRecoveryStage


class PipelineExecutionError(RuntimeError):
    def __init__(self, stage: str, detail: str) -> None:
        self.stage = str(stage or "pipeline")
        self.detail = str(detail or "")
        super().__init__(f"{self.stage}: {self.detail}")


class Pipeline:
    """Load only the stages required by the chosen Router branch."""

    def __init__(
        self,
        *,
        router: RouterStage | None = None,
        intake_response: IntakeResponseStage | None = None,
        out_of_scope_response: OutOfScopeResponseStage | None = None,
        article_lookup: ArticleLookupStage | None = None,
        article_answer: ArticleAnswerStage | None = None,
        simple_fast: SimpleFastStage | None = None,
        fact_extractor: FactExtractorStage | None = None,
        planner: PlannerStage | None = None,
        retrieval: RetrievalStage | None = None,
        evidence_selector: EvidenceSelectorStage | None = None,
        claim_extractor: ClaimExtractorStage | None = None,
        claim_verifier: ClaimVerifierStage | None = None,
        condition_extractor: ConditionExtractorStage | None = None,
        condition_matcher: ConditionMatcherStage | None = None,
        answer_writer: AnswerWriterStage | None = None,
        answer_control: AnswerControlStage | None = None,
        incremental_recovery: IncrementalRecoveryStage | None = None,
        publication: PublicationStage | None = None,
    ) -> None:
        self._router = router
        self._intake_response = intake_response
        self._out_of_scope_response = out_of_scope_response
        self._article_lookup = article_lookup
        self._article_answer = article_answer
        self._simple_fast = simple_fast
        self._fact_extractor = fact_extractor
        self._planner = planner
        self._retrieval = retrieval
        self._evidence_selector = evidence_selector
        self._claim_extractor = claim_extractor
        self._claim_verifier = claim_verifier
        self._condition_extractor = condition_extractor
        self._condition_matcher = condition_matcher
        self._answer_writer = answer_writer
        self._answer_control = answer_control
        self._incremental_recovery = incremental_recovery
        self._publication = publication

    def _stage(self, field: str, module: str, class_name: str):
        value = getattr(self, field)
        if value is None:
            from importlib import import_module

            value = getattr(
                import_module(f"{__package__}.{module}"),
                class_name,
            )()
            setattr(self, field, value)
        return value

    @staticmethod
    def _remember_stage(state: PipelineState, stage: str, value: Any) -> None:
        state.diagnostics.setdefault("completed_stages", []).append(stage)
        state.diagnostics.setdefault("stage_types", {})[stage] = type(value).__name__
        metrics = {}
        for field in (
            "latency_seconds",
            "writer_calls",
            "summary_calls",
            "source_count",
            "unit_count",
            "grounded_unit_count",
            "coverage",
            "found",
            "writer_failure_reason",
            "writer_raw_output_chars",
            "writer_raw_output_preview",
            "source_gate_calls",
            "source_gate_failure_reason",
        ):
            if hasattr(value, field):
                metric = getattr(value, field)
                metrics[field] = getattr(metric, "value", metric)
        if metrics:
            state.diagnostics.setdefault("stage_metrics", {})[stage] = metrics

    def run(self, client: LocalLLMClient, question: str) -> PipelineState:
        state = PipelineState(question=str(question or "").strip())
        if not state.question:
            raise ValueError("Pipeline không nhận câu hỏi rỗng.")
        try:
            router = self._stage("_router", "router", "RouterStage")
            route_result = router.run(client, state.question)
            state.route = route_result.route
            self._remember_stage(state, "router", route_result)

            if state.route is Route.INTAKE:
                stage = self._stage(
                    "_intake_response", "front_desk", "IntakeResponseStage"
                )
                state.answer = stage.run(client, state.question)
                self._remember_stage(state, "intake_response", state.answer)
                return state
            if state.route is Route.OUT_OF_SCOPE:
                stage = self._stage(
                    "_out_of_scope_response",
                    "front_desk",
                    "OutOfScopeResponseStage",
                )
                state.answer = stage.run(client, state.question)
                self._remember_stage(state, "out_of_scope_response", state.answer)
                return state
            if state.route is Route.ARTICLE:
                lookup_stage = self._stage(
                    "_article_lookup", "article_lookup", "ArticleLookupStage"
                )
                lookup = lookup_stage.run(state.question)
                state.retrieved_contexts = [
                    f"[NGUỒN: {source.citation}]\n{source.text}"
                    for source in getattr(lookup, "sources", ())
                    if str(getattr(source, "text", "")).strip()
                ]
                self._remember_stage(state, "article_lookup", lookup)
                answer_stage = self._stage(
                    "_article_answer", "article_answer", "ArticleAnswerStage"
                )
                article_answer = answer_stage.run(client, state.question, lookup)
                state.answer = article_answer.text
                self._remember_stage(state, "article_answer", article_answer)
                return state
            if state.route is Route.SIMPLE:
                stage = self._stage("_simple_fast", "simple_fast", "SimpleFastStage")
                result = stage.run(client, state.question)
                state.answer = result.text
                state.retrieved_contexts = list(
                    getattr(result, "source_texts", ())
                )
                self._remember_stage(state, "simple_fast", result)
                return state

            fact_stage = self._stage(
                "_fact_extractor", "fact_extractor", "FactExtractorStage"
            )
            fact_result = fact_stage.run(client, state.question)
            state.facts = list(fact_result.facts)
            self._remember_stage(state, "fact_extractor", fact_result)

            planner = self._stage("_planner", "planner", "PlannerStage")
            # Planner uses the Fact view from its SFT contract, including the
            # REQUEST record. Downstream stages only receive material Facts.
            planner_facts = list(
                getattr(fact_result, "planner_facts", ()) or state.facts
            )
            state.planning = planner.run(client, state.question, planner_facts)
            if getattr(state.planning, "temporal_payload", {}).get(
                "planner_semantic_audit_unresolved"
            ):
                state.diagnostics.setdefault("degraded_stages", []).append(
                    {
                        "stage": "planner",
                        "reason": "SEMANTIC_AUDIT_UNRESOLVED",
                    }
                )
            self._remember_stage(state, "planner", state.planning)

            retrieval = self._stage("_retrieval", "retrieval", "RetrievalStage")
            state.retrieval = retrieval.run(
                client, state.question, state.facts, state.planning
            )
            self._remember_stage(state, "retrieval", state.retrieval)

            evidence_stage = self._stage(
                "_evidence_selector", "evidence_selector", "EvidenceSelectorStage"
            )
            state.evidence_selection = evidence_stage.run(
                client, state.planning, state.retrieval
            )
            state.retrieved_contexts = list(
                dict.fromkeys(
                    context.raw_text
                    for context in getattr(
                        state.evidence_selection,
                        "selected_contexts",
                        (),
                    )
                    if str(getattr(context, "raw_text", "")).strip()
                )
            )
            self._remember_stage(state, "evidence_selector", state.evidence_selection)

            claim_stage = self._stage(
                "_claim_extractor", "claim_extractor", "ClaimExtractorStage"
            )
            state.claim_extraction = claim_stage.run(
                client, state.planning, state.evidence_selection
            )
            self._remember_stage(state, "claim_extractor", state.claim_extraction)

            verifier = self._stage(
                "_claim_verifier", "claim_verifier", "ClaimVerifierStage"
            )
            state.claim_verification = verifier.run(
                client,
                question=state.question,
                planning=state.planning,
                evidence=state.evidence_selection,
                claims=state.claim_extraction,
            )
            self._remember_stage(state, "claim_verifier", state.claim_verification)

            condition_extractor = self._stage(
                "_condition_extractor",
                "condition_extractor",
                "ConditionExtractorStage",
            )
            extracted_conditions = condition_extractor.run(
                client, state.claim_verification, state.evidence_selection
            )
            self._remember_stage(state, "condition_extractor", extracted_conditions)

            matcher = self._stage(
                "_condition_matcher", "condition_matcher", "ConditionMatcherStage"
            )
            state.condition_application = matcher.run(
                client,
                facts=state.facts,
                verification=state.claim_verification,
                extraction=extracted_conditions,
            )
            self._remember_stage(state, "condition_matcher", state.condition_application)

            # Mọi truy xuất bổ sung phải hoàn tất trước khi tạo câu trả lời.
            # Recovery chỉ commit bản ghi mới; bản ghi đã duyệt được giữ nguyên.
            from .incremental_recovery import incremental_recovery_enabled
            if incremental_recovery_enabled():
                recovery = self._stage(
                    "_incremental_recovery",
                    "incremental_recovery",
                    "IncrementalRecoveryStage",
                )
                recovered = recovery.run(
                    client,
                    question=state.question,
                    facts=state.facts,
                    planning=state.planning,
                    retrieval=state.retrieval,
                    evidence=state.evidence_selection,
                    claims=state.claim_extraction,
                    verification=state.claim_verification,
                    application=state.condition_application,
                )
                state.retrieval = recovered.retrieval
                state.evidence_selection = recovered.evidence
                state.claim_extraction = recovered.claims
                state.claim_verification = recovered.verification
                state.condition_application = recovered.application
                state.retrieved_contexts = list(dict.fromkeys(
                    context.raw_text
                    for context in state.evidence_selection.selected_contexts
                    if str(context.raw_text).strip()
                ))
                state.diagnostics["incremental_recovery"] = {
                    "attempted_requirement_ids": list(
                        recovered.attempted_requirement_ids
                    ),
                    "committed_requirement_ids": list(
                        recovered.committed_requirement_ids
                    ),
                    "skipped": list(recovered.skipped),
                    "append_only": True,
                }
                self._remember_stage(
                    state, "incremental_recovery", recovered
                )

            from core.answer_mode import response_mode_for_question
            response_mode = response_mode_for_question(
                state.question,
                route=state.route.value,
            )

            writer = self._stage("_answer_writer", "answer_writer", "AnswerWriterStage")
            state.answer_draft = writer.run(
                client,
                facts=state.facts,
                application=state.condition_application,
                question=state.question,
                planning=state.planning,
                response_mode=response_mode,
            )
            self._remember_stage(state, "answer_writer", state.answer_draft)

            # Từ đây trở đi không còn quyền gọi Retrieval. Bộ kiểm soát chỉ có
            # thể giữ, sửa ba trường văn bản hoặc loại từng Answer Unit.
            from .answer_control import answer_control_enabled
            if answer_control_enabled():
                control = self._stage(
                    "_answer_control", "answer_control", "AnswerControlStage"
                )
                controlled = control.run(
                    client,
                    question=state.question,
                    facts=state.facts,
                    planning=state.planning,
                    application=state.condition_application,
                    draft=state.answer_draft,
                    response_mode=response_mode,
                )
                state.answer_draft = controlled.draft
                state.diagnostics["answer_control"] = {
                    "kept_unit_ids": list(controlled.kept_unit_ids),
                    "revised_unit_ids": list(controlled.revised_unit_ids),
                    "dropped_unit_ids": list(controlled.dropped_unit_ids),
                    "audit_failed_unit_ids": list(
                        controlled.audit_failed_unit_ids
                    ),
                    "retrieval_allowed": False,
                }
                self._remember_stage(state, "answer_control", controlled)

            publication = self._stage(
                "_publication", "publication", "PublicationStage"
            )
            state.publication = publication.run(
                state.answer_draft,
                response_mode=response_mode,
                issue_titles={
                    issue.issue_id: issue.display_text
                    for issue in getattr(state.planning, "issues", ())
                    if str(getattr(issue, "issue_id", "")).strip()
                },
                unresolved_issue_titles={
                    issue.issue_id: issue.display_text
                    for issue in getattr(state.planning, "issues", ())
                    if issue.issue_id
                    not in {
                        record.verification.claim.issue_id
                        for record in getattr(
                            state.condition_application,
                            "publishable_records",
                            (),
                        )
                    }
                },
            )
            state.answer = state.publication.text
            self._remember_stage(state, "publication", state.publication)
            debug_dump(
                "PIPELINE :: FINAL PUBLICATION",
                {
                    "status": state.publication.status.value,
                    "published_unit_ids": list(state.publication.published_unit_ids),
                    "published_evidence_ids": list(state.publication.published_evidence_ids),
                    "omitted_claim_ids": list(state.publication.omitted_claim_ids),
                    "answer": state.answer,
                    "diagnostics": state.diagnostics,
                },
            )
            return state
        except PipelineExecutionError:
            raise
        except Exception as error:
            completed = state.diagnostics.get("completed_stages", [])
            raise PipelineExecutionError(
                self._next_stage_name(completed, state.route),
                str(error),
            ) from error

    def run_intake(self, client: LocalLLMClient, question: str) -> PipelineState:
        return self.run(client, question)

    @staticmethod
    def _next_stage_name(completed: list[str], route: Route | None) -> str:
        branch_order = {
            Route.INTAKE: ("router", "intake_response"),
            Route.OUT_OF_SCOPE: ("router", "out_of_scope_response"),
            Route.ARTICLE: ("router", "article_lookup", "article_answer"),
            Route.SIMPLE: ("router", "simple_fast"),
            Route.COMPLEX: (
                "router",
                "fact_extractor",
                "planner",
                "retrieval",
                "evidence_selector",
                "claim_extractor",
                "claim_verifier",
                "condition_extractor",
                "condition_matcher",
                "answer_writer",
                "publication",
            ),
        }
        order = branch_order.get(route, ("router",))
        if route is Route.COMPLEX:
            from .incremental_recovery import incremental_recovery_enabled
            from .answer_control import answer_control_enabled
            values = list(order)
            if incremental_recovery_enabled():
                values.insert(values.index("answer_writer"), "incremental_recovery")
            if answer_control_enabled():
                values.insert(values.index("publication"), "answer_control")
            order = tuple(values)
        completed_set = set(completed)
        return next((stage for stage in order if stage not in completed_set), "pipeline")


__all__ = ["PipelineExecutionError", "Pipeline"]
