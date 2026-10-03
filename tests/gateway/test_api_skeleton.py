from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

SECRET_SENTINEL = "SECRET-SENTINEL-7f3a"


def execute_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "task_id": str(uuid4()),
        "tool": "documents.summarize",
        "arguments": {"document_id": "doc-a", "prompt": "Summarize this company."},
    }
    body.update(overrides)
    return body


def post_execute(client: TestClient, body: object, idempotency_key: str | None = None):
    headers = {"Idempotency-Key": idempotency_key or str(uuid4())}
    return client.post("/v1/execute", json=body, headers=headers)


def test_valid_execute_request_is_refused_until_the_gateway_exists(client: TestClient) -> None:
    response = post_execute(client, execute_body())

    assert response.status_code == 501
    body = response.json()
    assert body["reason_code"] == "NOT_IMPLEMENTED"
    assert body["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("overrides", "expected_type"),
    [
        ({"role": "admin"}, "extra_forbidden"),
        ({"tool": "shell.exec"}, "union_tag_invalid"),
        ({"schema_version": True}, "value_error"),
        ({"arguments": {"document_id": "../doc-b", "prompt": "x"}}, "string_pattern_mismatch"),
    ],
)
def test_invalid_execute_request_returns_safe_422(
    client: TestClient, overrides: dict[str, object], expected_type: str
) -> None:
    response = post_execute(client, execute_body(**overrides))

    assert response.status_code == 422
    body = response.json()
    assert body["reason_code"] == "INVALID_INPUT"
    assert expected_type in [error["type"] for error in body["errors"]]
    assert set(body) == {"schema_version", "request_id", "reason_code", "errors"}


def test_validation_error_does_not_echo_submitted_values(client: TestClient) -> None:
    oversized = SECRET_SENTINEL + "x" * 8000
    body = execute_body(arguments={"document_id": "doc-a", "prompt": oversized})

    response = post_execute(client, body)

    assert response.status_code == 422
    assert SECRET_SENTINEL not in response.text


def test_missing_idempotency_key_is_rejected(client: TestClient) -> None:
    response = client.post("/v1/execute", json=execute_body())

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["header", "Idempotency-Key"]


def test_create_task_validates_body_before_refusing(client: TestClient) -> None:
    valid = client.post("/v1/tasks", json={"schema_version": 1, "client_id": "client-a"})
    forged = client.post(
        "/v1/tasks",
        json={"schema_version": 1, "client_id": "client-a", "principal_id": "admin"},
    )

    assert valid.status_code == 501
    assert forged.status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"/v1/tasks/{uuid4()}"),
        ("GET", "/admin/policy"),
        ("PUT", "/admin/policy"),
        ("GET", "/admin/feed"),
        ("PUT", "/admin/feed"),
        ("GET", "/admin/events"),
        ("GET", "/admin/metrics"),
        ("GET", "/admin/audit/export"),
        ("GET", "/admin/test-results"),
    ],
)
def test_skeleton_routes_refuse_with_not_implemented(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path)

    assert response.status_code == 501
    assert response.json()["reason_code"] == "NOT_IMPLEMENTED"
