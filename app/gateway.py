"""Gateway pipeline for ``POST /v1/execute`` (docs/WSPOLNE_USTALENIA.md, section 3).

Built so far (A2–A4): steps 2–4 for documents, with an audit event at every step. The
task, its owner and client come from the database. The active policy/feed versions are
pinned and the request uses that one policy throughout. The role's tools and the document
owner are checked before the adapter runs, and so is the local PII engine. After the read,
fields outside the role's scope are removed, then the secret rule and Presidio replace
sensitive fragments in the rest. The intent record is stored before the document adapter
runs; without it the adapter is not called.

Not built yet: idempotency, request limits, budget, Jev and Luna (A5), which take their
input from ``redaction.prepare_provider_input``; artifacts (A6). Summaries and artifacts
answer 501.
"""

import time
from collections.abc import Callable
from contextlib import closing
from uuid import UUID

from app import db, policy
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
from app.controls.redaction import redact_fields
from app.pii.engine import PiiEngine, PiiEngineUnavailable, get_engine
from app.policy import Policy
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
        self,
        settings: Settings,
        catalog: DocumentCatalog,
        documents: DocumentAdapter,
        pii_engine: Callable[[tuple[str, ...]], PiiEngine] = get_engine,
    ) -> None:
        self._settings = settings
        self._catalog = catalog
        self._documents = documents
        self._pii_engine = pii_engine

    def execute(
        self, request_id: UUID, principal: Principal, request: ExecuteRequest
    ) -> ExecuteResponse:
        tool = Tool(request.tool)
        trail = RequestTrail(self._settings.db_path, request_id, principal, tool)
        try:
            context, pinned = self._admit(trail, principal, request.task_id)
        except AuditUnavailableError:
            raise ApiError(503, ReasonCode.AUDIT_UNAVAILABLE) from None
        try:
            return self._run(trail, context, pinned, request)
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

    def _admit(
        self, trail: RequestTrail, principal: Principal, task_id: UUID
    ) -> tuple[RequestContext, Policy]:
        """Load the task, pin the active configuration and its policy; refuse before any
        adapter."""
        with closing(db.connect(self._settings.db_path)) as conn:
            task = get_task(conn, task_id)
            versions = policy.active_versions(conn)
            pinned = None
            if versions.policy_version is not None:
                try:
                    pinned = policy.load(conn, "policy", versions.policy_version).document
                except policy.StoredConfigError:
                    pinned = None

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
        if (
            versions.policy_version is None
            or versions.feed_version is None
            or not isinstance(pinned, Policy)
        ):
            # Protected operations stay disabled until a valid policy and a feed are active.
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
        return context, pinned

    def _run(
        self,
        trail: RequestTrail,
        context: RequestContext,
        pinned: Policy,
        request: ExecuteRequest,
    ) -> ExecuteResponse:
        tool_access = access.check_tool(pinned, context, Tool(request.tool))
        if tool_access.decision is Decision.DENY:
            trail.record(tool_access)
            return _denied(context, trail, tool_access.reason_code)

        if not isinstance(request, DocumentReadRequest | DocumentSummarizeRequest):
            raise ApiError(501, ReasonCode.NOT_IMPLEMENTED)  # artifacts.admit: A6

        # Without the local engine nothing may be returned or sent, so do not read at all.
        try:
            engine = self._pii_engine(pinned.redaction.languages)
        except PiiEngineUnavailable:
            trail.record(_redaction_unavailable(Stage.PRE_DOCUMENT))
            return _denied(context, trail, ReasonCode.PII_ENGINE_UNAVAILABLE)

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

        try:
            redacted = redact_fields(
                fields, pinned.fields_for(context.role), pinned.redaction, engine
            )
        except PiiEngineUnavailable:
            trail.record(
                _redaction_unavailable(Stage.PRE_DETECTOR),
                ExecutionStatus.SUCCEEDED,
                latency_ms=latency_ms,
            )
            return _denied(
                context, trail, ReasonCode.PII_ENGINE_UNAVAILABLE, ExecutionStatus.SUCCEEDED
            )

        redaction = ControlResult(
            control_id=ControlId.REDACTION,
            decision=Decision.REDACT if redacted.changed else Decision.ALLOW,
            reason_code=ReasonCode.PII_REDACTED if redacted.changed else ReasonCode.OK,
            stage=Stage.PRE_DETECTOR,
            redacted_fields=redacted.removed,
        )
        trail.record(
            redaction,
            ExecutionStatus.SUCCEEDED,
            latency_ms=latency_ms,
            entity_counts=redacted.entity_counts,
        )
        return ExecuteResponse(
            request_id=context.request_id,
            task_id=context.task_id,
            decision=redaction.decision,
            reason_code=redaction.reason_code,
            policy_version=context.policy_version,
            execution_status=ExecutionStatus.SUCCEEDED,
            adapter_calls=trail.calls,
            output=DocumentReadOutput(document_id=document.document_id, fields=redacted.fields),
            redacted_fields=redacted.removed,
            audit_event_ids=tuple(trail.event_ids),
        )


def _gateway(decision: Decision, reason_code: ReasonCode, stage: Stage) -> ControlResult:
    return ControlResult(
        control_id=ControlId.GATEWAY, decision=decision, reason_code=reason_code, stage=stage
    )


def _redaction_unavailable(stage: Stage) -> ControlResult:
    return ControlResult(
        control_id=ControlId.REDACTION,
        decision=Decision.DENY,
        reason_code=ReasonCode.PII_ENGINE_UNAVAILABLE,
        stage=stage,
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
