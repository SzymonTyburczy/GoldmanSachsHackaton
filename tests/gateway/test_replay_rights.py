"""A repeated Idempotency-Key returns the stored response only within the current rights.

Nothing is executed again either way; a refusal is audited and not stored, so the same
key replays once the rights are back.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.contracts import Tool
from app.policy import Policy
from tests.gateway.support import StubProviders, activate_config, config_document
from tests.gateway.test_artifacts import digest_of, put_feed, rule, store

NewTask = Callable[..., str]
Headers = dict[str, dict[str, str]]


def body_for(task_id: str, tool: str, **arguments: str) -> dict[str, Any]:
    return {"schema_version": 1, "task_id": task_id, "tool": tool, "arguments": arguments}


def post(
    client: TestClient, headers: Headers, identity: str, body: dict[str, Any], key: UUID
) -> httpx.Response:
    return client.post(
        "/v1/execute", json=body, headers=headers[identity] | {"Idempotency-Key": str(key)}
    )


def with_reviewer(db_path: Path, **access: Any) -> int:
    """Activate the shipped policy with the reviewer's access changed."""
    base = config_document("policy")
    assert isinstance(base, Policy)
    reviewer = base.acl.reviewer.model_copy(update=access)
    return activate_config(
        db_path,
        "policy",
        base.model_copy(update={"acl": base.acl.model_copy(update={"reviewer": reviewer})}),
    )


def restore_policy(db_path: Path) -> None:
    activate_config(db_path, "policy")


def denial(response: httpx.Response) -> tuple[str, str, Any]:
    body = response.json()
    return body["decision"], body["reason_code"], body["output"]


@pytest.mark.usefixtures("active_config")
def test_revoked_tool_stops_the_replay_without_running_again(
    client: TestClient, headers: Headers, providers: StubProviders, db_path: Path, new_task: NewTask
) -> None:
    body, key = body_for(new_task("reviewer-a"), "documents.read", document_id="doc-a"), uuid4()
    first = post(client, headers, "reviewer-a", body, key)
    assert first.json()["decision"] == "REDACT"
    assert "review_note" in first.json()["output"]["fields"]

    with_reviewer(db_path, tools=(Tool.DOCUMENTS_SUMMARIZE,))
    replay = post(client, headers, "reviewer-a", body, key)

    assert replay.status_code == 200
    assert denial(replay) == ("DENY", "TOOL_FORBIDDEN", None)
    assert replay.json()["adapter_calls"]["document_read"] == "NOT_CALLED"
    assert client.app.state.documents.read_count == 1
    assert len(providers.jev.states) == 1

    restore_policy(db_path)
    again = post(client, headers, "reviewer-a", body, key)
    assert again.json() == first.json()
    assert client.app.state.documents.read_count == 1


@pytest.mark.usefixtures("active_config")
def test_removed_field_stops_the_replay_of_a_read(
    client: TestClient, headers: Headers, db_path: Path, new_task: NewTask
) -> None:
    body, key = body_for(new_task("reviewer-a"), "documents.read", document_id="doc-a"), uuid4()
    post(client, headers, "reviewer-a", body, key)

    with_reviewer(db_path, fields=("company_name", "status", "notes"))
    replay = post(client, headers, "reviewer-a", body, key)

    assert denial(replay) == ("DENY", "TOOL_FORBIDDEN", None)
    assert client.app.state.documents.read_count == 1


@pytest.mark.usefixtures("active_config")
def test_narrower_outbound_scope_stops_the_replay_of_a_summary(
    client: TestClient, headers: Headers, providers: StubProviders, db_path: Path, new_task: NewTask
) -> None:
    body = body_for(
        new_task("analyst-a"), "documents.summarize", document_id="doc-a", prompt="Sum up."
    )
    key = uuid4()
    assert post(client, headers, "analyst-a", body, key).json()["decision"] in ("ALLOW", "REDACT")

    base = config_document("policy")
    assert isinstance(base, Policy)
    activate_config(
        db_path, "policy", base.model_copy(update={"outbound_fields": ("company_name",)})
    )
    replay = post(client, headers, "analyst-a", body, key)

    assert denial(replay) == ("DENY", "TOOL_FORBIDDEN", None)
    assert len(providers.luna.summarized) == 1


@pytest.mark.usefixtures("active_config")
def test_unrelated_policy_change_keeps_the_replay(
    client: TestClient, headers: Headers, providers: StubProviders, db_path: Path, new_task: NewTask
) -> None:
    body = body_for(
        new_task("analyst-a"), "documents.summarize", document_id="doc-a", prompt="Sum up."
    )
    key = uuid4()
    first = post(client, headers, "analyst-a", body, key)

    restore_policy(db_path)  # a new version with the same rights
    replay = post(client, headers, "analyst-a", body, key)

    assert replay.json() == first.json()
    assert len(providers.jev.states) == len(providers.luna.summarized) == 1


@pytest.mark.usefixtures("active_config")
def test_artifact_blocked_since_is_not_replayed(
    client: TestClient, headers: Headers, new_task: NewTask
) -> None:
    body = body_for(new_task("admin"), "artifacts.admit", artifact_id="art-summary-template")
    key = uuid4()
    assert post(client, headers, "admin", body, key).json()["decision"] == "ALLOW"

    assert (
        put_feed(client, headers, [rule(digest_of("art-summary-template"))], expected=1).status_code
        == 200
    )
    replay = post(client, headers, "admin", body, key)

    assert denial(replay) == ("DENY", "ARTIFACT_BLOCKED", None)
    assert store(client).read_count == 1
