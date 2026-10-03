"""Gateway test fixtures: demo identities with test tokens, tasks and an active config."""

from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.gateway.support import TOKENS, StubProviders, activate_config


@pytest.fixture
def settings(db_path: Path) -> Settings:
    return Settings(
        db_path=db_path,
        token_analyst_a=TOKENS["analyst-a"],
        token_reviewer_a=TOKENS["reviewer-a"],
        token_admin=TOKENS["admin"],
    )


@pytest.fixture
def providers() -> StubProviders:
    return StubProviders()


@pytest.fixture
def client(settings: Settings, providers: StubProviders) -> Iterator[TestClient]:
    with TestClient(create_app(settings, providers)) as test_client:
        yield test_client


@pytest.fixture
def headers() -> dict[str, dict[str, str]]:
    return {name: {"Authorization": f"Bearer {token}"} for name, token in TOKENS.items()}


@pytest.fixture
def active_config(client: TestClient, db_path: Path) -> None:
    activate_config(db_path, "policy")
    activate_config(db_path, "feed")


@pytest.fixture
def new_task(client: TestClient, headers: dict[str, dict[str, str]]) -> Callable[..., str]:
    def create(identity: str, client_id: str = "client-a") -> str:
        response = client.post(
            "/v1/tasks",
            json={"schema_version": 1, "client_id": client_id},
            headers=headers[identity],
        )
        assert response.status_code == 201, response.text
        return response.json()["task_id"]

    return create


@pytest.fixture
def execute(
    client: TestClient, headers: dict[str, dict[str, str]]
) -> Callable[..., httpx.Response]:
    def call(identity: str | None, task_id: str, tool: str, **arguments: str) -> httpx.Response:
        request_headers = {"Idempotency-Key": str(uuid4())}
        if identity is not None:
            request_headers |= headers[identity]
        body = {"schema_version": 1, "task_id": task_id, "tool": tool, "arguments": arguments}
        return client.post("/v1/execute", json=body, headers=request_headers)

    return call
