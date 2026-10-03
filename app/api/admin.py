"""Admin API (docs/WSPOLNE_USTALENIA.md, section 5).

The router requires the admin role for every route, including ones added later.
Audit events and their export work since A3, the policy since A4. The other routes
refuse with 501 ``NOT_IMPLEMENTED`` until their step is built.
"""

from contextlib import closing
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app import audit, db, policy
from app.api.errors import ApiError
from app.api.paging import EventsAfter, EventsLimit
from app.auth import CurrentPrincipal, require_admin
from app.contracts import AuditEventPage, ReasonCode
from app.policy import ActivePolicy, Policy, PolicyUpdate, StoredConfig

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _not_implemented() -> ApiError:
    return ApiError(501, ReasonCode.NOT_IMPLEMENTED)


def _active_policy(stored: StoredConfig) -> ActivePolicy:
    if not isinstance(stored.document, Policy):
        raise TypeError("stored document is not a policy")
    return ActivePolicy(
        policy_version=stored.version,
        sha256=stored.sha256,
        created_at=stored.created_at,
        created_by=stored.created_by,
        policy=stored.document,
    )


@router.get("/policy")
def get_policy(request: Request) -> ActivePolicy:
    """The complete active policy and its version."""
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        try:
            stored = policy.load_active(conn, "policy")
        except policy.StoredConfigError:
            stored = None
    if stored is None:
        raise ApiError(503, ReasonCode.INVALID_CONFIG)
    return _active_policy(stored)


@router.put("/policy")
def put_policy(body: PolicyUpdate, principal: CurrentPrincipal, request: Request) -> ActivePolicy:
    """Validate a complete policy and activate it as the next version.

    An invalid body is refused with 422 before anything is stored; a stale
    ``expected_version`` gives 409. In both cases the active version stays in force.
    Requests already admitted keep the version they pinned.
    """
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        try:
            stored = policy.activate(
                conn,
                "policy",
                body.policy,
                expected_version=body.expected_version,
                created_by=principal.principal_id,
            )
        except policy.VersionConflictError:
            raise ApiError(409, ReasonCode.VERSION_CONFLICT) from None
    return _active_policy(stored)


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
