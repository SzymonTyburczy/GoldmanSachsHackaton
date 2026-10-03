"""OpenAI Responses API adapter for Luna token counting and summaries."""

from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.contracts import CostStatus, Provider, Usage
from app.prompts.summary import SUMMARY_INSTRUCTIONS

LUNA_MODEL = "gpt-6-luna"
DEFAULT_TIMEOUT_SECONDS = 30.0


class OpenAILunaError(RuntimeError):
    """Safe-to-surface provider failure; never includes provider body or submitted text."""


@dataclass(frozen=True)
class TokenCount:
    input_tokens: int
    usage: Usage


@dataclass(frozen=True)
class SummaryResult:
    text: str
    usage: Usage


class OpenAILunaAdapter:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = 2048,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key is required")
        if timeout <= 0 or max_output_tokens <= 0:
            raise ValueError("timeout and max_output_tokens must be positive")
        self._api_key = api_key
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens
        self._client = client

    async def count_input_tokens(self, *, input: str) -> TokenCount:
        """Count tokens for an already-redacted, complete Responses API input."""
        response = await self._call("count_tokens", input=input)
        count = getattr(response, "input_tokens", None)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise OpenAILunaError("invalid token-count response")
        return TokenCount(
            input_tokens=count,
            usage=_usage(
                response,
                requested_model=LUNA_MODEL,
                output_tokens=None,
                cost_status=CostStatus.UNKNOWN,
            ),
        )

    async def summarize(self, *, input: str, max_output_tokens: int | None = None) -> SummaryResult:
        """Generate a bounded summary from an already-redacted complete input."""
        output_limit = self._max_output_tokens if max_output_tokens is None else max_output_tokens
        if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
        response = await self._call(
            "create_response",
            input=input,
            max_output_tokens=output_limit,
        )
        status = getattr(response, "status", None)
        if status is not None and status != "completed":
            raise OpenAILunaError("incomplete summary response")
        _reject_refusal(response)
        text = getattr(response, "output_text", None)
        if not isinstance(text, str) or not text.strip():
            raise OpenAILunaError("empty or incomplete summary response")
        return SummaryResult(
            text=text,
            usage=_usage(
                response,
                requested_model=LUNA_MODEL,
                output_tokens=_usage_count(getattr(response, "usage", None), "output_tokens"),
                cost_status=CostStatus.UNKNOWN,
            ),
        )

    async def _call(
        self, operation: str, *, input: str, max_output_tokens: int | None = None
    ) -> Any:
        try:
            if self._client is not None:
                return await self._invoke(
                    self._client, operation, input=input, max_output_tokens=max_output_tokens
                )
            async with AsyncOpenAI(
                api_key=self._api_key,
                timeout=self._timeout,
                max_retries=0,
            ) as client:
                return await self._invoke(
                    client, operation, input=input, max_output_tokens=max_output_tokens
                )
        except OpenAILunaError:
            raise
        except Exception as exc:
            # Do not include exception strings: SDK errors may contain prompts or response data.
            raise OpenAILunaError(type(exc).__name__) from None

    async def _invoke(
        self,
        client: AsyncOpenAI,
        operation: str,
        *,
        input: str,
        max_output_tokens: int | None,
    ) -> Any:
        if operation == "count_tokens":
            return await client.responses.input_tokens.count(
                model=LUNA_MODEL,
                instructions=SUMMARY_INSTRUCTIONS,
                input=input,
            )
        return await client.responses.create(
            model=LUNA_MODEL,
            instructions=SUMMARY_INSTRUCTIONS,
            input=input,
            reasoning={"effort": "low"},
            max_output_tokens=max_output_tokens,
            store=False,
        )


def _usage(
    response: Any,
    *,
    requested_model: str,
    output_tokens: int | None,
    cost_status: CostStatus,
) -> Usage:
    raw = getattr(response, "usage", None)
    input_tokens = _usage_count(response, "input_tokens")
    if input_tokens is None:
        input_tokens = _usage_count(raw, "input_tokens")
    details = getattr(raw, "input_tokens_details", None)
    cached_tokens = _usage_count(details, "cached_tokens")
    reported_model = getattr(response, "model", None)
    response_id = getattr(response, "id", None)
    return Usage(
        provider=Provider.OPENAI,
        requested_model=requested_model,
        model=reported_model if isinstance(reported_model, str) and reported_model else None,
        provider_response_id=response_id if isinstance(response_id, str) and response_id else None,
        input_tokens=input_tokens,
        cached_input_tokens=cached_tokens,
        output_tokens=output_tokens,
        cost_nusd=None,
        pricing_version=None,
        cost_status=cost_status,
    )


def _reject_refusal(response: Any) -> None:
    for item in getattr(response, "output", ()) or ():
        for content in getattr(item, "content", ()) or ():
            if getattr(content, "type", None) == "refusal":
                raise OpenAILunaError("provider refused summary")


def _usage_count(value: Any, field: str) -> int | None:
    count = getattr(value, field, None)
    if count is None:
        return None
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise OpenAILunaError("invalid token usage")
    return count
