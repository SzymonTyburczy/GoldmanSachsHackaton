"""Gateway pipeline for ``POST /v1/execute`` (docs/WSPOLNE_USTALENIA.md, section 3).

Built so far (A2): steps 2–4 for documents. The task, its owner and client come from the
database; the active policy/feed versions are pinned; access is decided from the trusted
catalog before the adapter runs; fields outside the role's scope are removed.

Not built yet: audit (A3); Presidio and the secret rule (A4); idempotency, request
limits, budget, Jev and Luna (A5); artifacts (A6). Summaries and artifacts answer 501.
"""

from contextlib import closing
from uuid import UUID

from app import db
from app.adapters.documents import DocumentAdapter, DocumentCatalog, DocumentReadError
from app.api.errors import ApiError
from app.auth import Principal
from app.contracts import (
    AdapterCalls,
    Decision,
    DocumentReadOutput,
    DocumentReadRequest,
    DocumentSummarizeRequest,
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStatus,
    ReasonCode,
    RequestContext,
    utc_now,
)
from app.controls import access
from app.controls.redaction import remove_fields
from app.policy import active_versions
from app.settings import Settings
from app.tasks import get_task


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
        context = self._admit(request_id, principal, request.task_id)

        if not isinstance(request, DocumentReadRequest | DocumentSummarizeRequest):
            raise ApiError(501, ReasonCode.NOT_IMPLEMENTED)  # artifacts.admit: A6

        document = self._catalog.get(request.arguments.document_id)
        document_access = access.check_document(context, document)
        if document_access.decision is Decision.DENY or document is None:
            return _denied(context, document_access.reason_code, ExecutionStatus.NOT_CALLED)

        if isinstance(request, DocumentSummarizeRequest):
            raise ApiError(501, ReasonCode.NOT_IMPLEMENTED)  # Jev and Luna: A5

        try:
            fields = self._documents.read(document)
        except DocumentReadError:
            return _denied(
                context,
                ReasonCode.UPSTREAM_FAILED,
                ExecutionStatus.FAILED,
                AdapterCalls(document_read=ExecutionStatus.FAILED),
            )

        kept, removed = remove_fields(fields, access.readable_fields(context.role))
        return ExecuteResponse(
            request_id=context.request_id,
            task_id=context.task_id,
            decision=Decision.REDACT if removed else Decision.ALLOW,
            reason_code=ReasonCode.PII_REDACTED if removed else ReasonCode.OK,
            policy_version=context.policy_version,
            execution_status=ExecutionStatus.SUCCEEDED,
            adapter_calls=AdapterCalls(document_read=ExecutionStatus.SUCCEEDED),
            output=DocumentReadOutput(document_id=document.document_id, fields=kept),
            redacted_fields=removed,
        )

    def _admit(self, request_id: UUID, principal: Principal, task_id: UUID) -> RequestContext:
        """Load the task and pin the active configuration; refuse before any adapter."""
        with closing(db.connect(self._settings.db_path)) as conn:
            task = get_task(conn, task_id)
            versions = active_versions(conn)

        owner = access.check_task_owner(principal, task)
        if owner.decision is Decision.DENY or task is None:
            raise ApiError(403, owner.reason_code)
        if versions.policy_version is None or versions.feed_version is None:
            # Protected operations stay disabled until a policy and a feed are active.
            raise ApiError(503, ReasonCode.INVALID_CONFIG)

        return RequestContext(
            request_id=request_id,
            task_id=task.task_id,
            principal_id=task.principal_id,
            agent_id=task.agent_id,
            role=principal.role,
            client_id=task.client_id,
            policy_version=versions.policy_version,
            feed_version=versions.feed_version,
            created_at=utc_now(),
        )


def _denied(
    context: RequestContext,
    reason_code: ReasonCode,
    status: ExecutionStatus,
    adapter_calls: AdapterCalls | None = None,
) -> ExecuteResponse:
    return ExecuteResponse(
        request_id=context.request_id,
        task_id=context.task_id,
        decision=Decision.DENY,
        reason_code=reason_code,
        policy_version=context.policy_version,
        execution_status=status,
        adapter_calls=adapter_calls or AdapterCalls(),
        output=None,
    )
