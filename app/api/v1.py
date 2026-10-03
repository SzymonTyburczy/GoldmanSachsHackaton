"""Client API skeleton (docs/WSPOLNE_USTALENIA.md, sections 4–5).

Request bodies are already validated against the shared contracts, but no route runs a
control or an adapter yet: each one refuses with 501 ``NOT_IMPLEMENTED``. Authentication
(A2) and the gateway pipeline (A2–A5) replace these bodies.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header

from app.api.errors import ApiError
from app.contracts import CreateTaskRequest, ExecuteRequest, ReasonCode

router = APIRouter(prefix="/v1")


def _not_implemented() -> ApiError:
    return ApiError(501, ReasonCode.NOT_IMPLEMENTED)


@router.post("/tasks")
def create_task(body: CreateTaskRequest) -> None:
    """A2: create a task owned by the authenticated principal for an allowed client."""
    raise _not_implemented()


@router.get("/tasks/{task_id}")
def get_task(task_id: UUID) -> None:
    """A2/A3: task state, decisions and usage for its owner or an admin."""
    raise _not_implemented()


@router.post("/execute")
def execute(
    body: ExecuteRequest,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> None:
    """A2–A5: run one tool call through every control of the gateway."""
    raise _not_implemented()
