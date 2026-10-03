"""Access control: client scope, task ownership and document owner.

Every decision uses only server-side state: the authenticated principal, the stored task
and the trusted document catalog. Nothing here opens document content, so a denial
always happens before the document adapter runs.
"""

from app.adapters.documents import CatalogEntry
from app.auth import Principal
from app.contracts import (
    ControlId,
    ControlResult,
    Decision,
    ReasonCode,
    RequestContext,
    Role,
    Stage,
)
from app.tasks import Task

ANALYST_FIELDS = frozenset({"company_name", "status", "notes"})
REVIEWER_FIELDS = ANALYST_FIELDS | {"review_note"}

# Document fields each role may read (docs/WSPOLNE_USTALENIA.md, section 5). Anything
# else, including email, personal_id and secret, is removed. A4 moves this to the policy.
READABLE_FIELDS: dict[Role, frozenset[str]] = {
    Role.ANALYST: ANALYST_FIELDS,
    Role.REVIEWER: REVIEWER_FIELDS,
    Role.ADMIN: REVIEWER_FIELDS,
}


def _result(decision: Decision, reason_code: ReasonCode, stage: Stage) -> ControlResult:
    return ControlResult(
        control_id=ControlId.ACCESS, decision=decision, reason_code=reason_code, stage=stage
    )


def _allow(stage: Stage) -> ControlResult:
    return _result(Decision.ALLOW, ReasonCode.OK, stage)


def check_client_scope(principal: Principal, client_id: str) -> ControlResult:
    """A principal may open tasks only for its own clients."""
    if client_id not in principal.client_ids:
        return _result(Decision.DENY, ReasonCode.CLIENT_FORBIDDEN, Stage.ADMISSION)
    return _allow(Stage.ADMISSION)


def check_task_owner(principal: Principal, task: Task | None) -> ControlResult:
    """Only the owner executes in a task. An unknown task is refused like a foreign one."""
    if task is None or task.principal_id != principal.principal_id:
        return _result(Decision.DENY, ReasonCode.TASK_FORBIDDEN, Stage.ADMISSION)
    # Re-checked on every request in case the principal's client scope has changed.
    return check_client_scope(principal, task.client_id)


def can_view_task(principal: Principal, task: Task | None) -> bool:
    return task is not None and (
        task.principal_id == principal.principal_id or principal.role is Role.ADMIN
    )


def check_document(context: RequestContext, document: CatalogEntry | None) -> ControlResult:
    """The document must be in the trusted catalog and belong to the task's client.

    An unknown document is refused like another client's, so the answer does not reveal
    which documents exist.
    """
    if document is None or document.client_id != context.client_id:
        return _result(Decision.DENY, ReasonCode.CLIENT_FORBIDDEN, Stage.PRE_DOCUMENT)
    return _allow(Stage.PRE_DOCUMENT)


def readable_fields(role: Role) -> frozenset[str]:
    return READABLE_FIELDS[role]
