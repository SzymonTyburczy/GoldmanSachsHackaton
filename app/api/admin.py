"""Admin API (docs/WSPOLNE_USTALENIA.md, section 5).

The router requires the admin role for every route, including ones added later.
Audit events and their export work since A3. The other routes refuse with
501 ``NOT_IMPLEMENTED`` until their step is built.
"""

from contextlib import closing
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app import audit, db
from app.api.errors import ApiError
from app.api.paging import EventsAfter, EventsLimit
from app.auth import require_admin
from app.contracts import AuditEventPage, ReasonCode

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _not_implemented() -> ApiError:
    return ApiError(501, ReasonCode.NOT_IMPLEMENTED)


@router.get("/policy")
def get_policy() -> None:
    """A4: full active policy and its version."""
    raise _not_implemented()


@router.put("/policy")
def put_policy() -> None:
    """A4: validate a complete policy and activate it atomically."""
    raise _not_implemented()


@router.get("/feed")
def get_feed() -> None:
    """A6: active artifact feed and its version."""
    raise _not_implemented()


@router.put("/feed")
def put_feed() -> None:
    """A6: validate a complete feed and activate it atomically."""
    raise _not_implemented()


@router.get("/events")
def list_events(
    request: Request,
    after: EventsAfter = 0,
    limit: EventsLimit = 50,
    task_id: UUID | None = None,
    request_id: UUID | None = None,
) -> AuditEventPage:
    """All audit events, oldest first, optionally for one task or one request."""
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        return audit.list_events(
            conn, limit=limit, after=after, task_id=task_id, request_id=request_id
        )


@router.get("/metrics")
def get_metrics() -> None:
    """A6/B4: counters, active and disabled controls, cost and reservations."""
    raise _not_implemented()


@router.get("/audit/export")
def export_audit(request: Request) -> StreamingResponse:
    """All audit events as JSON Lines, from the same table as ``/admin/events``."""
    return StreamingResponse(
        audit.export_lines(request.app.state.settings.db_path),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="controlproof-audit.jsonl"'},
    )


@router.get("/test-results")
def get_test_results() -> None:
    """B5/A6: last saved test report with time and commit; never runs tests."""
    raise _not_implemented()
