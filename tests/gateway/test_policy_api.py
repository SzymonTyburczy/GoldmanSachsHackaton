"""Policy changes through the admin API and their effect on the next request."""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.contracts import PiiFinding
from app.pii.engine import PiiEngineUnavailable
from app.policy import Policy
from tests.gateway.support import activate_config, config_document

Execute = Callable[..., httpx.Response]
NewTask = Callable[..., str]
Headers = dict[str, dict[str, str]]


def shipped() -> dict[str, Any]:
    document = config_document("policy")
    return json.loads(document.model_dump_json())


def put_policy(
    client: TestClient, headers: Headers, policy: dict[str, Any], expected: int | None
) -> httpx.Response:
    body = {"schema_version": 1, "expected_version": expected, "policy": policy}
    return client.put("/admin/policy", json=body, headers=headers["admin"])


def active(client: TestClient, headers: Headers) -> dict[str, Any]:
    response = client.get("/admin/policy", headers=headers["admin"])
    assert response.status_code == 200, response.text
    return response.json()


def events_of(client: TestClient, headers: Headers, request_id: str) -> list[dict[str, Any]]:
    response = client.get(
        "/admin/events", params={"request_id": request_id}, headers=headers["admin"]
    )
    return response.json()["events"]


@pytest.mark.usefixtures("active_config")
def test_admin_reads_the_complete_active_policy(client: TestClient, headers: Headers) -> None:
    body = active(client, headers)

    assert body["policy_version"] == 1
    assert body["created_by"] == "test"
    assert body["policy"] == shipped()
    canonical = json.dumps(body["policy"], sort_keys=True, separators=(",", ":"))
    assert body["sha256"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_policy_is_unavailable_until_one_is_active(client: TestClient, headers: Headers) -> None:
    response = client.get("/admin/policy", headers=headers["admin"])

    assert response.status_code == 503
    assert response.json()["reason_code"] == "INVALID_CONFIG"


def test_first_policy_can_be_activated_through_the_api(
    client: TestClient, headers: Headers
) -> None:
    response = put_policy(client, headers, shipped(), expected=None)

    assert response.status_code == 200
    assert (response.json()["policy_version"], response.json()["created_by"]) == (1, "admin")


@pytest.mark.usefixtures("active_config")
def test_update_activates_the_next_version(client: TestClient, headers: Headers) -> None:
    policy = shipped()
    policy["semantic"]["block_threshold"] = 0.65

    response = put_policy(client, headers, policy, expected=1)

    assert response.status_code == 200
    assert response.json()["policy_version"] == 2
    assert active(client, headers)["policy"]["semantic"]["block_threshold"] == 0.65
    assert client.get("/health").json()["policy_version"] == 2


@pytest.mark.usefixtures("active_config")
def test_stale_update_is_refused(client: TestClient, headers: Headers) -> None:
    assert put_policy(client, headers, shipped(), expected=1).status_code == 200
    policy = shipped()
    policy["semantic"]["block_threshold"] = 0.1

    response = put_policy(client, headers, policy, expected=1)

    assert response.status_code == 409
    assert response.json()["reason_code"] == "VERSION_CONFLICT"
    assert active(client, headers)["policy_version"] == 2
    assert active(client, headers)["policy"]["semantic"]["block_threshold"] == 0.8


@pytest.mark.usefixtures("active_config")
@pytest.mark.parametrize(
    "breaks",
    [
        lambda p: p["controls"].update(access=False),
        lambda p: p["acl"]["analyst"]["fields"].append("secret"),
        lambda p: p["outbound_fields"].append("personal_id"),
        lambda p: p["models"].update(summary="gpt-4o"),
        lambda p: p.update(note="SENTINEL-POLICY-NOTE-91f2"),
        lambda p: p["redaction"]["entities"].pop("PL_PESEL"),
    ],
)
def test_invalid_update_keeps_the_previous_version(
    client: TestClient, headers: Headers, breaks: Callable[[dict[str, Any]], None]
) -> None:
    before = active(client, headers)
    policy = shipped()
    breaks(policy)

    response = put_policy(client, headers, policy, expected=1)

    assert response.status_code == 422
    assert response.json()["reason_code"] == "INVALID_INPUT"
    assert "SENTINEL-POLICY-NOTE-91f2" not in response.text
    assert active(client, headers) == before


@pytest.mark.usefixtures("active_config")
@pytest.mark.parametrize("identity", ["analyst-a", "reviewer-a"])
def test_only_the_admin_changes_the_policy(
    client: TestClient, headers: Headers, identity: str
) -> None:
    body = {"schema_version": 1, "expected_version": 1, "policy": shipped()}

    response = client.put("/admin/policy", json=body, headers=headers[identity])

    assert response.status_code == 403
    assert active(client, headers)["policy_version"] == 1


@pytest.mark.usefixtures("active_config")
def test_next_request_follows_the_new_field_scope(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    task_id = new_task("reviewer-a")
    before = execute("reviewer-a", task_id, "documents.read", document_id="doc-a").json()
    policy = shipped()
    policy["acl"]["reviewer"]["fields"].remove("review_note")
    assert put_policy(client, headers, policy, expected=1).status_code == 200

    after = execute("reviewer-a", task_id, "documents.read", document_id="doc-a").json()

    assert (before["policy_version"], after["policy_version"]) == (1, 2)
    assert "review_note" in before["output"]["fields"]
    assert "review_note" not in after["output"]["fields"]
    assert "review_note" in after["redacted_fields"]
    [*_, result] = events_of(client, headers, after["request_id"])
    assert result["policy_version"] == 2


@pytest.mark.usefixtures("active_config")
def test_tool_removed_from_a_role_is_denied_before_the_adapter(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    policy = shipped()
    policy["acl"]["analyst"]["tools"] = ["documents.summarize"]
    assert put_policy(client, headers, policy, expected=1).status_code == 200

    response = execute("analyst-a", new_task("analyst-a"), "documents.read", document_id="doc-a")

    body = response.json()
    assert (response.status_code, body["decision"], body["reason_code"]) == (
        200,
        "DENY",
        "TOOL_FORBIDDEN",
    )
    assert client.app.state.documents.read_count == 0
    steps = [
        (e["control_id"], e["stage"], e["reason_code"])
        for e in events_of(client, headers, body["request_id"])
    ]
    assert steps == [
        ("gateway", "admission", "OK"),
        ("access", "pre_document", "TOOL_FORBIDDEN"),
    ]


@pytest.mark.usefixtures("active_config")
def test_detection_thresholds_follow_the_policy(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    policy = shipped()
    policy["redaction"]["entities"]["PHONE_NUMBER"]["threshold"] = 0.95
    assert put_policy(client, headers, policy, expected=1).status_code == 200

    body = execute("analyst-a", new_task("analyst-a"), "documents.read", document_id="doc-a")

    notes = body.json()["output"]["fields"]["notes"]
    assert "+48 22 555 01 23" in notes  # below the stricter threshold
    assert "<EMAIL_ADDRESS>" in notes and "<SECRET>" in notes


@pytest.mark.usefixtures("active_config")
def test_one_request_uses_the_version_pinned_at_admission(
    client: TestClient,
    headers: Headers,
    db_path: Path,
    new_task: NewTask,
    execute: Execute,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    narrower = config_document("policy")
    assert isinstance(narrower, Policy)
    reviewer = narrower.acl.reviewer.model_copy(
        update={"fields": ("company_name", "status", "notes")}
    )
    narrower = narrower.model_copy(
        update={"acl": narrower.acl.model_copy(update={"reviewer": reviewer})}
    )
    documents = client.app.state.documents
    read = documents.read

    def read_while_the_policy_changes(entry):
        activate_config(db_path, "policy", narrower)
        return read(entry)

    monkeypatch.setattr(documents, "read", read_while_the_policy_changes)
    task_id = new_task("reviewer-a")

    during = execute("reviewer-a", task_id, "documents.read", document_id="doc-a").json()
    monkeypatch.setattr(documents, "read", read)
    after = execute("reviewer-a", task_id, "documents.read", document_id="doc-a").json()

    assert during["policy_version"] == 1
    assert "review_note" in during["output"]["fields"]
    assert {e["policy_version"] for e in events_of(client, headers, during["request_id"])} == {1}
    assert after["policy_version"] == 2
    assert "review_note" not in after["output"]["fields"]


@pytest.mark.usefixtures("active_config")
def test_invalid_stored_policy_stops_protected_operations(
    client: TestClient, headers: Headers, db_path: Path, new_task: NewTask, execute: Execute
) -> None:
    task_id = new_task("analyst-a")
    body = json.dumps({"schema_version": 1})
    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute(
            "INSERT INTO config_versions (kind, version, body, sha256, created_at, created_by)"
            " VALUES ('policy', 2, ?, ?, '2026-10-03T00:00:00Z', 'test')",
            (body, hashlib.sha256(body.encode()).hexdigest()),
        )
        conn.execute("UPDATE active_config SET version = 2 WHERE kind = 'policy'")

    response = execute("analyst-a", task_id, "documents.read", document_id="doc-a")

    assert response.status_code == 503
    assert response.json()["reason_code"] == "INVALID_CONFIG"
    assert client.app.state.documents.read_count == 0
    [event] = events_of(client, headers, response.json()["request_id"])
    assert (event["reason_code"], event["policy_version"]) == ("INVALID_CONFIG", 2)


@pytest.mark.usefixtures("active_config")
def test_unavailable_pii_engine_stops_the_read(
    client: TestClient,
    headers: Headers,
    new_task: NewTask,
    execute: Execute,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_engine(languages: tuple[str, ...]):
        raise PiiEngineUnavailable("missing pipeline")

    monkeypatch.setattr(client.app.state.gateway, "_pii_engine", no_engine)

    response = execute("analyst-a", new_task("analyst-a"), "documents.read", document_id="doc-a")

    body = response.json()
    assert (body["decision"], body["reason_code"], body["execution_status"]) == (
        "DENY",
        "PII_ENGINE_UNAVAILABLE",
        "NOT_CALLED",
    )
    assert client.app.state.documents.read_count == 0
    [*_, event] = events_of(client, headers, body["request_id"])
    assert (event["control_id"], event["stage"]) == ("redaction", "pre_document")


class FailingEngine:
    def analyze(self, text: str, thresholds: dict[str, float]) -> list[PiiFinding]:
        raise PiiEngineUnavailable("analysis failed")


@pytest.mark.usefixtures("active_config")
def test_failure_during_redaction_withholds_the_read_document(
    client: TestClient,
    headers: Headers,
    new_task: NewTask,
    execute: Execute,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client.app.state.gateway, "_pii_engine", lambda languages: FailingEngine())

    response = execute("analyst-a", new_task("analyst-a"), "documents.read", document_id="doc-a")

    body = response.json()
    assert (body["decision"], body["reason_code"], body["execution_status"]) == (
        "DENY",
        "PII_ENGINE_UNAVAILABLE",
        "SUCCEEDED",  # the document was read; nothing from it is returned
    )
    assert body["output"] is None
    assert "Fabrikam" not in response.text
    [*_, event] = events_of(client, headers, body["request_id"])
    assert (event["control_id"], event["stage"], event["adapter_calls"]["document_read"]) == (
        "redaction",
        "pre_detector",
        "SUCCEEDED",
    )


@pytest.mark.usefixtures("active_config")
def test_audit_counts_masked_entities_without_values(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    body = execute("reviewer-a", new_task("reviewer-a"), "documents.read", document_id="doc-a")

    [event] = [
        event
        for event in events_of(client, headers, body.json()["request_id"])
        if event["control_id"] == "redaction"
    ]
    assert event["redacted_entity_counts"] == {
        "EMAIL_ADDRESS": 1,
        "IBAN_CODE": 1,
        "PHONE_NUMBER": 1,
        "SECRET": 1,
    }
    assert event["redacted_fields"] == ["email", "personal_id", "secret"]
