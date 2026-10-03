from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

from app import audit, db
from app.auth import ANALYST_A
from app.contracts import (
    AdapterCalls,
    ControlId,
    ControlResult,
    Decision,
    ExecutionStatus,
    ReasonCode,
    Stage,
    Tool,
)

ALLOW_DOCUMENT = ControlResult(
    control_id=ControlId.ACCESS,
    decision=Decision.ALLOW,
    reason_code=ReasonCode.OK,
    stage=Stage.PRE_DOCUMENT,
)


@pytest.fixture
def trail(db_path: Path) -> audit.RequestTrail:
    db.init_db(db_path)
    return audit.RequestTrail(db_path, uuid4(), ANALYST_A, Tool.DOCUMENTS_READ)


def stored(db_path: Path) -> list:
    with closing(db.connect(db_path)) as conn:
        return list(audit.list_events(conn, limit=200).events)


def test_intent_is_stored_before_the_call_is_noted(
    trail: audit.RequestTrail, db_path: Path
) -> None:
    trail.record(ALLOW_DOCUMENT, starting="document_read")
    trail.finished("document_read", ExecutionStatus.SUCCEEDED)

    [event] = stored(db_path)
    assert event.execution_status is ExecutionStatus.STARTED
    assert event.adapter_calls == AdapterCalls(document_read=ExecutionStatus.STARTED)
    assert trail.calls == AdapterCalls(document_read=ExecutionStatus.SUCCEEDED)
    assert trail.event_ids == [event.event_id]


def test_failed_intent_leaves_the_adapter_not_called(
    trail: audit.RequestTrail, db_path: Path
) -> None:
    db_path.unlink()
    db_path.mkdir()  # the database file cannot be opened any more

    with pytest.raises(audit.AuditUnavailableError):
        trail.record(ALLOW_DOCUMENT, starting="document_read")

    assert not trail.anything_called
    assert trail.event_ids == []


def test_stored_events_are_append_only(trail: audit.RequestTrail, db_path: Path) -> None:
    trail.record(ALLOW_DOCUMENT)
    [event] = stored(db_path)

    with pytest.raises(audit.AuditUnavailableError):
        audit.append(db_path, event)  # same event_id twice

    assert stored(db_path) == [event]


def test_pages_filter_by_principal_and_keep_the_cursor(db_path: Path) -> None:
    db.init_db(db_path)
    task_id = uuid4()
    for _ in range(3):
        trail = audit.RequestTrail(db_path, uuid4(), ANALYST_A, Tool.DOCUMENTS_READ)
        trail.task_id = task_id
        trail.record(ALLOW_DOCUMENT)

    with closing(db.connect(db_path)) as conn:
        first = audit.list_events(conn, limit=2, task_id=task_id, principal_id="analyst-a")
        rest = audit.list_events(
            conn, limit=2, after=first.next_after, task_id=task_id, principal_id="analyst-a"
        )
        nobody = audit.list_events(conn, limit=2, task_id=task_id, principal_id="reviewer-a")

    assert len(first.events) == 2
    assert first.next_after is not None
    assert len(rest.events) == 1
    assert rest.next_after is None
    assert nobody.events == ()
