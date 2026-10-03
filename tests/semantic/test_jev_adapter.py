from __future__ import annotations

import json

import httpx
import pytest

from app.adapters.jev import JEV_ENDPOINT, JevAdapter, JevAdapterError
from app.contracts import CostStatus, Provider, SemanticCategory


@pytest.mark.asyncio
async def test_jev_parses_two_noul_answers_and_usage() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["authorization"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "instruction_override": {"type": "noul", "noul": 0.91},
                    "data_exfiltration": {"type": "noul", "noul": 0.2},
                },
                "usage": {"input_tokens": 42, "output_tokens": 12},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result, usage = await JevAdapter("test-key", client=client).assess(
            {"trusted_task": "summarize", "document": "synthetic text"}
        )
    finally:
        await client.aclose()

    assert captured["authorization"] == "Bearer test-key"
    assert isinstance(captured["body"], dict)
    assert captured["body"]["model"] == "jev-1.13.0"
    assert set(captured["body"]["questions"]) == {
        "instruction_override",
        "data_exfiltration",
    }
    assert result.instruction_override_probability == 0.91
    assert result.data_exfiltration_probability == 0.2
    assert result.risk_score == 0.91
    assert result.category is SemanticCategory.INSTRUCTION_OVERRIDE
    assert usage.provider is Provider.TYPESAFE
    assert usage.input_tokens == 42
    assert usage.output_tokens == 12
    assert usage.cost_status is CostStatus.UNKNOWN


@pytest.mark.asyncio
async def test_jev_http_error_is_safe_and_not_retried() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="private provider response")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(JevAdapterError) as error:
            await JevAdapter("test-key", client=client).assess({"text": "secret"})
    finally:
        await client.aclose()

    assert calls == 1
    assert "private" not in str(error.value)
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answers",
    [
        {"instruction_override": {"type": "score", "score": 0.1}},
        {
            "instruction_override": {"type": "noul", "noul": 0.1},
            "data_exfiltration": {"type": "noul", "noul": 2.0},
        },
        {
            "instruction_override": {"type": "noul", "noul": float("nan")},
            "data_exfiltration": {"type": "noul", "noul": 0.1},
        },
    ],
)
async def test_jev_rejects_missing_or_invalid_answers(answers: dict[str, object]) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": answers, "usage": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(JevAdapterError):
            await JevAdapter("test-key", client=client).assess({"text": "synthetic"})
    finally:
        await client.aclose()


def test_jev_uses_expected_endpoint() -> None:
    assert JEV_ENDPOINT == "https://api.typesafe.ai/v1/systemone"
