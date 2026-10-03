"""What the real Jev and Luna adapters put on the wire when the gateway calls them.

The adapters are Paweł's, unchanged; only their HTTP transport is replaced, so the bodies
captured here are the ones TypeSafe and OpenAI would receive.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app.adapters.jev import JevAdapter
from app.adapters.openai_luna import OpenAILunaAdapter
from app.adapters.providers import ProviderSet
from app.main import create_app
from app.policy import ModelsPolicy
from app.prompts.semantic import SEMANTIC_QUESTIONS
from app.prompts.summary import SUMMARY_INSTRUCTIONS
from app.settings import Settings
from tests.gateway.support import TOKENS, activate_config
from tests.gateway.test_summary import PROMPT, SENSITIVE

Headers = dict[str, dict[str, str]]

PROVIDER_KEYS = ("typesafe-wire-test-key", "openai-wire-test-key")
SUMMARY_TEXT = "Fabrikam Logistics is an active freight client. Write to ops@fabrikam.example."


class FakeProviderApis:
    """TypeSafe and OpenAI endpoints answering like the real services."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.scores = {"instruction_override": 0.04, "data_exfiltration": 0.02}
        self.jev_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "api.typesafe.ai":
            answers = {name: {"type": "noul", "noul": score} for name, score in self.scores.items()}
            return httpx.Response(
                self.jev_status,
                json={
                    "answers": answers,
                    "model": "jev-1.13.0",
                    "usage": {"input_tokens": 310, "output_tokens": 4},
                },
            )
        if request.url.path == "/v1/responses/input_tokens":
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 95})
        return httpx.Response(
            200,
            json={
                "id": "resp_wire",
                "object": "response",
                "created_at": 1790000000,
                "model": "gpt-6-luna",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_wire",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": SUMMARY_TEXT, "annotations": []}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 95,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 30,
                    "output_tokens_details": {"reasoning_tokens": 12},
                    "total_tokens": 125,
                },
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests]


class WireProviders:
    """The real adapters, configured from the pinned policy, on a mock transport."""

    def __init__(self, apis: FakeProviderApis) -> None:
        self._transport = httpx.MockTransport(apis)

    def connect(self, models: ModelsPolicy) -> ProviderSet:
        typesafe_key, openai_key = PROVIDER_KEYS
        client = AsyncOpenAI(
            api_key=openai_key,
            max_retries=0,
            http_client=httpx.AsyncClient(transport=self._transport),
        )
        return ProviderSet(
            JevAdapter(
                typesafe_key,
                timeout=float(models.detector_timeout_seconds),
                client=httpx.AsyncClient(transport=self._transport),
            ),
            OpenAILunaAdapter(
                openai_key,
                timeout=float(models.summary_timeout_seconds),
                max_output_tokens=models.summary_max_output_tokens,
                client=client,
            ),
        )


@pytest.fixture
def apis() -> FakeProviderApis:
    return FakeProviderApis()


@pytest.fixture
def client(settings: Settings, apis: FakeProviderApis, db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(settings, WireProviders(apis))) as test_client:
        activate_config(db_path, "policy")
        activate_config(db_path, "feed")
        yield test_client


def summarize(client: TestClient, headers: Headers, new_task: Callable[..., str]) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "task_id": new_task("reviewer-a"),
        "tool": "documents.summarize",
        "arguments": {"document_id": "doc-a", "prompt": PROMPT},
    }
    response = client.post(
        "/v1/execute", json=body, headers=headers["reviewer-a"] | {"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_providers_receive_only_redacted_data(
    client: TestClient, headers: Headers, apis: FakeProviderApis, new_task: Callable[..., str]
) -> None:
    body = summarize(client, headers, new_task)

    assert (body["decision"], body["execution_status"]) == ("REDACT", "SUCCEEDED")
    assert [(r.url.host, r.url.path) for r in apis.requests] == [
        ("api.typesafe.ai", "/v1/systemone"),
        ("api.openai.com", "/v1/responses/input_tokens"),
        ("api.openai.com", "/v1/responses"),
    ]
    jev, count, create = apis.bodies()
    assert (jev["model"], jev["questions"]) == ("jev-1.13.0", SEMANTIC_QUESTIONS)
    assert count == {
        "model": "gpt-6-luna",
        "instructions": SUMMARY_INSTRUCTIONS,
        "input": count["input"],
    }
    assert create["input"] == count["input"]  # the counted input is the one generated from
    assert (create["store"], create["reasoning"], create["max_output_tokens"]) == (
        False,
        {"effort": "low"},
        2048,  # policy: models.summary_max_output_tokens
    )
    assert "<EMAIL_ADDRESS>" in count["input"]
    for request in apis.requests:
        sent = request.content.decode() + str(request.headers)
        for value in (*SENSITIVE, *TOKENS.values()):
            assert value not in sent  # no raw data and no demo access token
    # Each provider gets its own key, from the server's settings.
    assert [r.headers["Authorization"] for r in apis.requests] == [
        f"Bearer {PROVIDER_KEYS[0]}",
        f"Bearer {PROVIDER_KEYS[1]}",
        f"Bearer {PROVIDER_KEYS[1]}",
    ]
    # The provider's answer is filtered before the caller sees it.
    assert body["output"]["text"] == (
        "Fabrikam Logistics is an active freight client. Write to <EMAIL_ADDRESS>."
    )
    # The count endpoint names no model; unknown values stay null.
    assert [usage["model"] for usage in body["usage"]] == ["jev-1.13.0", None, "gpt-6-luna"]


def test_semantic_block_sends_nothing_to_openai(
    client: TestClient, headers: Headers, apis: FakeProviderApis, new_task: Callable[..., str]
) -> None:
    apis.scores = {"instruction_override": 0.97, "data_exfiltration": 0.4}

    body = summarize(client, headers, new_task)

    assert (body["decision"], body["reason_code"]) == ("DENY", "SEMANTIC_RISK")
    assert [r.url.host for r in apis.requests] == ["api.typesafe.ai"]


def test_detector_error_sends_nothing_to_openai(
    client: TestClient, headers: Headers, apis: FakeProviderApis, new_task: Callable[..., str]
) -> None:
    apis.jev_status = 503

    body = summarize(client, headers, new_task)

    assert (body["decision"], body["reason_code"]) == ("DENY", "DETECTOR_UNAVAILABLE")
    assert body["adapter_calls"]["detector"] == "FAILED"
    assert [r.url.host for r in apis.requests] == ["api.typesafe.ai"]
