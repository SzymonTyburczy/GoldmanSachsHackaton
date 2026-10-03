"""Reading the audit: task history for the owner, events and JSONL export for the admin."""

import json
import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app import audit
from app.contracts import AuditEvent
from app.settings import DEFAULT_DOCUMENTS_DIR
from tests.gateway.support import TOKENS

pytestmark = pytest.mark.usefixtures("active_config")

Execute = Callable[..., httpx.Response]
NewTask = Callable[..., str]
Headers = dict[str, dict[str, str]]


def read(execute: Execute, identity: str, task_id: str, document_id: str = "doc-a") -> dict:
    return execute(identity, task_id, "documents.read", document_id=document_id).json()


def history(client: TestClient, headers: Headers, identity: str, task_id: str, **params: int):
    return client.get(f"/v1/tasks/{task_id}/events", params=params, headers=headers[identity])


def all_pages(client: TestClient, url: str, headers: dict[str, str], limit: int) -> list[dict]:
    events: list[dict] = []
    after = 0
    while True:
        page = client.get(url, params={"limit": limit, "after": after}, headers=headers).json()
        assert len(page["events"]) <= limit
        events += page["events"]
        if page["next_after"] is None:
            return events
        after = page["next_after"]


def test_owner_and_admin_read_the_same_task_history(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    task_id = new_task("analyst-a")
    first = read(execute, "analyst-a", task_id)
    second = read(execute, "analyst-a", task_id, "doc-b")
    read(execute, "analyst-a", new_task("analyst-a"))  # another task of the same owner

    owner = history(client, headers, "analyst-a", task_id)
    admin = history(client, headers, "admin", task_id)

    assert owner.status_code == admin.status_code == 200
    assert owner.json() == admin.json()
    assert owner.headers["Cache-Control"] == "no-store"
    events = owner.json()["events"]
    assert [event["event_id"] for event in events] == (
        first["audit_event_ids"] + second["audit_event_ids"]
    )
    assert {event["task_id"] for event in events} == {task_id}
    assert owner.json()["next_after"] is None


def test_task_history_is_refused_to_others(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    task_id = new_task("reviewer-a")
    read(execute, "reviewer-a", task_id)

    foreign = history(client, headers, "analyst-a", task_id)
    unknown = history(client, headers, "analyst-a", str(uuid4()))
    anonymous = client.get(f"/v1/tasks/{task_id}/events")

    for response in (foreign, unknown):
        assert response.status_code == 403
        assert response.json()["reason_code"] == "TASK_FORBIDDEN"
        assert "event_id" not in response.text
    assert anonymous.status_code == 401


def test_history_pages_follow_the_write_order(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    task_id = new_task("analyst-a")
    ids: list[str] = []
    for document_id in ("doc-a", "doc-b", "doc-a"):
        ids += read(execute, "analyst-a", task_id, document_id)["audit_event_ids"]

    for limit in (1, 2, 3, len(ids), 200):
        events = all_pages(client, f"/v1/tasks/{task_id}/events", headers["analyst-a"], limit)
        assert [event["event_id"] for event in events] == ids

    last = history(client, headers, "analyst-a", task_id, limit=len(ids))
    assert last.json()["next_after"] is None


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"after": -1}])
def test_page_bounds_are_enforced(
    client: TestClient, headers: Headers, new_task: NewTask, params: dict[str, int]
) -> None:
    task_id = new_task("analyst-a")

    for response in (
        history(client, headers, "analyst-a", task_id, **params),
        client.get("/admin/events", params=params, headers=headers["admin"]),
    ):
        assert response.status_code == 422
        assert response.json()["reason_code"] == "INVALID_INPUT"


def test_admin_events_filter_by_task_and_request(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    analysts_task = new_task("analyst-a")
    reviewers_task = new_task("reviewer-a")
    first = read(execute, "analyst-a", analysts_task)
    read(execute, "reviewer-a", reviewers_task)
    read(execute, "analyst-a", reviewers_task)  # refused: foreign task

    everything = all_pages(client, "/admin/events", headers["admin"], limit=2)
    by_task = client.get(
        "/admin/events", params={"task_id": reviewers_task}, headers=headers["admin"]
    ).json()["events"]
    by_request = client.get(
        "/admin/events", params={"request_id": first["request_id"]}, headers=headers["admin"]
    ).json()["events"]

    assert len(everything) == 7  # 3 + 3 + 1
    assert [e["principal_id"] for e in by_task] == ["reviewer-a"] * 3 + ["analyst-a"]
    assert [e["event_id"] for e in by_request] == first["audit_event_ids"]


def test_export_is_jsonl_from_the_same_store(
    client: TestClient,
    headers: Headers,
    new_task: NewTask,
    execute: Execute,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "EXPORT_BATCH", 2)  # several batches with a few events
    task_id = new_task("analyst-a")
    for document_id in ("doc-a", "doc-b", "doc-zz"):
        read(execute, "analyst-a", task_id, document_id)

    response = client.get("/admin/audit/export", headers=headers["admin"])

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/x-ndjson"
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="controlproof-audit.jsonl"'
    )
    assert response.headers["Cache-Control"] == "no-store"
    lines = response.text.splitlines()
    assert response.text.endswith("\n")
    exported = [AuditEvent.model_validate_json(line).model_dump(mode="json") for line in lines]
    assert exported == all_pages(client, "/admin/events", headers["admin"], limit=200)
    assert len(exported) == 7  # 3 + 2 + 2


@pytest.mark.parametrize("identity", ["analyst-a", "reviewer-a"])
def test_export_requires_the_admin_role(
    client: TestClient, headers: Headers, identity: str
) -> None:
    response = client.get("/admin/audit/export", headers=headers[identity])

    assert response.status_code == 403
    assert response.json()["reason_code"] == "ADMIN_REQUIRED"


def test_empty_audit_exports_nothing(client: TestClient, headers: Headers) -> None:
    response = client.get("/admin/audit/export", headers=headers["admin"])

    assert response.status_code == 200
    assert response.text == ""


def test_audit_and_logs_hold_no_tokens_or_document_values(
    client: TestClient,
    headers: Headers,
    db_path: Path,
    new_task: NewTask,
    execute: Execute,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        for identity in TOKENS:
            task_id = new_task(identity)
            for document_id in ("doc-a", "doc-b", "doc-zz"):
                read(execute, identity, task_id, document_id)
        read(execute, "analyst-a", new_task("reviewer-a"))
        execute(
            "analyst-a",
            new_task("analyst-a"),
            "documents.summarize",
            document_id="doc-a",
            prompt="PROMPT-SENTINEL-41c9 summarize",
        )
        exported = client.get("/admin/audit/export", headers=headers["admin"]).text

    with closing(sqlite3.connect(db_path)) as conn:
        database = "\n".join(conn.iterdump())
    assert "audit_events" in database
    forbidden = list(TOKENS.values()) + ["PROMPT-SENTINEL-41c9"]
    for document_id in ("doc-a", "doc-b"):
        path = DEFAULT_DOCUMENTS_DIR / "content" / f"{document_id}.json"
        fields = json.loads(path.read_text(encoding="utf-8"))["fields"]
        # "status" holds a short word such as "active", which also names a table.
        forbidden += [value for name, value in fields.items() if name != "status"]
    for text in (exported, database, caplog.text):
        for value in forbidden:
            assert value not in text
