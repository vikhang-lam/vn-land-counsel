"""Versioned prompt registry for the replacement pipeline.

Prompt text is executable configuration.  Every prompt therefore has a stable
identifier, a semantic version and a reproducible hash.  Fine-tuned roles may
also declare the exact hash used during training; runtime alignment can then be
checked without copying prompt text into model-loading code.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """One prompt contract and its optional fine-tuning alignment record."""

    prompt_id: str
    version: str
    model_role: str
    text: str
    trained_prompt_sha256: str | None = None
    training_required: bool = False

    @property
    def prompt_sha256(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def requires_sft_alignment(self) -> bool:
        return self.training_required or self.trained_prompt_sha256 is not None

    @property
    def sft_aligned(self) -> bool | None:
        if not self.requires_sft_alignment:
            return None
        if self.trained_prompt_sha256 is None:
            return False
        return self.prompt_sha256 == self.trained_prompt_sha256

    def assert_sft_alignment(self) -> None:
        """Fail before inference when an adapter and its prompt have drifted."""

        if self.requires_sft_alignment and not self.sft_aligned:
            raise RuntimeError(
                f"Prompt {self.prompt_id}@{self.version} không khớp prompt "
                "đã dùng để SFT."
            )

    @property
    def deployment_status(self) -> str:
        if not self.requires_sft_alignment:
            return "BASE_MODEL_OK"
        if self.trained_prompt_sha256 is None:
            return "REQUIRES_TRAINING"
        return "SFT_ALIGNED" if self.sft_aligned else "PROMPT_DRIFT"


_PROMPT_REGISTRY: dict[str, PromptSpec] = {}


def register_prompt_spec(spec: PromptSpec) -> PromptSpec:
    """Register one prompt ID exactly once."""

    key = str(spec.prompt_id or "").strip().lower()
    if not key:
        raise ValueError("PromptSpec thiếu prompt_id.")
    if key in _PROMPT_REGISTRY:
        raise ValueError(f"Prompt ID bị đăng ký trùng: {key}")
    if not str(spec.version or "").strip() or not str(spec.text or "").strip():
        raise ValueError(f"Prompt {key} thiếu version hoặc nội dung.")
    _PROMPT_REGISTRY[key] = spec
    return spec


def get_prompt_spec(prompt_id: str) -> PromptSpec:
    key = str(prompt_id or "").strip().lower()
    try:
        return _PROMPT_REGISTRY[key]
    except KeyError as error:
        raise KeyError(f"Prompt chưa đăng ký: {key or '<trống>'}") from error


def registered_prompt_specs() -> tuple[PromptSpec, ...]:
    return tuple(_PROMPT_REGISTRY.values())


__all__ = [
    "PromptSpec",
    "get_prompt_spec",
    "register_prompt_spec",
    "registered_prompt_specs",
]
