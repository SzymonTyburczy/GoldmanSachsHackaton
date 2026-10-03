from __future__ import annotations

from typing import Any

import pytest

from app.adapters.jev import JevAdapterError
from app.contracts import (
    CostStatus,
    Provider,
    SemanticCategory,
    SemanticResult,
    Usage,
)
from app.controls.semantic import SemanticCheckError, build_jev_state, evaluate


def assessment(override: float, exfiltration: float) -> SemanticResult:
    return SemanticResult(
        instruction_override_probability=override,
        data_exfiltration_probability=exfiltration,
        risk_score=max(override, exfiltration),
        category=(
            SemanticCategory.INSTRUCTION_OVERRIDE
            if override >= exfiltration
            else SemanticCategory.DATA_EXFILTRATION
        ),
    )


def usage() -> Usage:
    return Usage(
        provider=Provider.TYPESAFE,
        requested_model="jev-1.13.0",
        model="jev-1.13.0",
        provider_response_id=None,
        input_tokens=10,
        cached_input_tokens=None,
        output_tokens=2,
        cost_nusd=None,
        pricing_version=None,
        cost_status=CostStatus.UNKNOWN,
    )


def test_jev_state_marks_trusted_and_untrusted_fields_separately() -> None:
    assert build_jev_state(
        trusted_task="summarize authorized company info",
        prompt="synthetic client request",
        document="synthetic document",
    ) == {
        "trusted_task": "summarize authorized company info",
        "untrusted_prompt": "synthetic client request",
        "untrusted_document": "synthetic document",
    }


class StubEvaluator:
    def __init__(
        self, result: SemanticResult | None = None, error: Exception | None = None
    ) -> None:
        self.result = result or assessment(0.1, 0.2)
        self.error = error
        self.state: dict[str, Any] | None = None

    async def assess(self, state: dict[str, Any]) -> tuple[SemanticResult, Usage]:
        self.state = state
        if self.error:
            raise self.error
        return self.result, usage()


@pytest.mark.asyncio
async def test_below_threshold_is_benign_and_passes_state_to_provider() -> None:
    evaluator = StubEvaluator(assessment(0.2, 0.4))
    state = {"trusted_task": "summarize synthetic record", "document": "redacted content"}

    result, provider_usage = await evaluate(evaluator, state=state, block_threshold=0.8)

    assert evaluator.state == state
    assert result.risk_score == 0.4
    assert result.category is SemanticCategory.BENIGN
    assert provider_usage.provider is Provider.TYPESAFE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "exfiltration", "threshold", "category"),
    [
        (0.8, 0.1, 0.8, SemanticCategory.INSTRUCTION_OVERRIDE),
        (0.1, 0.8, 0.8, SemanticCategory.DATA_EXFILTRATION),
        (0.8, 0.8, 0.8, SemanticCategory.INSTRUCTION_OVERRIDE),
    ],
)
async def test_at_or_above_threshold_is_risky(
    override: float,
    exfiltration: float,
    threshold: float,
    category: SemanticCategory,
) -> None:
    result, _ = await evaluate(
        StubEvaluator(assessment(override, exfiltration)),
        state={"document": "synthetic"},
        block_threshold=threshold,
    )
    assert result.risk_score >= threshold
    assert result.category is category


@pytest.mark.asyncio
async def test_provider_failure_becomes_fail_closed_control_error() -> None:
    evaluator = StubEvaluator(error=JevAdapterError("upstream unavailable"))

    with pytest.raises(SemanticCheckError) as error:
        await evaluate(evaluator, state={"document": "synthetic"}, block_threshold=0.8)
    assert "JevAdapterError" in str(error.value)


@pytest.mark.parametrize("threshold", [-0.01, 1.01, True, "0.8"])
def test_invalid_threshold_is_rejected(threshold: object) -> None:
    with pytest.raises(ValueError, match="block_threshold"):
        # Validation is intentionally synchronous before any provider call.
        import asyncio

        asyncio.run(
            evaluate(StubEvaluator(), state={}, block_threshold=threshold)  # type: ignore[arg-type]
        )
