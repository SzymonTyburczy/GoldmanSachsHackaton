import json
from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.documents import DocumentAdapter
from app.settings import DEFAULT_DOCUMENTS_DIR

pytestmark = pytest.mark.usefixtures("active_config")

Execute = Callable[..., httpx.Response]
NewTask = Callable[..., str]


def stored_fields(document_id: str) -> dict[str, str]:
    path = DEFAULT_DOCUMENTS_DIR / "content" / f"{document_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))["fields"]


def adapter(client: TestClient) -> DocumentAdapter:
    return client.app.state.documents


def assert_nothing_from(document_id: str, response: httpx.Response) -> None:
    for value in stored_fields(document_id).values():
        assert value not in response.text


@pytest.mark.parametrize(
    ("identity", "visible", "removed"),
    [
        (
            "analyst-a",
            ["company_name", "notes", "status"],
            ["email", "personal_id", "review_note", "secret"],
        ),
        (
            "reviewer-a",
            ["company_name", "notes", "review_note", "status"],
            ["email", "personal_id", "secret"],
        ),
        (
            "admin",
            ["company_name", "notes", "review_note", "status"],
            ["email", "personal_id", "secret"],
        ),
    ],
)
def test_owner_reads_document_a_within_the_role_scope(
    client: TestClient,
    new_task: NewTask,
    execute: Execute,
    identity: str,
    visible: list[str],
    removed: list[str],
) -> None:
    task_id = new_task(identity)

    response = execute(identity, task_id, "documents.read", document_id="doc-a")

    assert response.status_code == 200
    body = response.json()
    assert (body["decision"], body["reason_code"]) == ("REDACT", "PII_REDACTED")
    assert body["execution_status"] == "SUCCEEDED"
    assert body["adapter_calls"]["document_read"] == "SUCCEEDED"
    assert body["policy_version"] == 1
    assert body["task_id"] == task_id
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert sorted(body["output"]["fields"]) == visible
    assert body["redacted_fields"] == removed
    expected = stored_fields("doc-a")
    assert body["output"]["fields"] == {name: expected[name] for name in visible}
    for name in removed:
        assert expected[name] not in response.text
    assert adapter(client).reads == {"doc-a": 1}


@pytest.mark.parametrize("tool", ["documents.read", "documents.summarize"])
def test_document_b_is_denied_before_the_adapter(
    client: TestClient, new_task: NewTask, execute: Execute, tool: str
) -> None:
    arguments = {"document_id": "doc-b"}
    if tool == "documents.summarize":
        arguments["prompt"] = "Summarize this company."

    response = execute("analyst-a", new_task("analyst-a"), tool, **arguments)

    assert response.status_code == 200
    body = response.json()
    assert (body["decision"], body["reason_code"]) == ("DENY", "CLIENT_FORBIDDEN")
    assert body["output"] is None
    assert body["execution_status"] == "NOT_CALLED"
    assert set(body["adapter_calls"].values()) == {"NOT_CALLED"}
    assert adapter(client).read_count == 0
    assert_nothing_from("doc-b", response)


def test_unknown_document_is_denied_like_document_b(
    client: TestClient, new_task: NewTask, execute: Execute
) -> None:
    task_id = new_task("analyst-a")
    other_client = execute("analyst-a", task_id, "documents.read", document_id="doc-b").json()
    unknown = execute("analyst-a", task_id, "documents.read", document_id="doc-zz").json()

    ignore = {"request_id", "audit_event_ids"}
    assert {k: v for k, v in unknown.items() if k not in ignore} == {
        k: v for k, v in other_client.items() if k not in ignore
    }
    assert adapter(client).read_count == 0


def test_foreign_task_is_refused_before_the_adapter(
    client: TestClient, new_task: NewTask, execute: Execute
) -> None:
    reviewers_task = new_task("reviewer-a")

    for identity in ("analyst-a", "admin"):  # admin executes only in its own tasks
        response = execute(identity, reviewers_task, "documents.read", document_id="doc-a")
        assert response.status_code == 403
        assert response.json()["reason_code"] == "TASK_FORBIDDEN"
        assert_nothing_from("doc-a", response)

    unknown = execute("analyst-a", str(uuid4()), "documents.read", document_id="doc-a")
    assert unknown.status_code == 403
    assert adapter(client).read_count == 0


def test_missing_token_never_reaches_the_adapter(
    client: TestClient, new_task: NewTask, execute: Execute
) -> None:
    response = execute(None, new_task("analyst-a"), "documents.read", document_id="doc-a")

    assert response.status_code == 401
    assert adapter(client).read_count == 0


def test_summary_is_not_built_and_reads_nothing(
    client: TestClient, new_task: NewTask, execute: Execute
) -> None:
    response = execute(
        "analyst-a",
        new_task("analyst-a"),
        "documents.summarize",
        document_id="doc-a",
        prompt="Summarize this company.",
    )

    assert response.status_code == 501
    assert response.json()["reason_code"] == "NOT_IMPLEMENTED"
    assert adapter(client).read_count == 0


def test_artifacts_are_not_built(client: TestClient, new_task: NewTask, execute: Execute) -> None:
    task_id = new_task("analyst-a")

    response = execute("analyst-a", task_id, "artifacts.admit", artifact_id="artifact-1")

    assert response.status_code == 501
