"""Gateway pipeline for ``POST /v1/execute`` (docs/WSPOLNE_USTALENIA.md, section 3).

Built so far (A2–A3): steps 2–4 for documents, with an audit event at every step. The
task, its owner and client come from the database; the active policy/feed versions are
pinned; access is decided from the trusted catalog before the adapter runs; fields
outside the role's scope are removed. The intent record is stored before the document
adapter runs; without it the adapter is not called.

Not built yet: Presidio and the secret rule (A4); idempotency, request limits, budget,
Jev and Luna (A5); artifacts (A6). Summaries and artifacts answer 501.
"""

import time
from contextlib import closing
from uuid import UUID

from app import db
from app.adapters.documents import DocumentAdapter, DocumentCatalog, DocumentReadError
from app.api.errors import ApiError
from app.audit import AdapterName, AuditUnavailableError, RequestTrail
from app.auth import Principal
from app.contracts import (
    ControlId,
    ControlResult,
    Decision,
    DocumentReadOutput,
    DocumentReadRequest,
    DocumentSummarizeRequest,
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStatus,
    ReasonCode,
    RequestContext,
    Stage,
    Tool,
    utc_now,
)
from app.controls import access
from app.controls.redaction import remove_fields
from app.policy import active_versions
from app.settings import Settings
from app.tasks import get_task

# Adapter whose status is the ``execution_status`` of each tool's response.
TOOL_ADAPTERS: dict[Tool, AdapterName] = {
    Tool.DOCUMENTS_READ: "document_read",
    Tool.DOCUMENTS_SUMMARIZE: "summary",
    Tool.ARTIFACTS_ADMIT: "artifact_admit",
}


class Gateway:
    def __init__(
        self, settings: Settings, catalog: DocumentCatalog, documents: DocumentAdapter
    ) -> None:
        self._settings = settings
        self._catalog = catalog
        self._documents = documents

    def execute(
        self, request_id: UUID, principal: Principal, request: ExecuteRequest
    ) -> ExecuteResponse:
        tool = Tool(request.tool)
        trail = RequestTrail(self._settings.db_path, request_id, principal, tool)
        try:
            context = self._admit(trail, principal, request.task_id)
        except AuditUnavailableError:
            raise ApiError(503, ReasonCode.AUDIT_UNAVAILABLE) from None
        try:
            return self._run(trail, context, request)
        except AuditUnavailableError:
            if not trail.anything_called:
                raise ApiError(503, ReasonCode.AUDIT_UNAVAILABLE) from None
            # An adapter has already run, so the response must say so. Its output is
            # withheld because the audit trail of this request is incomplete.
            return _denied(
                context,
                trail,
                ReasonCode.AUDIT_UNAVAILABLE,
                getattr(trail.calls, TOOL_ADAPTERS[tool]),
            )

    def _admit(self, trail: RequestTrail, principal: Principal, task_id: UUID) -> RequestContext:
        """Load the task and pin the active configuration; refuse before any adapter."""
        with closing(db.connect(self._settings.db_path)) as conn:
            task = get_task(conn, task_id)
            versions = active_versions(conn)

        # A refused task is still recorded under the requested ID and the caller, so an
        # admin can see attempts on foreign tasks; the owner's history leaves them out.
        trail.task_id = task_id
        trail.policy_version = versions.policy_version
        trail.feed_version = versions.feed_version
        owner = access.check_task_owner(principal, task)
        if owner.decision is Decision.DENY or task is None:
            trail.record(owner)
            raise ApiError(403, owner.reason_code)

        trail.client_id = task.client_id
        if versions.policy_version is None or versions.feed_version is None:
            # Protected operations stay disabled until a policy and a feed are active.
            trail.record(_gateway(Decision.DENY, ReasonCode.INVALID_CONFIG, Stage.ADMISSION))
            raise ApiError(503, ReasonCode.INVALID_CONFIG)

        context = RequestContext(
            request_id=trail.request_id,
            task_id=task.task_id,
            principal_id=task.principal_id,
            agent_id=task.agent_id,
            role=principal.role,
            client_id=task.client_id,
            policy_version=versions.policy_version,
            feed_version=versions.feed_version,
            created_at=utc_now(),
        )
        trail.record(_gateway(Decision.ALLOW, ReasonCode.OK, Stage.ADMISSION))
        return context

    def _run(
        self, trail: RequestTrail, context: RequestContext, request: ExecuteRequest
    ) -> ExecuteResponse:
        if not isinstance(request, DocumentReadRequest | DocumentSummarizeRequest):
            raise ApiError(501, ReasonCode.NOT_IMPLEMENTED)  # artifacts.admit: A6

        document = self._catalog.get(request.arguments.document_id)
        document_access = access.check_document(context, document)
        if document_access.decision is Decision.DENY or document is None:
            trail.record(document_access)
            return _denied(context, trail, document_access.reason_code)

        if isinstance(request, DocumentSummarizeRequest):
            trail.record(document_access)
            raise ApiError(501, ReasonCode.NOT_IMPLEMENTED)  # Jev and Luna: A5

        trail.record(document_access, starting="document_read")
        started = time.perf_counter()
        try:
            fields = self._documents.read(document)
        except DocumentReadError:
            trail.finished("document_read", ExecutionStatus.FAILED)
            trail.record(
                _gateway(Decision.DENY, ReasonCode.UPSTREAM_FAILED, Stage.PRE_DETECTOR),
                ExecutionStatus.FAILED,
                latency_ms=_elapsed_ms(started),
            )
            return _denied(context, trail, ReasonCode.UPSTREAM_FAILED, ExecutionStatus.FAILED)
        trail.finished("document_read", ExecutionStatus.SUCCEEDED)
        latency_ms = _elapsed_ms(started)

        kept, removed = remove_fields(fields, access.readable_fields(context.role))
        redaction = ControlResult(
            control_id=ControlId.REDACTION,
            decision=Decision.REDACT if removed else Decision.ALLOW,
            reason_code=ReasonCode.PII_REDACTED if removed else ReasonCode.OK,
            stage=Stage.PRE_DETECTOR,
            redacted_fields=removed,
        )
        trail.record(redaction, ExecutionStatus.SUCCEEDED, latency_ms=latency_ms)
        return ExecuteResponse(
            request_id=context.request_id,
            task_id=context.task_id,
            decision=redaction.decision,
            reason_code=redaction.reason_code,
            policy_version=context.policy_version,
            execution_status=ExecutionStatus.SUCCEEDED,
            adapter_calls=trail.calls,
            output=DocumentReadOutput(document_id=document.document_id, fields=kept),
            redacted_fields=removed,
            audit_event_ids=tuple(trail.event_ids),
        )


def _gateway(decision: Decision, reason_code: ReasonCode, stage: Stage) -> ControlResult:
    return ControlResult(
        control_id=ControlId.GATEWAY, decision=decision, reason_code=reason_code, stage=stage
    )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _denied(
    context: RequestContext,
    trail: RequestTrail,
    reason_code: ReasonCode,
    status: ExecutionStatus = ExecutionStatus.NOT_CALLED,
) -> ExecuteResponse:
    return ExecuteResponse(
        request_id=context.request_id,
        task_id=context.task_id,
        decision=Decision.DENY,
        reason_code=reason_code,
        policy_version=context.policy_version,
        execution_status=status,
        adapter_calls=trail.calls,
        output=None,
        audit_event_ids=tuple(trail.event_ids),
    )
