"""Admin API for configuration, audit, metrics and saved reports.

The router requires the admin role for every route, including ones added later.
Policy and feed changes go through the same validation and atomic activation as
``make reload-config``; an invalid or stale update leaves the active version in force.
Metrics and test results are read-only views of stored data.
"""

from contextlib import closing
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app import audit, db, metrics, policy, reports
from app.api.errors import ApiError
from app.api.paging import EventsAfter, EventsLimit
from app.auth import CurrentPrincipal, require_admin
from app.contracts import AuditEventPage, ReasonCode
from app.metrics import AdminMetrics
from app.policy import (
    ActiveFeed,
    ActivePolicy,
    ConfigKind,
    Feed,
    FeedUpdate,
    Policy,
    PolicyUpdate,
    StoredConfig,
)
from app.reports import TestResults

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


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


def _active_feed(stored: StoredConfig) -> ActiveFeed:
    if not isinstance(stored.document, Feed):
        raise TypeError("stored document is not a feed")
    return ActiveFeed(
        feed_version=stored.version,
        sha256=stored.sha256,
        created_at=stored.created_at,
        created_by=stored.created_by,
        feed=stored.document,
    )


def _load_active(request: Request, kind: ConfigKind) -> StoredConfig:
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        try:
            stored = policy.load_active(conn, kind)
        except policy.StoredConfigError:
            stored = None
    if stored is None:
        raise ApiError(503, ReasonCode.INVALID_CONFIG)
    return stored


def _activate(
    request: Request,
    kind: ConfigKind,
    document: Policy | Feed,
    expected_version: int | None,
    created_by: str,
) -> StoredConfig:
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        try:
            return policy.activate(
                conn, kind, document, expected_version=expected_version, created_by=created_by
            )
        except policy.VersionConflictError:
            raise ApiError(409, ReasonCode.VERSION_CONFLICT) from None


@router.get("/policy")
def get_policy(request: Request) -> ActivePolicy:
    """The complete active policy and its version."""
    return _active_policy(_load_active(request, "policy"))


@router.put("/policy")
def put_policy(body: PolicyUpdate, principal: CurrentPrincipal, request: Request) -> ActivePolicy:
    """Validate a complete policy and activate it as the next version.

    An invalid body is refused with 422 before anything is stored; a stale
    ``expected_version`` gives 409. In both cases the active version stays in force.
    Requests already admitted keep the version they pinned.
    """
    stored = _activate(
        request, "policy", body.policy, body.expected_version, principal.principal_id
    )
    return _active_policy(stored)


@router.get("/feed")
def get_feed(request: Request) -> ActiveFeed:
    """The complete active artifact feed and its version."""
    return _active_feed(_load_active(request, "feed"))


@router.put("/feed")
def put_feed(body: FeedUpdate, principal: CurrentPrincipal, request: Request) -> ActiveFeed:
    """Validate a complete feed and activate it as the next version.

    Like the policy: 422 for an invalid feed and 409 for a stale ``expected_version``,
    both without a change, so existing rules stay in force. The next request pins the
    new version; requests already admitted keep theirs.
    """
    stored = _activate(request, "feed", body.feed, body.expected_version, principal.principal_id)
    return _active_feed(stored)


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
def get_metrics(request: Request) -> AdminMetrics:
    """Counters, active and disabled controls, cost and reservations from stored data."""
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        loaded: dict[ConfigKind, StoredConfig | None] = {}
        for kind in ("policy", "feed"):
            try:
                loaded[kind] = policy.load_active(conn, kind)
            except policy.StoredConfigError:
                loaded[kind] = None
        return metrics.collect(conn, loaded["policy"], loaded["feed"])


@router.get("/audit/export")
def export_audit(request: Request) -> StreamingResponse:
    """All audit events as JSON Lines, from the same table as ``/admin/events``."""
    return StreamingResponse(
        audit.export_lines(request.app.state.settings.db_path),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="controlproof-audit.jsonl"'},
    )


@router.get("/test-results")
def get_test_results(request: Request) -> TestResults:
    """Newest saved report of each kind, with its time and commit; never runs tests."""
    return reports.latest(request.app.state.settings.reports_dir)
