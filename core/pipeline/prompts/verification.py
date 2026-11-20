"""Locked prompt metadata for the active fine-tuned Claim Verifier."""

from __future__ import annotations

from core.agents.claim_verifier_contract import CLAIM_VERIFIER_PROMPT

from .registry import PromptSpec, register_prompt_spec


CLAIM_VERIFIER_BASELINE_SPEC = register_prompt_spec(
    PromptSpec(
        prompt_id="claim_verifier",
        version="3.0.0",
        model_role="claim_verifier",
        text=CLAIM_VERIFIER_PROMPT,
        trained_prompt_sha256=(
            "7dae63aeef68fe1757b326c42c5b5ff3a8cc2e49af9a036e77b71e3545c96f77"
        ),
        training_required=True,
    )
)


# Compatibility alias for callers that used the candidate name while the
# canonical adapter was still under evaluation.
CLAIM_VERIFIER_CANDIDATE_SPEC = CLAIM_VERIFIER_BASELINE_SPEC


__all__ = [
    "CLAIM_VERIFIER_BASELINE_SPEC",
    "CLAIM_VERIFIER_CANDIDATE_SPEC",
]
