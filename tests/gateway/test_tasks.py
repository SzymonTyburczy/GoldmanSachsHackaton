import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.auth import ANALYST_A, Principal
from app.contracts import Decision, ReasonCode, Role
from app.controls import access
from app.policy import Policy
from app.tasks import Task, TaskLimitReached, create_task
from tests.gateway.support import activate_config, config_document


def stored_tasks(db_path: Path) -> list[sqlite3.Row]:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM tasks").fetchall()


@pytest.mark.usefixtures("active_config")
def test_task_is_owned_by_the_caller_for_the_requested_client(
    client: TestClient, headers: dict[str, dict[str, str]], db_path: Path
) -> None:
    response = client.post(
        "/v1/tasks",
        json={"schema_version": 1, "client_id": "client-a"},
        headers=headers["reviewer-a"],
    )

    assert response.status_code == 201
    task = response.json()
    UUID(task["task_id"])
    assert task["principal_id"] == "reviewer-a"
    assert task["client_id"] == "client-a"
    assert datetime.fromisoformat(task["created_at"]).utcoffset() == timedelta(0)
    [row] = stored_tasks(db_path)
    assert (row["task_id"], row["principal_id"], row["client_id"]) == (
        task["task_id"],
        "reviewer-a",
        "client-a",
    )
    assert datetime.fromisoformat(row["created_at"]) == datetime.fromisoformat(task["created_at"])


@pytest.mark.parametrize("client_id", ["client-b", "client-unknown"])
def test_task_for_a_client_outside_the_scope_is_refused(
    client: TestClient, headers: dict[str, dict[str, str]], db_path: Path, client_id: str
) -> None:
    for identity in ("analyst-a", "admin"):
        response = client.post(
            "/v1/tasks",
            json={"schema_version": 1, "client_id": client_id},
            headers=headers[identity],
        )

        assert response.status_code == 403
        assert response.json()["reason_code"] == "CLIENT_FORBIDDEN"
    assert stored_tasks(db_path) == []


@pytest.mark.parametrize("forged", ["principal_id", "agent_id", "task_id", "created_at"])
def test_server_assigned_task_fields_cannot_be_sent(
    client: TestClient, headers: dict[str, dict[str, str]], db_path: Path, forged: str
) -> None:
    body = {"schema_version": 1, "client_id": "client-a", forged: "admin"}

    response = client.post("/v1/tasks", json=body, headers=headers["analyst-a"])

    assert response.status_code == 422
    assert stored_tasks(db_path) == []


@pytest.mark.usefixtures("active_config")
def test_owner_and_admin_can_read_a_task(
    client: TestClient, headers: dict[str, dict[str, str]], new_task: Callable[..., str]
) -> None:
    task_id = new_task("analyst-a")

    for identity in ("analyst-a", "admin"):
        response = client.get(f"/v1/tasks/{task_id}", headers=headers[identity])
        assert response.status_code == 200
        assert response.json()["principal_id"] == "analyst-a"


@pytest.mark.usefixtures("active_config")
def test_foreign_and_unknown_tasks_are_refused_alike(
    client: TestClient, headers: dict[str, dict[str, str]], new_task: Callable[..., str]
) -> None:
    foreign = client.get(f"/v1/tasks/{new_task('reviewer-a')}", headers=headers["analyst-a"])
    unknown = client.get(f"/v1/tasks/{uuid4()}", headers=headers["analyst-a"])

    for response in (foreign, unknown):
        assert response.status_code == 403
        assert response.json()["reason_code"] == "TASK_FORBIDDEN"
    assert set(foreign.json()) == set(unknown.json())


def test_task_check_follows_a_changed_client_scope() -> None:
    task = Task(uuid4(), "analyst-a", "demo-agent", "client-a", datetime.now(UTC))
    moved = Principal("analyst-a", Role.ANALYST, "demo-agent", frozenset({"client-b"}))

    assert access.check_task_owner(ANALYST_A, task).decision is Decision.ALLOW
    result = access.check_task_owner(moved, task)
    assert (result.decision, result.reason_code) == (Decision.DENY, ReasonCode.CLIENT_FORBIDDEN)


# --------------------------------------------------------------------------------------
# Task limit per principal (resources.max_tasks_per_principal)
# --------------------------------------------------------------------------------------


def limit_tasks(db_path: Path, max_tasks: int) -> None:
    base = config_document("policy")
    assert isinstance(base, Policy)
    resources = base.resources.model_copy(update={"max_tasks_per_principal": max_tasks})
    activate_config(db_path, "policy", base.model_copy(update={"resources": resources}))


def post_task(client: TestClient, headers: dict[str, dict[str, str]], identity: str) -> int:
    return client.post(
        "/v1/tasks", json={"schema_version": 1, "client_id": "client-a"}, headers=headers[identity]
    ).status_code


@pytest.mark.usefixtures("active_config")
def test_task_over_the_limit_is_refused_and_not_stored(
    client: TestClient,
    headers: dict[str, dict[str, str]],
    db_path: Path,
    execute: Callable[..., httpx.Response],
) -> None:
    limit_tasks(db_path, 2)

    statuses = [post_task(client, headers, "analyst-a") for _ in range(3)]

    assert statuses == [201, 201, 429]
    rows = stored_tasks(db_path)
    assert len(rows) == 2
    # The refused attempt does not block the tasks accepted before it.
    response = execute("analyst-a", rows[0]["task_id"], "documents.read", document_id="doc-a")
    assert response.json()["decision"] in ("ALLOW", "REDACT")
    # The limit is per principal.
    assert post_task(client, headers, "reviewer-a") == 201


@pytest.mark.usefixtures("active_config")
def test_refused_task_answers_with_budget_exceeded(
    client: TestClient, headers: dict[str, dict[str, str]], db_path: Path
) -> None:
    limit_tasks(db_path, 1)
    post_task(client, headers, "analyst-a")

    response = client.post(
        "/v1/tasks",
        json={"schema_version": 1, "client_id": "client-a"},
        headers=headers["analyst-a"],
    )

    assert response.status_code == 429
    assert response.json()["reason_code"] == "BUDGET_EXCEEDED"


@pytest.mark.usefixtures("active_config")
def test_parallel_task_creation_does_not_pass_the_limit(client: TestClient, db_path: Path) -> None:
    limit_tasks(db_path, 3)

    def attempt(_: int) -> bool:
        with closing(db.connect(db_path)) as conn:
            try:
                create_task(conn, ANALYST_A, "client-a")
            except TaskLimitReached:
                return False
            return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(12)))

    assert results.count(True) == 3
    assert len(stored_tasks(db_path)) == 3


def test_no_task_without_an_active_policy(
    client: TestClient, headers: dict[str, dict[str, str]], db_path: Path
) -> None:
    response = client.post(
        "/v1/tasks",
        json={"schema_version": 1, "client_id": "client-a"},
        headers=headers["analyst-a"],
    )

    assert response.status_code == 503
    assert response.json()["reason_code"] == "INVALID_CONFIG"
    assert stored_tasks(db_path) == []
