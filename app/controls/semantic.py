"""Fail-closed semantic assessment orchestration."""

from collections.abc import Mapping
from typing import Any, Protocol

from app.contracts import SemanticCategory, SemanticResult, Usage


class SemanticEvaluator(Protocol):
    async def assess(self, state: Mapping[str, Any]) -> tuple[SemanticResult, Usage]: ...


class SemanticCheckError(RuntimeError):
    """Assessment could not be trusted; callers must deny the protected operation."""


def build_jev_state(*, trusted_task: str, prompt: str, document: str) -> dict[str, str]:
    """Build explicit trust-boundary fields from already-redacted server inputs."""
    return {
        "trusted_task": trusted_task,
        "untrusted_prompt": prompt,
        "untrusted_document": document,
    }


async def evaluate(
    evaluator: SemanticEvaluator,
    *,
    state: Mapping[str, Any],
    block_threshold: float,
) -> tuple[SemanticResult, Usage]:
    """Evaluate redacted state and apply the server policy threshold to the model score.

    The model only assesses content. This function applies the server-owned threshold;
    ACL, policy and budget decisions remain outside the model.
    """
    if isinstance(block_threshold, bool) or not isinstance(block_threshold, int | float):
        raise ValueError("block_threshold must be numeric")
    if not 0.0 <= block_threshold <= 1.0:
        raise ValueError("block_threshold must be in [0, 1]")
    try:
        result, usage = await evaluator.assess(state)
        if result.risk_score < block_threshold:
            result = result.model_copy(update={"category": SemanticCategory.BENIGN})
        elif result.instruction_override_probability >= result.data_exfiltration_probability:
            result = result.model_copy(update={"category": SemanticCategory.INSTRUCTION_OVERRIDE})
        else:
            result = result.model_copy(update={"category": SemanticCategory.DATA_EXFILTRATION})
        return result, usage
    except Exception as exc:
        # Do not expose provider details or input text; the gateway must fail closed.
        raise SemanticCheckError(type(exc).__name__) from None
