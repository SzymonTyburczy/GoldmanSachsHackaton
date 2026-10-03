"""Append-only audit log (docs/WSPOLNE_USTALENIA.md, sections 4 and 8).

Every stored event is a validated ``AuditEvent``: identifiers, enums, field names,
entity counts and provider usage. The model has no field for request bodies, prompts,
document values, access tokens or SDK errors, so none of these can be written here.
The ``audit_events`` table rejects UPDATE and DELETE.

``RequestTrail`` writes the events of one gateway request in order. The event before an
adapter call is the intent record: if it cannot be stored, the adapter is not called.
"""

import logging
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import closing
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from app import db
from app.auth import Principal
from app.contracts import (
    AdapterCalls,
    AuditEvent,
    AuditEventPage,
    ControlResult,
    ExecutionStatus,
    Tool,
    utc_now,
)

logger = logging.getLogger(__name__)

AdapterName = Literal["document_read", "token_count", "detector", "summary", "artifact_admit"]

EXPORT_BATCH = 500

_SELECT_PAGE = """
    SELECT seq, event_json FROM audit_events
    WHERE seq > ?
      AND (? IS NULL OR task_id = ?)
      AND (? IS NULL OR principal_id = ?)
      AND (? IS NULL OR request_id = ?)
    ORDER BY seq
    LIMIT ?
"""


class AuditUnavailableError(RuntimeError):
    """An audit event was not stored. The gateway must not start the next adapter."""


def append(db_path: Path, event: AuditEvent) -> None:
    """Store one event durably (autocommit) or raise ``AuditUnavailableError``."""
    try:
        with closing(db.connect(db_path)) as conn:
            conn.execute(
                "INSERT INTO audit_events (event_id, request_id, task_id, principal_id,"
                " occurred_at, control_id, decision, reason_code, stage, execution_status,"
                " policy_version, feed_version, event_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(event.event_id),
                    str(event.request_id),
                    None if event.task_id is None else str(event.task_id),
                    event.principal_id,
                    db.to_db_time(event.occurred_at),
                    event.control_id,
                    event.decision,
                    event.reason_code,
                    event.stage,
                    event.execution_status,
                    event.policy_version,
                    event.feed_version,
                    event.model_dump_json(),
                ),
            )
    except sqlite3.Error as exc:
        # Only identifiers and the error class: SQLite messages are not needed to act.
        logger.error(
            "audit event not stored: request_id=%s stage=%s error=%s",
            event.request_id,
            event.stage,
            type(exc).__name__,
        )
        raise AuditUnavailableError("audit event not stored") from None


def list_events(
    conn: sqlite3.Connection,
    *,
    limit: int,
    after: int = 0,
    task_id: UUID | None = None,
    principal_id: str | None = None,
    request_id: UUID | None = None,
) -> AuditEventPage:
    """Events in write order after the cursor ``after``, optionally filtered."""
    task = None if task_id is None else str(task_id)
    request = None if request_id is None else str(request_id)
    rows = conn.execute(
        _SELECT_PAGE,
        (after, task, task, principal_id, principal_id, request, request, limit + 1),
    ).fetchall()
    page = rows[:limit]
    return AuditEventPage(
        events=tuple(AuditEvent.model_validate_json(row["event_json"]) for row in page),
        next_after=page[-1]["seq"] if len(rows) > limit else None,
    )


def export_lines(db_path: Path) -> Iterator[str]:
    """All events as JSON Lines, oldest first, read in batches from ``audit_events``."""
    after = 0
    while True:
        with closing(db.connect(db_path)) as conn:
            page = list_events(conn, limit=EXPORT_BATCH, after=after)
        for event in page.events:
            yield event.model_dump_json() + "\n"
        if page.next_after is None:
            return
        after = page.next_after


class RequestTrail:
    """Audit events of one gateway request, written one at a time and in order.

    Identifiers come from the authenticated principal and, once known, from the stored
    task and the pinned configuration. ``calls`` is the execution status of each adapter
    so far. Every event carries a snapshot of it, so a denial after an adapter call still
    shows that call.
    """

    def __init__(self, db_path: Path, request_id: UUID, principal: Principal, tool: Tool) -> None:
        self._db_path = db_path
        self.request_id = request_id
        self._principal_id = principal.principal_id
        self._agent_id = principal.agent_id
        self._tool = tool
        self.task_id: UUID | None = None
        self.client_id: str | None = None
        self.policy_version: int | None = None
        self.feed_version: int | None = None
        self.calls = AdapterCalls()
        self.event_ids: list[UUID] = []

    def record(
        self,
        result: ControlResult,
        execution_status: ExecutionStatus = ExecutionStatus.NOT_CALLED,
        *,
        starting: AdapterName | None = None,
        latency_ms: int | None = None,
        entity_counts: Mapping[str, int] | None = None,
    ) -> None:
        """Store the outcome of one step.

        With ``starting`` the event is the intent record of that adapter: it is stored
        with the adapter ``STARTED``, and ``calls`` changes only after the write succeeds.
        """
        calls = self.calls
        if starting is not None:
            calls = calls.model_copy(update={starting: ExecutionStatus.STARTED})
            execution_status = ExecutionStatus.STARTED
        event = AuditEvent(
            event_id=uuid4(),
            request_id=self.request_id,
            task_id=self.task_id,
            principal_id=self._principal_id,
            agent_id=self._agent_id,
            client_id=self.client_id,
            occurred_at=utc_now(),
            tool=self._tool,
            control_id=result.control_id,
            decision=result.decision,
            reason_code=result.reason_code,
            stage=result.stage,
            execution_status=execution_status,
            adapter_calls=calls,
            latency_ms=latency_ms,
            model=None,
            policy_version=self.policy_version,
            feed_version=self.feed_version,
            redacted_fields=result.redacted_fields,
            redacted_entity_counts=dict(entity_counts or {}),
        )
        append(self._db_path, event)
        self.calls = calls
        self.event_ids.append(event.event_id)

    def finished(self, adapter: AdapterName, status: ExecutionStatus) -> None:
        """Note the real outcome of an adapter call, before its result event is written."""
        self.calls = self.calls.model_copy(update={adapter: status})

    @property
    def anything_called(self) -> bool:
        return self.calls != AdapterCalls()
