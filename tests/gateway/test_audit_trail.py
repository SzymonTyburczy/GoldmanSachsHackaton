"""Audit events written by the gateway: one per step, with the adapter calls so far."""

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.gateway.support import activate_config, break_audit

Execute = Callable[..., httpx.Response]
NewTask = Callable[..., str]
Headers = dict[str, dict[str, str]]

NOTHING_CALLED = {
    "document_read": "NOT_CALLED",
    "token_count": "NOT_CALLED",
    "detector": "NOT_CALLED",
    "summary": "NOT_CALLED",
    "artifact_admit": "NOT_CALLED",
}


def admin_events(client: TestClient, headers: Headers, **filters: str) -> list[dict]:
    response = client.get(
        "/admin/events", params={"limit": 200, **filters}, headers=headers["admin"]
    )
    assert response.status_code == 200, response.text
    return response.json()["events"]


def steps(events: list[dict]) -> list[tuple[str, str, str, str, str]]:
    return [
        (
            event["control_id"],
            event["stage"],
            event["decision"],
            event["reason_code"],
            event["execution_status"],
        )
        for event in events
    ]


def calls(**statuses: str) -> dict[str, str]:
    return NOTHING_CALLED | statuses


@pytest.mark.usefixtures("active_config")
def test_allowed_read_records_admission_intent_and_result(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    task_id = new_task("analyst-a")

    response = execute("analyst-a", task_id, "documents.read", document_id="doc-a")

    body = response.json()
    events = admin_events(client, headers, request_id=body["request_id"])
    assert steps(events) == [
        ("gateway", "admission", "ALLOW", "OK", "NOT_CALLED"),
        ("access", "pre_document", "ALLOW", "OK", "STARTED"),
        ("redaction", "pre_detector", "REDACT", "PII_REDACTED", "SUCCEEDED"),
        ("budget", "pre_detector", "ALLOW", "OK", "STARTED"),
        ("semantic", "pre_detector", "ALLOW", "OK", "SUCCEEDED"),
    ]
    assert [event["adapter_calls"] for event in events] == [
        NOTHING_CALLED,
        calls(document_read="STARTED"),
        calls(document_read="SUCCEEDED"),
        calls(document_read="SUCCEEDED", detector="STARTED"),
        calls(document_read="SUCCEEDED", detector="SUCCEEDED"),
    ]
    assert body["audit_event_ids"] == [event["event_id"] for event in events]
    assert events[2]["redacted_fields"] == body["redacted_fields"]
    assert [event["latency_ms"] is None for event in events] == [True, True, False, True, False]
    # The detector event carries its priced usage and the score; no other step has one.
    assert events[4]["usage"] == body["usage"]
    assert [usage["provider"] for usage in body["usage"]] == ["typesafe"]
    assert events[4]["model"] == "jev-1.13.0"
    assert events[4]["semantic"]["category"] == "benign"
    for event in events[:4]:
        assert (event["usage"], event["model"], event["semantic"]) == ([], None, None)
    for event in events:
        assert event["request_id"] == response.headers["X-Request-ID"]
        assert event["task_id"] == task_id
        assert (event["principal_id"], event["agent_id"], event["client_id"]) == (
            "analyst-a",
            "demo-agent",
            "client-a",
        )
        assert (event["tool"], event["policy_version"], event["feed_version"]) == (
            "documents.read",
            1,
            1,
        )


@pytest.mark.usefixtures("active_config")
@pytest.mark.parametrize("tool", ["documents.read", "documents.summarize"])
def test_document_b_denial_is_recorded_before_any_adapter(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute, tool: str
) -> None:
    arguments = {"document_id": "doc-b"}
    if tool == "documents.summarize":
        arguments["prompt"] = "Summarize this company."

    body = execute("analyst-a", new_task("analyst-a"), tool, **arguments).json()

    events = admin_events(client, headers, request_id=body["request_id"])
    assert steps(events) == [
        ("gateway", "admission", "ALLOW", "OK", "NOT_CALLED"),
        ("access", "pre_document", "DENY", "CLIENT_FORBIDDEN", "NOT_CALLED"),
    ]
    assert all(event["adapter_calls"] == NOTHING_CALLED for event in events)
    assert body["audit_event_ids"] == [event["event_id"] for event in events]
    assert client.app.state.documents.read_count == 0


@pytest.mark.usefixtures("active_config")
def test_unknown_document_leaves_the_same_trail_as_document_b(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    task_id = new_task("analyst-a")
    other = execute("analyst-a", task_id, "documents.read", document_id="doc-b").json()
    unknown = execute("analyst-a", task_id, "documents.read", document_id="doc-zz").json()

    varying = {"event_id", "request_id", "occurred_at"}

    def stable(request_id: str) -> list[dict]:
        events = admin_events(client, headers, request_id=request_id)
        return [{k: v for k, v in event.items() if k not in varying} for event in events]

    assert stable(unknown["request_id"]) == stable(other["request_id"])


@pytest.mark.usefixtures("active_config")
def test_summary_records_each_adapter_after_its_reservation(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    response = execute(
        "analyst-a",
        new_task("analyst-a"),
        "documents.summarize",
        document_id="doc-a",
        prompt="Summarize this company.",
    )

    body = response.json()
    events = admin_events(client, headers, request_id=body["request_id"])
    done = {"document_read": "SUCCEEDED", "detector": "SUCCEEDED"}
    assert steps(events) == [
        ("gateway", "admission", "ALLOW", "OK", "NOT_CALLED"),
        ("access", "pre_document", "ALLOW", "OK", "STARTED"),
        ("redaction", "pre_detector", "REDACT", "PII_REDACTED", "SUCCEEDED"),
        ("budget", "pre_detector", "ALLOW", "OK", "STARTED"),
        ("semantic", "pre_detector", "ALLOW", "OK", "SUCCEEDED"),
        ("budget", "pre_summary", "ALLOW", "OK", "STARTED"),
        ("budget", "pre_summary", "ALLOW", "OK", "STARTED"),
        ("redaction", "post_output", "ALLOW", "OK", "SUCCEEDED"),
    ]
    assert [event["adapter_calls"] for event in events[5:]] == [
        calls(**done, token_count="STARTED"),
        calls(**done, token_count="SUCCEEDED", summary="STARTED"),
        calls(**done, token_count="SUCCEEDED", summary="SUCCEEDED"),
    ]
    # Fields that never reach a provider, by name; the response reports the same.
    assert events[2]["redacted_fields"] == ["email", "personal_id", "review_note", "secret"]
    assert body["redacted_fields"] == events[2]["redacted_fields"]
    assert [usage["provider"] for usage in events[7]["usage"]] == ["openai", "openai"]
    assert events[7]["model"] == "gpt-6-luna"
    assert body["usage"] == events[4]["usage"] + events[7]["usage"]
    assert body["audit_event_ids"] == [event["event_id"] for event in events]


@pytest.mark.usefixtures("active_config")
def test_attempts_on_foreign_and_unknown_tasks_are_recorded_for_the_admin(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    reviewers_task = new_task("reviewer-a")
    unknown_task = str(uuid4())

    for task_id in (reviewers_task, unknown_task):
        response = execute("analyst-a", task_id, "documents.read", document_id="doc-a")
        assert response.status_code == 403

        [event] = admin_events(client, headers, task_id=task_id)
        assert steps([event]) == [("access", "admission", "DENY", "TASK_FORBIDDEN", "NOT_CALLED")]
        assert event["request_id"] == response.json()["request_id"]
        assert (event["principal_id"], event["client_id"]) == ("analyst-a", None)
        assert event["adapter_calls"] == NOTHING_CALLED

    owner_view = client.get(f"/v1/tasks/{reviewers_task}/events", headers=headers["reviewer-a"])
    assert owner_view.json()["events"] == []  # another principal's attempt is not the owner's


def test_missing_configuration_is_recorded(
    client: TestClient, headers: Headers, db_path: Path, new_task: NewTask, execute: Execute
) -> None:
    activate_config(db_path, "policy")  # feed missing

    response = execute("analyst-a", new_task("analyst-a"), "documents.read", document_id="doc-a")

    assert response.status_code == 503
    [event] = admin_events(client, headers, request_id=response.json()["request_id"])
    assert steps([event]) == [("gateway", "admission", "DENY", "INVALID_CONFIG", "NOT_CALLED")]
    assert (event["policy_version"], event["feed_version"]) == (1, None)
    assert event["client_id"] == "client-a"


@pytest.mark.usefixtures("active_config")
def test_audit_counts_every_document_adapter_call(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    analysts_task = new_task("analyst-a")
    for document_id in ("doc-a", "doc-b", "doc-a", "doc-zz"):
        execute("analyst-a", analysts_task, "documents.read", document_id=document_id)
    execute("reviewer-a", new_task("reviewer-a"), "documents.read", document_id="doc-a")
    execute("analyst-a", new_task("reviewer-a"), "documents.read", document_id="doc-a")

    events = admin_events(client, headers)
    started = [e for e in events if e["adapter_calls"]["document_read"] == "STARTED"]
    finished = {
        e["request_id"] for e in events if e["adapter_calls"]["document_read"] == "SUCCEEDED"
    }
    assert len(started) == len(finished) == client.app.state.documents.read_count == 3


@pytest.mark.usefixtures("active_config")
@pytest.mark.parametrize("stage", ["admission", "pre_document"])
def test_unrecorded_step_before_the_adapter_stops_the_request(
    client: TestClient,
    headers: Headers,
    db_path: Path,
    new_task: NewTask,
    execute: Execute,
    caplog: pytest.LogCaptureFixture,
    stage: str,
) -> None:
    task_id = new_task("analyst-a")
    break_audit(db_path, stage)

    with caplog.at_level(logging.DEBUG):
        for document_id in ("doc-a", "doc-b"):
            response = execute("analyst-a", task_id, "documents.read", document_id=document_id)

            assert response.status_code == 503
            assert response.json()["reason_code"] == "AUDIT_UNAVAILABLE"
            events = admin_events(client, headers, request_id=response.json()["request_id"])
            assert all(event["stage"] != stage for event in events)

    assert client.app.state.documents.read_count == 0
    logged = [record.getMessage() for record in caplog.records if record.name == "app.audit"]
    assert len(logged) == 2
    for message in logged:  # identifiers and the error class only, no SQLite message
        assert message.startswith("audit event not stored: request_id=")
        assert message.endswith(f"stage={stage} error=IntegrityError")


@pytest.mark.usefixtures("active_config")
def test_unrecorded_result_withholds_the_output_but_reports_the_read(
    client: TestClient, headers: Headers, db_path: Path, new_task: NewTask, execute: Execute
) -> None:
    task_id = new_task("analyst-a")
    break_audit(db_path, "pre_detector")

    response = execute("analyst-a", task_id, "documents.read", document_id="doc-a")

    assert response.status_code == 200
    body = response.json()
    assert (body["decision"], body["reason_code"]) == ("DENY", "AUDIT_UNAVAILABLE")
    assert body["execution_status"] == "SUCCEEDED"  # the document was read
    assert body["adapter_calls"] == calls(document_read="SUCCEEDED")
    assert body["output"] is None
    assert "Fabrikam" not in response.text
    assert client.app.state.documents.read_count == 1
    # The stored intent stays STARTED: the outcome is left for reconciliation.
    events = admin_events(client, headers, request_id=body["request_id"])
    assert steps(events) == [
        ("gateway", "admission", "ALLOW", "OK", "NOT_CALLED"),
        ("access", "pre_document", "ALLOW", "OK", "STARTED"),
    ]
    assert body["audit_event_ids"] == [event["event_id"] for event in events]
