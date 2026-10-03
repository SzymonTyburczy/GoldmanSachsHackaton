"""Request body limit before parsing."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.body_limit import MAX_ADMIN_BODY_BYTES, MAX_BODY_BYTES
from tests.gateway.support import StubProviders

Headers = dict[str, dict[str, str]]

TASK_JSON = b'{"schema_version":1,"client_id":"client-a"}'


def padded(size: int) -> bytes:
    """Valid task JSON of exactly ``size`` bytes, padded with leading whitespace."""
    return b" " * (size - len(TASK_JSON)) + TASK_JSON


def task_count(db_path: Path) -> int:
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute("SELECT count(*) FROM tasks").fetchone()[0]


def json_headers(headers: Headers, identity: str = "analyst-a") -> dict[str, str]:
    return headers[identity] | {"Content-Type": "application/json"}


def assert_too_large(response) -> None:  # noqa: ANN001
    assert response.status_code == 413
    body = response.json()
    assert body["reason_code"] == "INPUT_TOO_LARGE"
    assert body["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.usefixtures("active_config")
def test_body_at_the_limit_is_accepted(client: TestClient, headers: Headers) -> None:
    response = client.post(
        "/v1/tasks", content=padded(MAX_BODY_BYTES), headers=json_headers(headers)
    )

    assert response.status_code == 201


@pytest.mark.usefixtures("active_config")
def test_body_over_the_limit_is_refused_before_parsing(
    client: TestClient, headers: Headers, db_path: Path
) -> None:
    response = client.post(
        "/v1/tasks", content=padded(MAX_BODY_BYTES + 1), headers=json_headers(headers)
    )

    assert_too_large(response)
    assert task_count(db_path) == 0


@pytest.mark.usefixtures("active_config")
def test_chunked_body_without_length_is_counted(
    client: TestClient, headers: Headers, db_path: Path
) -> None:
    def chunks() -> Iterator[bytes]:
        yield from (b" " * 4096 for _ in range(9))
        yield TASK_JSON

    response = client.post("/v1/tasks", content=chunks(), headers=json_headers(headers))

    assert_too_large(response)
    assert task_count(db_path) == 0


@pytest.mark.usefixtures("active_config")
def test_false_content_length_does_not_pass_the_limit(
    client: TestClient, headers: Headers, db_path: Path
) -> None:
    response = client.post(
        "/v1/tasks",
        content=padded(MAX_BODY_BYTES * 3),
        headers=json_headers(headers) | {"Content-Length": "100"},
    )

    assert_too_large(response)
    assert task_count(db_path) == 0


@pytest.mark.usefixtures("active_config")
def test_oversized_execute_runs_no_adapter(
    client: TestClient, headers: Headers, providers: StubProviders
) -> None:
    body = b'{"schema_version":1}' + b" " * MAX_BODY_BYTES
    response = client.post(
        "/v1/execute",
        content=body,
        headers=json_headers(headers) | {"Idempotency-Key": str(uuid4())},
    )

    assert_too_large(response)
    assert client.app.state.documents.read_count == 0
    assert providers.jev.states == []


def test_unauthenticated_oversized_body_is_refused(client: TestClient) -> None:
    response = client.post(
        "/v1/tasks",
        content=padded(MAX_BODY_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413


@pytest.mark.usefixtures("active_config")
def test_admin_config_has_its_own_larger_limit(client: TestClient, headers: Headers) -> None:
    feed = b'{"schema_version":1,"expected_version":1,"feed":{"schema_version":1,"rules":[]}}'
    larger = b" " * (MAX_BODY_BYTES * 2) + feed
    over = b" " * MAX_ADMIN_BODY_BYTES + feed

    accepted = client.put("/admin/feed", content=larger, headers=json_headers(headers, "admin"))
    refused = client.put("/admin/feed", content=over, headers=json_headers(headers, "admin"))

    assert accepted.status_code == 200, accepted.text
    assert_too_large(refused)
