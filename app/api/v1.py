"""Client API (docs/WSPOLNE_USTALENIA.md, sections 4–5).

Every route needs a demo bearer token. The identity, role and client scope come from
the server-side directory in ``app.auth``; tasks record their owner and client.
"""

from contextlib import closing
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request

from app import audit, db
from app.api.errors import ApiError, request_id_of
from app.api.paging import EventsAfter, EventsLimit
from app.auth import CurrentPrincipal
from app.contracts import (
    AuditEventPage,
    CreateTaskRequest,
    Decision,
    ExecuteRequest,
    ExecuteResponse,
    ReasonCode,
    TaskResponse,
)
from app.controls import access
from app.gateway import Gateway
from app.tasks import create_task as insert_task
from app.tasks import get_task as load_task

router = APIRouter(prefix="/v1")


@router.post("/tasks", status_code=201)
def create_task(
    body: CreateTaskRequest, principal: CurrentPrincipal, request: Request
) -> TaskResponse:
    """Create a task owned by the caller, for a client within the caller's scope."""
    scope = access.check_client_scope(principal, body.client_id)
    if scope.decision is Decision.DENY:
        raise ApiError(403, scope.reason_code)
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        task = insert_task(conn, principal, body.client_id)
    return task.to_response()


@router.get("/tasks/{task_id}")
def get_task(task_id: UUID, principal: CurrentPrincipal, request: Request) -> TaskResponse:
    """Task metadata for its owner or an admin. Decisions are in ``/events``."""
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        task = load_task(conn, task_id)
    if task is None or not access.can_view_task(principal, task):
        raise ApiError(403, ReasonCode.TASK_FORBIDDEN)
    return task.to_response()


@router.get("/tasks/{task_id}/events")
def get_task_events(
    task_id: UUID,
    principal: CurrentPrincipal,
    request: Request,
    after: EventsAfter = 0,
    limit: EventsLimit = 50,
) -> AuditEventPage:
    """Audit history of a task for its owner or an admin, oldest first.

    Lists the owner's requests only. Refused attempts by other principals on this task
    are visible to admins in ``/admin/events``.
    """
    with closing(db.connect(request.app.state.settings.db_path)) as conn:
        task = load_task(conn, task_id)
        if task is None or not access.can_view_task(principal, task):
            raise ApiError(403, ReasonCode.TASK_FORBIDDEN)
        return audit.list_events(
            conn, limit=limit, after=after, task_id=task.task_id, principal_id=task.principal_id
        )


@router.post("/execute")
def execute(
    body: ExecuteRequest,
    principal: CurrentPrincipal,
    request: Request,
    # Required by the contract; stored with the result once idempotency is built.
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> ExecuteResponse:
    """Run one tool call through the gateway; a denial is a 200 with ``DENY``."""
    gateway: Gateway = request.app.state.gateway
    return gateway.execute(request_id_of(request), principal, body)
