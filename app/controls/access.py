"""Access control: client scope, task ownership, tools and document owner.

Every decision uses only server-side state: the authenticated principal, the stored task,
the pinned policy and the trusted document catalog. Nothing here opens document content,
so a denial always happens before the document adapter runs. Readable fields per role
come from the policy (``acl``) and are applied by ``app.controls.redaction``.
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
    Tool,
)
from app.policy import Policy
from app.tasks import Task


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


def check_tool(policy: Policy, context: RequestContext, tool: Tool) -> ControlResult:
    """The role's tools come from the pinned policy (``acl.<role>.tools``)."""
    stage = Stage.ARTIFACT if tool is Tool.ARTIFACTS_ADMIT else Stage.PRE_DOCUMENT
    if tool not in policy.tools_for(context.role):
        return _result(Decision.DENY, ReasonCode.TOOL_FORBIDDEN, stage)
    return _allow(stage)


def check_replay(
    policy: Policy, stored: Policy | None, context: RequestContext, tool: Tool
) -> ControlResult:
    """A stored response is handed out again only within the role's current rights.

    The tool must still be allowed. If the policy changed since the response was stored
    (``stored`` is that policy, ``None`` if it cannot be loaded), the role's field scope
    must not have narrowed: the fields a read returns, or the outbound fields a summary
    was written from. The text of a summary cannot be filtered field by field, so a
    narrower scope refuses the whole response. Nothing is executed again.
    """
    tool_access = check_tool(policy, context, tool)
    if tool_access.decision is Decision.DENY or stored is policy or tool is Tool.ARTIFACTS_ADMIT:
        return tool_access
    if stored is None:
        return _result(Decision.DENY, ReasonCode.TOOL_FORBIDDEN, tool_access.stage)
    if tool is Tool.DOCUMENTS_READ:
        narrowed = not stored.fields_for(context.role) <= policy.fields_for(context.role)
    else:
        narrowed = not stored.outbound_fields_for(context.role) <= policy.outbound_fields_for(
            context.role
        )
    if narrowed:
        return _result(Decision.DENY, ReasonCode.TOOL_FORBIDDEN, tool_access.stage)
    return tool_access


def check_document(context: RequestContext, document: CatalogEntry | None) -> ControlResult:
    """The document must be in the trusted catalog and belong to the task's client.

    An unknown document is refused like another client's, so the answer does not reveal
    which documents exist.
    """
    if document is None or document.client_id != context.client_id:
        return _result(Decision.DENY, ReasonCode.CLIENT_FORBIDDEN, Stage.PRE_DOCUMENT)
    return _allow(Stage.PRE_DOCUMENT)
