from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters.openai_luna import (
    LUNA_MODEL,
    OpenAILunaAdapter,
    OpenAILunaError,
)
from app.contracts import CostStatus, Provider
from app.prompts.summary import SUMMARY_INSTRUCTIONS


class FakeResponses:
    def __init__(self) -> None:
        self.count_args: dict[str, Any] | None = None
        self.create_args: dict[str, Any] | None = None
        self.count_result = SimpleNamespace(input_tokens=17)
        self.create_result = SimpleNamespace(
            id="resp-test",
            model=LUNA_MODEL,
            output_text="A short synthetic summary.",
            status="completed",
            output=(),
            usage=SimpleNamespace(
                input_tokens=17,
                output_tokens=8,
                input_tokens_details=SimpleNamespace(cached_tokens=2),
            ),
        )
        self.input_tokens = SimpleNamespace(count=self.count)

    async def count(self, **kwargs: Any) -> Any:
        self.count_args = kwargs
        return self.count_result

    async def create(self, **kwargs: Any) -> Any:
        self.create_args = kwargs
        return self.create_result


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_token_count_calls_provider_with_complete_input() -> None:
    fake = FakeClient()
    adapter = OpenAILunaAdapter("test-key", client=fake)  # type: ignore[arg-type]

    result = await adapter.count_input_tokens(input="already-redacted synthetic input")

    assert result.input_tokens == 17
    assert fake.responses.count_args == {
        "model": LUNA_MODEL,
        "instructions": SUMMARY_INSTRUCTIONS,
        "input": "already-redacted synthetic input",
    }
    assert result.usage.provider is Provider.OPENAI
    assert result.usage.input_tokens == 17
    assert result.usage.output_tokens is None
    assert result.usage.cost_status is CostStatus.UNKNOWN


@pytest.mark.asyncio
async def test_summary_sets_store_false_no_retry_and_returns_usage() -> None:
    fake = FakeClient()
    adapter = OpenAILunaAdapter("test-key", client=fake, max_output_tokens=64)  # type: ignore[arg-type]

    result = await adapter.summarize(input="already-redacted synthetic input")

    assert result.text == "A short synthetic summary."
    assert fake.responses.create_args == {
        "model": LUNA_MODEL,
        "instructions": SUMMARY_INSTRUCTIONS,
        "input": "already-redacted synthetic input",
        "reasoning": {"effort": "low"},
        "max_output_tokens": 64,
        "store": False,
    }
    assert result.usage.provider_response_id == "resp-test"
    assert result.usage.input_tokens == 17
    assert result.usage.cached_input_tokens == 2
    assert result.usage.output_tokens == 8
    assert result.usage.cost_status is CostStatus.UNKNOWN


@pytest.mark.asyncio
async def test_summary_rejects_empty_output() -> None:
    fake = FakeClient()
    fake.responses.create_result.output_text = "  "
    adapter = OpenAILunaAdapter("test-key", client=fake)  # type: ignore[arg-type]

    with pytest.raises(OpenAILunaError, match="empty or incomplete"):
        await adapter.summarize(input="synthetic")


@pytest.mark.asyncio
async def test_provider_error_does_not_leak_exception_content() -> None:
    class BrokenResponses(FakeResponses):
        async def count(self, **kwargs: Any) -> Any:
            raise RuntimeError("provider echoed secret-input")

    fake = FakeClient()
    fake.responses = BrokenResponses()
    adapter = OpenAILunaAdapter("test-key", client=fake)  # type: ignore[arg-type]

    with pytest.raises(OpenAILunaError) as error:
        await adapter.count_input_tokens(input="secret-input")
    assert "secret-input" not in str(error.value)


@pytest.mark.asyncio
async def test_summary_rejects_refusal_and_incomplete_response() -> None:
    fake = FakeClient()
    fake.responses.create_result.output = [
        SimpleNamespace(content=[SimpleNamespace(type="refusal")])
    ]
    adapter = OpenAILunaAdapter("test-key", client=fake)  # type: ignore[arg-type]
    with pytest.raises(OpenAILunaError, match="refused"):
        await adapter.summarize(input="synthetic")

    fake.responses.create_result.output = []
    fake.responses.create_result.status = "incomplete"
    with pytest.raises(OpenAILunaError, match="incomplete"):
        await adapter.summarize(input="synthetic")
