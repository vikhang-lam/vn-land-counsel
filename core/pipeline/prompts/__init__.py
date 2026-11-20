"""Prompt contracts used only by the replacement pipeline.

The package is intentionally isolated from ``core.prompts`` while the new
pipeline is under construction.  At production promotion time it becomes the
canonical prompt package and the previous prompt bundle is removed.
"""

from .registry import PromptSpec, get_prompt_spec, registered_prompt_specs
from .facts import (
    FACT_EXTRACTION_RETRY_INSTRUCTION,
    FACT_EXTRACTOR_BASELINE_SPEC,
    FACT_EXTRACTOR_CANDIDATE_SPEC,
    FACT_EXTRACTOR_JSON_SCHEMA,
)
from .planning import (
    PLANNER_AUDIT_JSON_SCHEMA,
    PLANNER_AUDIT_RETRY_INSTRUCTION,
    PLANNER_AUDIT_SPEC,
    PLANNER_BASELINE_SPEC,
    PLANNER_CANDIDATE_SPEC,
    PLANNER_REPAIR_INSTRUCTION,
    PLANNER_REPAIR_DIRECTIVE_JSON_SCHEMA,
    PLANNER_REPAIR_DIRECTIVE_SPEC,
    PLANNER_FULL_REVISE_SPEC,
    PLANNER_SEMANTIC_REPAIR_INSTRUCTION,
    TEMPORAL_EXTRACTOR_JSON_SCHEMA,
    TEMPORAL_EXTRACTOR_SPEC,
)
from .routing import (
    ROUTER_JSON_SCHEMA,
    ROUTER_PROMPT_SPEC,
    SCOPE_REVIEW_JSON_SCHEMA,
    SCOPE_REVIEW_PROMPT_SPEC,
)
from .retrieval import (
    RETRIEVAL_RECOVERY_QUERY_SPEC,
    RETRIEVAL_QUERY_VARIANT_SPEC,
    retrieval_query_variant_schema,
)
from .evidence import (
    EVIDENCE_CLASSIFIER_RETRY_INSTRUCTION,
    EVIDENCE_CLASSIFIER_SPEC,
    evidence_classifier_schema,
)
from .claims import (
    CLAIM_EXTRACTOR_RETRY_INSTRUCTION,
    CLAIM_EXTRACTOR_SPEC,
    claim_extractor_schema,
)
from .verification import (
    CLAIM_VERIFIER_BASELINE_SPEC,
    CLAIM_VERIFIER_CANDIDATE_SPEC,
)
from .conditions import (
    CONDITION_EXTRACTOR_JSON_SCHEMA,
    CONDITION_EXTRACTOR_RETRY_INSTRUCTION,
    CONDITION_EXTRACTOR_SPEC,
    CONDITION_MATCHER_RETRY_INSTRUCTION,
    CONDITION_MATCHER_SPEC,
    condition_matcher_schema,
)
from .answer import (
    ANSWER_UNIT_AUDIT_SPEC,
    ANSWER_UNIT_BATCH_REVISER_SPEC,
    ANSWER_UNIT_JSON_SCHEMA,
    ANSWER_UNIT_REVISER_SPEC,
    ANSWER_UNIT_RETRY_INSTRUCTION,
    ANSWER_UNIT_SPEC,
    answer_unit_audit_schema,
    answer_unit_revision_schema,
)
from .front_desk import INTAKE_RESPONSE_SPEC, OUT_OF_SCOPE_RESPONSE_SPEC
from .simple import (
    SIMPLE_GROUNDED_WRITER_SPEC,
    SIMPLE_SOURCE_GATE_SPEC,
    simple_grounded_writer_schema,
    simple_source_gate_schema,
)
from .article import ARTICLE_SUMMARIZER_SPEC, article_summarizer_schema

__all__ = [
    "PromptSpec",
    "FACT_EXTRACTION_RETRY_INSTRUCTION",
    "FACT_EXTRACTOR_BASELINE_SPEC",
    "FACT_EXTRACTOR_CANDIDATE_SPEC",
    "FACT_EXTRACTOR_JSON_SCHEMA",
    "PLANNER_AUDIT_JSON_SCHEMA",
    "PLANNER_AUDIT_RETRY_INSTRUCTION",
    "PLANNER_AUDIT_SPEC",
    "PLANNER_BASELINE_SPEC",
    "PLANNER_CANDIDATE_SPEC",
    "PLANNER_REPAIR_INSTRUCTION",
    "PLANNER_REPAIR_DIRECTIVE_JSON_SCHEMA",
    "PLANNER_REPAIR_DIRECTIVE_SPEC",
    "PLANNER_FULL_REVISE_SPEC",
    "PLANNER_SEMANTIC_REPAIR_INSTRUCTION",
    "TEMPORAL_EXTRACTOR_JSON_SCHEMA",
    "TEMPORAL_EXTRACTOR_SPEC",
    "ROUTER_JSON_SCHEMA",
    "ROUTER_PROMPT_SPEC",
    "SCOPE_REVIEW_JSON_SCHEMA",
    "SCOPE_REVIEW_PROMPT_SPEC",
    "RETRIEVAL_QUERY_VARIANT_SPEC",
    "RETRIEVAL_RECOVERY_QUERY_SPEC",
    "retrieval_query_variant_schema",
    "EVIDENCE_CLASSIFIER_RETRY_INSTRUCTION",
    "EVIDENCE_CLASSIFIER_SPEC",
    "evidence_classifier_schema",
    "CLAIM_EXTRACTOR_RETRY_INSTRUCTION",
    "CLAIM_EXTRACTOR_SPEC",
    "claim_extractor_schema",
    "CLAIM_VERIFIER_BASELINE_SPEC",
    "CLAIM_VERIFIER_CANDIDATE_SPEC",
    "CONDITION_EXTRACTOR_JSON_SCHEMA",
    "CONDITION_EXTRACTOR_RETRY_INSTRUCTION",
    "CONDITION_EXTRACTOR_SPEC",
    "CONDITION_MATCHER_RETRY_INSTRUCTION",
    "CONDITION_MATCHER_SPEC",
    "condition_matcher_schema",
    "ANSWER_UNIT_JSON_SCHEMA",
    "ANSWER_UNIT_AUDIT_SPEC",
    "ANSWER_UNIT_BATCH_REVISER_SPEC",
    "ANSWER_UNIT_REVISER_SPEC",
    "ANSWER_UNIT_RETRY_INSTRUCTION",
    "ANSWER_UNIT_SPEC",
    "answer_unit_audit_schema",
    "answer_unit_revision_schema",
    "INTAKE_RESPONSE_SPEC",
    "OUT_OF_SCOPE_RESPONSE_SPEC",
    "SIMPLE_GROUNDED_WRITER_SPEC",
    "SIMPLE_SOURCE_GATE_SPEC",
    "simple_grounded_writer_schema",
    "simple_source_gate_schema",
    "ARTICLE_SUMMARIZER_SPEC",
    "article_summarizer_schema",
    "get_prompt_spec",
    "registered_prompt_specs",
]
