"""Lazy public facade for the replacement pipeline.

Importing the package must not load embedding, reranker or COMPLEX stages.
Each public symbol is resolved only when its owning branch is actually used.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {}


def _export(module: str, *names: str) -> None:
    for name in names:
        _EXPORTS[name] = (module, name)


_export(
    "contracts",
    "FactRecord",
    "IssueRecord",
    "IssueRetrievalResult",
    "PipelineState",
    "PlanningResult",
    "RequirementRecord",
    "RetrievalActionRecord",
    "RetrievalResult",
    "RetrievedContextRecord",
    "Route",
)
_export("claim_contract", "ClaimExtractionFailure", "ClaimExtractionResult", "ClaimRecord")
_export("claim_extractor", "ClaimExtractionBudget", "ClaimExtractorStage")
_export("claim_verifier", "ClaimVerificationBudget", "ClaimVerifierStage")
_export(
    "condition_contract",
    "ApplicationStatus",
    "ClaimApplicationRecord",
    "ConditionApplicationResult",
    "ConditionExtractionFailure",
    "ConditionExtractionResult",
    "ConditionLogic",
    "ConditionMatchRecord",
    "ConditionMatchStatus",
    "ConditionRecord",
    "ConditionRole",
)
_export("condition_extractor", "ConditionExtractionBudget", "ConditionExtractorStage")
_export("condition_matcher", "ConditionMatcherStage")
_export(
    "answer_contract",
    "AnswerDraftResult",
    "AnswerPurpose",
    "AnswerUnit",
    "AnswerUnitFailure",
    "PublicationStatus",
    "PublishedAnswer",
)
_export("answer_writer", "AnswerWriterStage")
_export("answer_control", "AnswerControlResult", "AnswerControlStage")
_export("publication", "PublicationStage")
_export(
    "incremental_recovery",
    "IncrementalRecoveryResult",
    "IncrementalRecoveryStage",
    "RecoveryTarget",
)
_export("article_lookup", "ArticleLookupResult", "ArticleLookupStage", "ArticleSourceRecord")
_export("article_answer", "ArticleAnswerResult", "ArticleAnswerStage", "ArticleSummaryBudget")
_export("front_desk", "IntakeResponseStage", "OutOfScopeResponseStage")
_export("simple_fast", "SimpleCoverage", "SimpleFastBudget", "SimpleFastResult", "SimpleFastStage")
_export(
    "verification_contract",
    "ClaimVerificationFailure",
    "ClaimVerificationRecord",
    "ClaimVerificationResult",
    "RequirementRelevance",
    "SourceEntailment",
)
_export("fact_extractor", "FactExtractorStage")
_export(
    "evidence_contract",
    "CandidateCoverage",
    "EvidenceDecisionRecord",
    "EvidenceRelevance",
    "EvidenceSelectionResult",
    "RequirementEvidenceResult",
    "SelectedEvidenceRecord",
)
_export("evidence_selector", "EvidenceSelectionBudget", "EvidenceSelectorStage")
_export("planner", "PlannerStage")
_export("retrieval", "RetrievalStage")
_export("router", "RouterStage")
_export("runner", "PipelineExecutionError", "Pipeline")


__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(
        import_module(f"{__name__}.{module_name}"),
        attribute_name,
    )
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
