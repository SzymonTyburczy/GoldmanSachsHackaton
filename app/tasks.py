"""Tasks: a unit of work owned by one principal for one client.

Owner, agent and client are fixed by the server when the task is created; later
requests read them from here instead of trusting the caller.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.auth import Principal
from app.contracts import TaskResponse, utc_now
from app.db import to_db_time


@dataclass(frozen=True, slots=True)
class Task:
    task_id: UUID
    principal_id: str
    agent_id: str
    client_id: str
    created_at: datetime

    def to_response(self) -> TaskResponse:
        return TaskResponse(
            task_id=self.task_id,
            principal_id=self.principal_id,
            agent_id=self.agent_id,
            client_id=self.client_id,
            created_at=self.created_at,
        )


def create_task(conn: sqlite3.Connection, principal: Principal, client_id: str) -> Task:
    """Insert a task for ``principal``. The caller has already checked the client scope."""
    task = Task(
        task_id=uuid4(),
        principal_id=principal.principal_id,
        agent_id=principal.agent_id,
        client_id=client_id,
        created_at=utc_now(),
    )
    conn.execute(
        "INSERT INTO tasks (task_id, principal_id, agent_id, client_id, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            str(task.task_id),
            task.principal_id,
            task.agent_id,
            task.client_id,
            to_db_time(task.created_at),
        ),
    )
    return task


def get_task(conn: sqlite3.Connection, task_id: UUID) -> Task | None:
    row = conn.execute(
        "SELECT task_id, principal_id, agent_id, client_id, created_at FROM tasks"
        " WHERE task_id = ?",
        (str(task_id),),
    ).fetchone()
    if row is None:
        return None
    return Task(
        task_id=UUID(row["task_id"]),
        principal_id=row["principal_id"],
        agent_id=row["agent_id"],
        client_id=row["client_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
