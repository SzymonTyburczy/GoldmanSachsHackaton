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


@pytest.fixture
def analyst(headers: dict[str, dict[str, str]]) -> dict[str, str]:
    return headers["analyst-a"] | {"Idempotency-Key": str(uuid4())}


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
    client: TestClient,
    analyst: dict[str, str],
    overrides: dict[str, object],
    expected_type: str,
) -> None:
    response = client.post("/v1/execute", json=execute_body(**overrides), headers=analyst)

    assert response.status_code == 422
    body = response.json()
    assert body["reason_code"] == "INVALID_INPUT"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert expected_type in [error["type"] for error in body["errors"]]
    assert set(body) == {"schema_version", "request_id", "reason_code", "errors"}


def test_validation_error_does_not_echo_submitted_values(
    client: TestClient, analyst: dict[str, str]
) -> None:
    oversized = SECRET_SENTINEL + "x" * 8000
    body = execute_body(arguments={"document_id": "doc-a", "prompt": oversized})

    response = client.post("/v1/execute", json=body, headers=analyst)

    assert response.status_code == 422
    assert SECRET_SENTINEL not in response.text


def test_missing_idempotency_key_is_rejected(
    client: TestClient, headers: dict[str, dict[str, str]]
) -> None:
    response = client.post("/v1/execute", json=execute_body(), headers=headers["analyst-a"])

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["header", "Idempotency-Key"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
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
def test_admin_skeleton_routes_refuse_with_not_implemented(
    client: TestClient, headers: dict[str, dict[str, str]], method: str, path: str
) -> None:
    response = client.request(method, path, headers=headers["admin"])

    assert response.status_code == 501
    assert response.json()["reason_code"] == "NOT_IMPLEMENTED"
