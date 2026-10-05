"""Gateway pipeline for ``POST /v1/execute``.

Steps for documents, with an audit event at every step:

2. The task, its owner and client come from the database. The active policy and feed are
   pinned, and the request uses that one policy throughout. The request is stored with
   its idempotency key within the request limits (``app.idempotency``).
3. The role's tools and the document owner are checked before anything is read, and so
   are the local PII engine and the provider keys.
4. After the read the user's copy keeps the role's fields. Jev and Luna get only the
   ``outbound_fields`` among them and the prompt. The secret rule and Presidio mask both.
5–6. Jev assesses that redacted state once, after a reservation of its worst-case cost
   (``app.provider_calls``). ``risk_score >= block_threshold`` denies. Any detector
   failure denies, so the summary model is never called without an assessment.
7. Luna counts the same input, its cost is reserved and Luna summarizes it once.
8. The summary passes the secret rule and Presidio again before it is returned.

Every provider call follows its reservation and is preceded by its intent record. It is
bounded by the policy timeout. ``documents.read`` ends after the detector. Budget limits
for each reservation are the pinned ones, lowered if an admin has activated lower limits
since.

``artifacts.admit`` calls no model: after the role's tools and the manifest, the bytes are
read once, at most 64 KiB, and ``app.controls.artifacts`` checks their digest against the
manifest and the pinned feed before it parses them as JSON.
"""

import asyncio
import dataclasses
import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from contextlib import closing
from typing import Any
from uuid import UUID

import httpx
import openai

from app import budget, db, idempotency, policy, provider_calls, reviews
from app.adapters.artifacts import (
    ArtifactManifest,
    ArtifactReadError,
    ArtifactStore,
    ArtifactTooLarge,
)
from app.adapters.documents import (
    CatalogEntry,
    DocumentAdapter,
    DocumentCatalog,
    DocumentReadError,
)
from app.adapters.openai_luna import OpenAILunaError, SummaryResult, TokenCount
from app.adapters.providers import KeyedProviders, Providers, Summarizer
from app.api.errors import ApiError
from app.audit import AdapterName, AuditUnavailableError, RequestTrail
from app.auth import Principal
from app.budget import BudgetLimits
from app.contracts import (
    ArtifactAdmitOutput,
    ArtifactAdmitRequest,
    ControlId,
    ControlResult,
    Decision,
    DocumentReadOutput,
    DocumentSummarizeRequest,
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStatus,
    ReasonCode,
    RequestContext,
    Role,
    SemanticResult,
    Stage,
    SummaryOutput,
    Tool,
    Usage,
    utc_now,
)
from app.controls import access, artifacts, semantic
from app.controls.redaction import ProviderInput, mask_text, prepare_provider_input, redact_fields
from app.controls.semantic import SemanticCheckError, SemanticEvaluator
from app.pii.engine import PiiEngine, PiiEngineUnavailable, get_engine
from app.policy import Feed, Policy
from app.prompts.semantic import SEMANTIC_QUESTIONS
from app.settings import Settings
from app.tasks import get_task

logger = logging.getLogger(__name__)

# Adapter whose status is the ``execution_status`` of each tool's response.
TOOL_ADAPTERS: dict[Tool, AdapterName] = {
    Tool.DOCUMENTS_READ: "document_read",
    Tool.DOCUMENTS_SUMMARIZE: "summary",
    Tool.ARTIFACTS_ADMIT: "artifact_admit",
}

TIMEOUT_ERRORS = (TimeoutError, httpx.TimeoutException, openai.APITimeoutError)
# Failures after which the detector result cannot be used. Budget refusals and audit
# outages are handled separately.
DETECTOR_ERRORS = (SemanticCheckError, provider_calls.ProviderCostUnavailable, ValueError)
SUMMARY_ERRORS = (OpenAILunaError, provider_calls.ProviderCostUnavailable, ValueError)


class Gateway:
    def __init__(
        self,
        settings: Settings,
        catalog: DocumentCatalog,
        documents: DocumentAdapter,
        manifest: ArtifactManifest,
        artifact_store: ArtifactStore,
        providers: Providers | None = None,
        pii_engine: Callable[[tuple[str, ...]], PiiEngine] = get_engine,
    ) -> None:
        self._db_path = settings.db_path
        self._catalog = catalog
        self._documents = documents
        self._manifest = manifest
        self._artifact_store = artifact_store
        self._providers = providers or KeyedProviders(settings)
        self._pii_engine = pii_engine

    async def execute(
        self,
        request_id: UUID,
        principal: Principal,
        request: ExecuteRequest,
        idempotency_key: UUID,
    ) -> ExecuteResponse:
        trail = RequestTrail(self._db_path, request_id, principal, Tool(request.tool))
        try:
            admitted = self._admit(trail, principal, request, idempotency_key)
        except AuditUnavailableError:
            raise ApiError(503, ReasonCode.AUDIT_UNAVAILABLE) from None
        if isinstance(admitted, ExecuteResponse):
            return admitted
        context, pinned, feed = admitted
        try:
            response = await self._run(trail, context, pinned, feed, request)
        except AuditUnavailableError:
            if not trail.anything_called:
                self._abandon(context, trail)
                raise ApiError(503, ReasonCode.AUDIT_UNAVAILABLE) from None
            # An adapter has already run, so the response must say so. Its output is
            # withheld because the audit trail of this request is incomplete.
            response = _denied(context, trail, ReasonCode.AUDIT_UNAVAILABLE)
        except BaseException:
            self._abandon(context, trail)
            raise
        self._complete(context, response)
        return response

    def response_for(self, principal: Principal, request_id: UUID) -> ExecuteResponse:
        response = reviews.get_response(self._db_path, principal, request_id)
        if response.output is None:
            return response
        with closing(db.connect(self._db_path)) as conn:
            row = conn.execute(
                "SELECT tool FROM requests WHERE request_id = ?", (str(request_id),)
            ).fetchone()
            task = get_task(conn, response.task_id)
            try:
                active = policy.load_active(conn, "policy")
                active_feed = policy.load_active(conn, "feed")
            except policy.StoredConfigError:
                active = active_feed = None
        if task is None or active is None or active_feed is None:
            raise ApiError(503, ReasonCode.INVALID_CONFIG)
        context = RequestContext(
            request_id=request_id,
            task_id=task.task_id,
            principal_id=task.principal_id,
            agent_id=task.agent_id,
            role=principal.role,
            client_id=task.client_id,
            policy_version=active.version,
            feed_version=active_feed.version,
            created_at=utc_now(),
        )
        trail = RequestTrail(self._db_path, request_id, principal, Tool(row["tool"]))
        trail.task_id, trail.client_id = task.task_id, task.client_id
        trail.policy_version, trail.feed_version = active.version, active_feed.version
        trail.calls = response.adapter_calls
        try:
            return self._replay(trail, context, active.document, active_feed.document, response)
        except AuditUnavailableError:
            raise ApiError(503, ReasonCode.AUDIT_UNAVAILABLE) from None

    async def decide_review(
        self, reviewer: Principal, review_id: UUID, decision: str
    ) -> reviews.HumanReview:
        # Check permission before loading configuration or claiming the request.
        item = reviews.get_review(self._db_path, reviewer, review_id)
        if not reviews.can_review(reviewer, item):
            raise ApiError(403, ReasonCode.REVIEW_FORBIDDEN)
        with closing(db.connect(self._db_path)) as conn:
            versions = policy.active_versions(conn)
            try:
                current = policy.load_active(conn, "policy")
                current_feed = policy.load_active(conn, "feed")
            except policy.StoredConfigError:
                current = current_feed = None
        if current is None or current_feed is None:
            raise ApiError(503, ReasonCode.INVALID_CONFIG)
        saved = reviews.claim(self._db_path, reviewer, review_id, current.document)
        context = saved.context
        origin = Principal(
            context.principal_id,
            Role(context.role),
            context.agent_id,
            frozenset({context.client_id}),
        )
        trail = RequestTrail(self._db_path, context.request_id, origin, Tool(saved.request.tool))
        trail.task_id, trail.client_id = context.task_id, context.client_id
        trail.policy_version, trail.feed_version = context.policy_version, context.feed_version
        trail.calls = saved.pending.adapter_calls
        trail.event_ids = list(saved.pending.audit_event_ids)
        trail.usage = list(saved.pending.usage)
        status = "APPROVED" if decision == "approve" else "BLOCKED"
        try:
            with closing(db.connect(self._db_path)) as conn:
                task = get_task(conn, context.task_id)
            reason = None
            if saved.review.expires_at <= utc_now():
                reason, status = ReasonCode.REVIEW_EXPIRED, "EXPIRED"
            elif decision == "block":
                reason = ReasonCode.HUMAN_BLOCKED
            elif (
                versions.policy_version != context.policy_version
                or versions.feed_version != context.feed_version
                or task is None
                or task.principal_id != context.principal_id
                or task.client_id != context.client_id
                or task.agent_id != context.agent_id
            ):
                reason, status = ReasonCode.REVIEW_STALE, "STALE"
            if reason is not None:
                trail.record(_human(Decision.DENY, reason), reviewer_id=reviewer.principal_id)
                response = _denied(context, trail, reason)
            else:
                trail.record(
                    _human(Decision.ALLOW, ReasonCode.HUMAN_APPROVED),
                    reviewer_id=reviewer.principal_id,
                )
                response = await self._run(
                    trail, context, current.document, current_feed.document, saved.request, saved
                )
                if response.reason_code is ReasonCode.REVIEW_STALE:
                    status = "STALE"
            idempotency.complete(self._db_path, context.request_id, response)
            reviews.finish(self._db_path, review_id, status)
        except AuditUnavailableError:
            self._abandon(context, trail)
            reviews.finish(self._db_path, review_id, "UNKNOWN")
            raise ApiError(503, ReasonCode.AUDIT_UNAVAILABLE) from None
        except BaseException:
            self._abandon(context, trail)
            reviews.finish(self._db_path, review_id, "UNKNOWN")
            raise
        return reviews.get_review(self._db_path, reviewer, review_id)

    def _admit(
        self,
        trail: RequestTrail,
        principal: Principal,
        request: ExecuteRequest,
        idempotency_key: UUID,
    ) -> tuple[RequestContext, Policy, Feed] | ExecuteResponse:
        """Load the task, pin the configuration and store the request, before any adapter.

        Returns a response instead of a context for a replayed key or a request limit.
        """
        with closing(db.connect(self._db_path)) as conn:
            task = get_task(conn, request.task_id)
            versions = policy.active_versions(conn)
            pinned = feed = None
            try:
                if versions.policy_version is not None:
                    pinned = policy.load(conn, "policy", versions.policy_version).document
                if versions.feed_version is not None:
                    feed = policy.load(conn, "feed", versions.feed_version).document
            except policy.StoredConfigError:
                pinned = feed = None

        # A refused task is still recorded under the requested ID and the caller, so an
        # admin can see attempts on foreign tasks; the owner's history leaves them out.
        trail.task_id = request.task_id
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
            or not isinstance(feed, Feed)
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
        reviews.maintain(self._db_path)
        claim = idempotency.claim(
            self._db_path,
            context,
            tool=trail.tool,
            key=idempotency_key,
            digest=idempotency.request_digest(request),
            resources=pinned.resources,
            now=context.created_at,
        )
        match claim:
            case idempotency.Replay(response):
                return self._replay(trail, context, pinned, feed, response)
            case idempotency.Pending():
                raise ApiError(409, ReasonCode.REQUEST_PENDING)
            case idempotency.Conflict():
                raise ApiError(409, ReasonCode.IDEMPOTENCY_CONFLICT)
            case idempotency.RateLimited(retry_after):
                trail.record(_gateway(Decision.DENY, ReasonCode.RATE_LIMITED, Stage.ADMISSION))
                raise ApiError(
                    429, ReasonCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)}
                )
            case idempotency.LimitReached(reason_code):
                trail.record(_gateway(Decision.DENY, reason_code, Stage.ADMISSION))
                return _denied(context, trail, reason_code)

        try:
            trail.record(_gateway(Decision.ALLOW, ReasonCode.OK, Stage.ADMISSION))
        except AuditUnavailableError:
            self._abandon(context, trail)
            raise
        return context, pinned, feed

    def _replay(
        self,
        trail: RequestTrail,
        context: RequestContext,
        pinned: Policy,
        feed: Feed,
        response: ExecuteResponse,
    ) -> ExecuteResponse:
        """The stored response of a repeated key, if the caller may still have it.

        A stored denial is returned as is. Otherwise the current policy must still allow
        the tool and the data (``access.check_replay``), and an admitted artifact must not
        have been blocked by the feed since. A refusal is audited but not stored, so the
        same key returns the stored response again once the rights are back.
        """
        if response.decision in (Decision.DENY, Decision.REQUIRE_APPROVAL):
            return response
        stored: Policy | None = pinned
        if response.policy_version != context.policy_version:
            with closing(db.connect(self._db_path)) as conn:
                try:
                    document = policy.load(conn, "policy", response.policy_version).document
                except policy.StoredConfigError:
                    document = None
            stored = document if isinstance(document, Policy) else None
        result = access.check_replay(pinned, stored, context, trail.tool)
        if (
            result.decision is Decision.ALLOW
            and isinstance(response.output, ArtifactAdmitOutput)
            and any(rule.value == response.output.sha256 for rule in feed.rules)
        ):
            result = artifacts.blocked()
        if result.decision is Decision.DENY:
            trail.record(result)
            return _denied(context, trail, result.reason_code)
        return response

    async def _run(
        self,
        trail: RequestTrail,
        context: RequestContext,
        pinned: Policy,
        feed: Feed,
        request: ExecuteRequest,
        continuation: reviews.Continuation | None = None,
    ) -> ExecuteResponse:
        tool_access = access.check_tool(pinned, context, trail.tool)
        if tool_access.decision is Decision.DENY:
            trail.record(tool_access)
            return _denied(context, trail, tool_access.reason_code)

        if isinstance(request, ArtifactAdmitRequest):
            return await self._admit_artifact(trail, context, pinned, feed, request)

        # Without the local engine nothing may be returned or sent, so do not read at all.
        try:
            engine = await asyncio.to_thread(self._pii_engine, pinned.redaction.languages)
        except PiiEngineUnavailable:
            trail.record(_redaction_unavailable(Stage.PRE_DOCUMENT))
            return _denied(context, trail, ReasonCode.PII_ENGINE_UNAVAILABLE)

        document = self._catalog.get(request.arguments.document_id)
        document_access = access.check_document(context, document)
        if document_access.decision is Decision.DENY or document is None:
            trail.record(document_access)
            return _denied(context, trail, document_access.reason_code)

        # A document that could not be assessed is not read: the detector is required for
        # every tool, and the summary model for summaries.
        providers = self._providers.connect(pinned.models)
        detector = providers.detector
        if detector is None:
            trail.record(
                _semantic(Decision.DENY, ReasonCode.DETECTOR_UNAVAILABLE, Stage.PRE_DOCUMENT)
            )
            return _denied(context, trail, ReasonCode.DETECTOR_UNAVAILABLE)
        prompt = summarizer = None
        if isinstance(request, DocumentSummarizeRequest):
            prompt, summarizer = request.arguments.prompt, providers.summarizer
            if summarizer is None:
                trail.record(
                    _gateway(Decision.DENY, ReasonCode.UPSTREAM_FAILED, Stage.PRE_DOCUMENT)
                )
                return _denied(context, trail, ReasonCode.UPSTREAM_FAILED)

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
            return _denied(context, trail, ReasonCode.UPSTREAM_FAILED)
        trail.finished("document_read", ExecutionStatus.SUCCEEDED)
        read_ms = _elapsed_ms(started)

        try:
            prepared = await asyncio.to_thread(
                prepare_provider_input, fields, prompt, context.role, pinned, engine
            )
            shown = None
            if summarizer is None:
                shown = await asyncio.to_thread(
                    redact_fields, fields, pinned.fields_for(context.role), pinned.redaction, engine
                )
        except PiiEngineUnavailable:
            trail.record(
                _redaction_unavailable(Stage.PRE_DETECTOR),
                ExecutionStatus.SUCCEEDED,
                latency_ms=read_ms,
            )
            return _denied(context, trail, ReasonCode.PII_ENGINE_UNAVAILABLE)

        # A read reports what the user gets; a summary reports what the providers get.
        removed, counts = (
            (prepared.removed, prepared.entity_counts)
            if shown is None
            else (shown.removed, shown.entity_counts)
        )
        input_redaction = _redaction(removed, counts, Stage.PRE_DETECTOR)
        trail.record(
            input_redaction, ExecutionStatus.SUCCEEDED, latency_ms=read_ms, entity_counts=counts
        )

        state = prepared.detector_state(_trusted_task(trail.tool, document, context))
        if _state_chars(state) > pinned.resources.max_detector_state_chars:
            trail.record(_budget(Decision.DENY, ReasonCode.INPUT_TOO_LARGE, Stage.PRE_DETECTOR))
            return _denied(context, trail, ReasonCode.INPUT_TOO_LARGE)

        if continuation is not None:
            with closing(db.connect(self._db_path)) as conn:
                versions = policy.active_versions(conn)
            if (
                reviews.input_digest(fields, prepared) != continuation.input_sha256
                or versions.policy_version != context.policy_version
                or versions.feed_version != context.feed_version
            ):
                trail.record(_human(Decision.DENY, ReasonCode.REVIEW_STALE))
                return _denied(context, trail, ReasonCode.REVIEW_STALE)
        else:
            assessed = await self._detect(trail, context, pinned, detector, state)
            if isinstance(assessed, ExecuteResponse):
                return assessed
            if isinstance(assessed, SemanticResult):
                review_id = reviews.enqueue(
                    self._db_path, context, request, fields, prepared, assessed, pinned
                )
                return ExecuteResponse(
                    request_id=context.request_id,
                    task_id=context.task_id,
                    decision=Decision.REQUIRE_APPROVAL,
                    reason_code=ReasonCode.REVIEW_REQUIRED,
                    policy_version=context.policy_version,
                    execution_status=getattr(trail.calls, TOOL_ADAPTERS[trail.tool]),
                    adapter_calls=trail.calls,
                    output=None,
                    redacted_fields=removed,
                    usage=tuple(trail.usage),
                    audit_event_ids=tuple(trail.event_ids),
                    review_id=review_id,
                )

        if summarizer is not None:
            return await self._summarize(
                trail, context, pinned, summarizer, engine, document, prepared, input_redaction
            )
        return ExecuteResponse(
            request_id=context.request_id,
            task_id=context.task_id,
            decision=input_redaction.decision,
            reason_code=input_redaction.reason_code,
            policy_version=context.policy_version,
            execution_status=ExecutionStatus.SUCCEEDED,
            adapter_calls=trail.calls,
            output=DocumentReadOutput(document_id=document.document_id, fields=shown.fields),
            redacted_fields=shown.removed,
            usage=tuple(trail.usage),
            audit_event_ids=tuple(trail.event_ids),
        )

    async def _admit_artifact(
        self,
        trail: RequestTrail,
        context: RequestContext,
        pinned: Policy,
        feed: Feed,
        request: ArtifactAdmitRequest,
    ) -> ExecuteResponse:
        """Manifest first; then one bounded read whose bytes are checked against the
        manifest digest and the pinned feed, and only then parsed."""
        if not pinned.controls.artifacts:
            # Without the check nothing is admitted; the switch never lets artifacts through.
            disabled = _artifacts(Decision.DENY, ReasonCode.TOOL_FORBIDDEN)
            trail.record(disabled)
            return _denied(context, trail, disabled.reason_code)

        entry = self._manifest.get(request.arguments.artifact_id)
        if entry is None:
            trail.record(artifacts.blocked())
            return _denied(context, trail, ReasonCode.ARTIFACT_BLOCKED)

        trail.record(_artifacts(Decision.ALLOW, ReasonCode.OK), starting="artifact_admit")
        started = time.perf_counter()
        try:
            data = await asyncio.to_thread(self._artifact_store.read, entry)
        except ArtifactReadError as exc:
            trail.finished("artifact_admit", ExecutionStatus.FAILED)
            reason = (
                ReasonCode.INPUT_TOO_LARGE
                if isinstance(exc, ArtifactTooLarge)
                else ReasonCode.UPSTREAM_FAILED
            )
            trail.record(
                _artifacts(Decision.DENY, reason),
                ExecutionStatus.FAILED,
                latency_ms=_elapsed_ms(started),
            )
            return _denied(context, trail, reason)
        trail.finished("artifact_admit", ExecutionStatus.SUCCEEDED)

        result, digest = artifacts.check_bytes(entry, data, feed)
        trail.record(result, ExecutionStatus.SUCCEEDED, latency_ms=_elapsed_ms(started))
        if result.decision is Decision.DENY:
            return _denied(context, trail, result.reason_code)
        return ExecuteResponse(
            request_id=context.request_id,
            task_id=context.task_id,
            decision=Decision.ALLOW,
            reason_code=ReasonCode.OK,
            policy_version=context.policy_version,
            execution_status=ExecutionStatus.SUCCEEDED,
            adapter_calls=trail.calls,
            output=ArtifactAdmitOutput(artifact_id=entry.artifact_id, sha256=digest),
            usage=tuple(trail.usage),
            audit_event_ids=tuple(trail.event_ids),
        )

    async def _detect(
        self,
        trail: RequestTrail,
        context: RequestContext,
        pinned: Policy,
        detector: SemanticEvaluator,
        state: dict[str, str],
    ) -> ExecuteResponse | SemanticResult | None:
        """Steps 5–6: reserve, call Jev once and apply the policy threshold. Returns the
        denial, or ``None`` when the request may continue."""
        limits = self._limits(trail, context, pinned, Stage.PRE_DETECTOR)
        if isinstance(limits, ExecuteResponse):
            return limits
        threshold = pinned.semantic.block_threshold
        calls = _TrackedDetector(trail, detector, threshold, pinned.models.detector_timeout_seconds)
        try:
            result, usage, _ = await provider_calls.assess_with_budget(
                db_path=self._db_path,
                context=context,
                adapter=calls,
                state=state,
                limits=limits,
                pricing=pinned.pricing.table(),
                max_detector_input_tokens=pinned.models.detector_reserved_input_tokens,
            )
        except budget.BudgetExceeded as exc:
            trail.record(_budget(Decision.DENY, exc.reason_code, Stage.PRE_DETECTOR))
            return _denied(context, trail, exc.reason_code)
        except (*DETECTOR_ERRORS, TimeoutError):
            trail.record(
                _semantic(Decision.DENY, ReasonCode.DETECTOR_UNAVAILABLE, Stage.PRE_DETECTOR),
                trail.calls.detector,
                latency_ms=calls.latency_ms,
                usage=calls.usage(),
            )
            return _denied(context, trail, ReasonCode.DETECTOR_UNAVAILABLE)

        blocked = result.risk_score >= threshold
        review = (
            not blocked
            and pinned.semantic.review_threshold is not None
            and result.risk_score >= pinned.semantic.review_threshold
        )
        trail.record(
            _semantic(
                Decision.DENY
                if blocked
                else Decision.REQUIRE_APPROVAL
                if review
                else Decision.ALLOW,
                ReasonCode.SEMANTIC_RISK
                if blocked
                else ReasonCode.REVIEW_REQUIRED
                if review
                else ReasonCode.OK,
                Stage.PRE_DETECTOR,
            ),
            ExecutionStatus.SUCCEEDED,
            latency_ms=calls.latency_ms,
            usage=(usage,),
            semantic=result,
        )
        if blocked:
            return _denied(context, trail, ReasonCode.SEMANTIC_RISK)
        return result if review else None

    async def _summarize(
        self,
        trail: RequestTrail,
        context: RequestContext,
        pinned: Policy,
        summarizer: Summarizer,
        engine: PiiEngine,
        document: CatalogEntry,
        prepared: ProviderInput,
        input_redaction: ControlResult,
    ) -> ExecuteResponse:
        """Steps 7–8: count, reserve and summarize once, then filter the output."""
        limits = self._limits(trail, context, pinned, Stage.PRE_SUMMARY)
        if isinstance(limits, ExecuteResponse):
            return limits
        calls = _TrackedSummarizer(trail, summarizer, pinned.models.summary_timeout_seconds)
        try:
            result = await provider_calls.summarize_with_budget(
                db_path=self._db_path,
                context=context,
                adapter=calls,
                input=prepared.summary_input(),
                limits=limits,
                pricing=pinned.pricing.table(),
                max_input_tokens=pinned.resources.max_summary_input_tokens,
                max_output_tokens=pinned.models.summary_max_output_tokens,
            )
        except budget.BudgetExceeded as exc:
            trail.record(
                _budget(Decision.DENY, exc.reason_code, Stage.PRE_SUMMARY), usage=calls.usage()
            )
            return _denied(context, trail, exc.reason_code)
        except provider_calls.InputTokenLimitExceeded:
            trail.record(
                _budget(Decision.DENY, ReasonCode.INPUT_TOO_LARGE, Stage.PRE_SUMMARY),
                trail.calls.token_count,
                latency_ms=calls.latency_ms,
                usage=calls.usage(),
            )
            return _denied(context, trail, ReasonCode.INPUT_TOO_LARGE)
        except (*SUMMARY_ERRORS, TimeoutError) as exc:
            if trail.calls.token_count is not ExecutionStatus.SUCCEEDED:
                failed = _budget(
                    Decision.DENY, ReasonCode.TOKEN_COUNT_UNAVAILABLE, Stage.PRE_SUMMARY
                )
                status = trail.calls.token_count
            else:
                reason = (
                    ReasonCode.UPSTREAM_TIMEOUT if _timed_out(exc) else ReasonCode.UPSTREAM_FAILED
                )
                failed = _gateway(Decision.DENY, reason, Stage.POST_OUTPUT)
                status = trail.calls.summary
            trail.record(failed, status, latency_ms=calls.latency_ms, usage=calls.usage())
            return _denied(context, trail, failed.reason_code)

        _, summary, count_usage, summary_usage, _, _ = result
        usage = (count_usage, summary_usage)
        try:
            text, found = await asyncio.to_thread(mask_text, summary.text, pinned.redaction, engine)
        except PiiEngineUnavailable:
            trail.record(
                _redaction_unavailable(Stage.POST_OUTPUT),
                ExecutionStatus.SUCCEEDED,
                latency_ms=calls.latency_ms,
                usage=usage,
            )
            return _denied(context, trail, ReasonCode.PII_ENGINE_UNAVAILABLE)
        counts = dict(sorted(found.items()))
        output_redaction = _redaction((), counts, Stage.POST_OUTPUT)
        trail.record(
            output_redaction,
            ExecutionStatus.SUCCEEDED,
            latency_ms=calls.latency_ms,
            entity_counts=counts,
            usage=usage,
        )

        redacted = Decision.REDACT in (input_redaction.decision, output_redaction.decision)
        return ExecuteResponse(
            request_id=context.request_id,
            task_id=context.task_id,
            decision=Decision.REDACT if redacted else Decision.ALLOW,
            reason_code=ReasonCode.PII_REDACTED if redacted else ReasonCode.OK,
            policy_version=context.policy_version,
            execution_status=ExecutionStatus.SUCCEEDED,
            adapter_calls=trail.calls,
            output=SummaryOutput(document_id=document.document_id, text=text),
            redacted_fields=prepared.removed,
            usage=tuple(trail.usage),
            audit_event_ids=tuple(trail.event_ids),
        )

    def _limits(
        self, trail: RequestTrail, context: RequestContext, pinned: Policy, stage: Stage
    ) -> BudgetLimits | ExecuteResponse:
        """Limits for the next reservation: the pinned policy's, each lowered to the active
        policy's value if an admin has activated another version since."""
        own = pinned.budget_limits(context.policy_version)
        with closing(db.connect(self._db_path)) as conn:
            version = policy.active_versions(conn).policy_version
            if version == context.policy_version:
                return own
            try:
                latest = None if version is None else policy.load(conn, "policy", version)
            except policy.StoredConfigError:
                latest = None
        if latest is None:
            trail.record(_budget(Decision.DENY, ReasonCode.INVALID_CONFIG, stage))
            return _denied(context, trail, ReasonCode.INVALID_CONFIG)
        current = latest.document.budget_limits(latest.version)
        lowest = {
            field.name: min(getattr(own, field.name), getattr(current, field.name))
            for field in dataclasses.fields(BudgetLimits)
            if field.name != "limit_version"
        }
        return BudgetLimits(**lowest, limit_version=latest.version)

    def _complete(self, context: RequestContext, response: ExecuteResponse) -> None:
        try:
            idempotency.complete(self._db_path, context.request_id, response)
        except sqlite3.Error as exc:
            # The row stays IN_PROGRESS: a retry with the key is answered as pending.
            logger.error(
                "response not stored: request_id=%s error=%s",
                context.request_id,
                type(exc).__name__,
            )

    def _abandon(self, context: RequestContext, trail: RequestTrail) -> None:
        try:
            idempotency.abandon(self._db_path, context.request_id, executed=trail.anything_called)
        except sqlite3.Error as exc:
            logger.error(
                "request not released: request_id=%s error=%s",
                context.request_id,
                type(exc).__name__,
            )


class _TrackedCalls:
    """Provider adapters as ``app.provider_calls`` calls them, after a reservation.

    Each call is preceded by its intent record, bounded by the policy timeout and its
    outcome is noted in the trail. The usage each adapter reported is kept for the audit
    of a failure that ``app.provider_calls`` raises after the call.
    """

    def __init__(self, trail: RequestTrail, stage: Stage, timeout_seconds: int) -> None:
        self._trail = trail
        self._stage = stage
        self._timeout = timeout_seconds
        self.latency_ms: int | None = None
        self._usage: list[Usage] = []

    async def _call(self, adapter: AdapterName, start: Callable[[], Awaitable[Any]]) -> Any:
        self._trail.record(_budget(Decision.ALLOW, ReasonCode.OK, self._stage), starting=adapter)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._timeout):
                result = await start()
        except BaseException as exc:
            self.latency_ms = _elapsed_ms(started)
            status = ExecutionStatus.UNKNOWN if _uncertain(exc) else ExecutionStatus.FAILED
            self._trail.finished(adapter, status)
            raise
        self.latency_ms = _elapsed_ms(started)
        self._trail.finished(adapter, ExecutionStatus.SUCCEEDED)
        return result

    def usage(self) -> tuple[Usage, ...]:
        """Usage as the adapters reported it, before ``app.provider_calls`` priced it."""
        return tuple(self._usage)


class _TrackedDetector(_TrackedCalls):
    def __init__(
        self,
        trail: RequestTrail,
        detector: SemanticEvaluator,
        threshold: float,
        timeout_seconds: int,
    ) -> None:
        super().__init__(trail, Stage.PRE_DETECTOR, timeout_seconds)
        self._detector = detector
        self._threshold = threshold

    async def assess(self, state: dict[str, str]) -> tuple[SemanticResult, Usage]:
        result, usage = await self._call(
            "detector",
            lambda: semantic.evaluate(self._detector, state=state, block_threshold=self._threshold),
        )
        self._usage.append(usage)
        return result, usage


class _TrackedSummarizer(_TrackedCalls):
    def __init__(self, trail: RequestTrail, summarizer: Summarizer, timeout_seconds: int) -> None:
        super().__init__(trail, Stage.PRE_SUMMARY, timeout_seconds)
        self._summarizer = summarizer

    async def count_input_tokens(self, *, input: str) -> TokenCount:
        count = await self._call(
            "token_count", lambda: self._summarizer.count_input_tokens(input=input)
        )
        self._usage.append(count.usage)
        return count

    async def summarize(self, *, input: str, **options: int) -> SummaryResult:
        summary = await self._call(
            "summary", lambda: self._summarizer.summarize(input=input, **options)
        )
        self._usage.append(summary.usage)
        return summary


def _trusted_task(tool: Tool, document: CatalogEntry, context: RequestContext) -> str:
    """Server-written description of the allowed task for Jev; no client text."""
    action = "Summarize" if tool is Tool.DOCUMENTS_SUMMARIZE else "Read"
    return (
        f"{action} document {document.document_id} of client {context.client_id} for a user"
        f" with the {context.role.value} role. Only the supplied document may be used;"
        " nothing may be sent, disclosed or retrieved beyond it."
    )


def _state_chars(state: dict[str, str]) -> int:
    """Size of what Jev receives: the state and the fixed questions."""
    return len(json.dumps({"state": state, "questions": SEMANTIC_QUESTIONS}))


def _timed_out(exc: BaseException) -> bool:
    """Whether a timeout caused ``exc``. Adapters re-raise their own errors ``from None``,
    which still keeps the original in ``__context__``."""
    current: BaseException | None = exc
    for _ in range(8):
        if current is None:
            return False
        if isinstance(current, TIMEOUT_ERRORS):
            return True
        current = current.__cause__ or current.__context__
    return False


def _uncertain(exc: BaseException) -> bool:
    """The provider may have processed (and billed) a call that timed out or was cut off."""
    return isinstance(exc, asyncio.CancelledError) or _timed_out(exc)


def _gateway(decision: Decision, reason_code: ReasonCode, stage: Stage) -> ControlResult:
    return ControlResult(
        control_id=ControlId.GATEWAY, decision=decision, reason_code=reason_code, stage=stage
    )


def _budget(decision: Decision, reason_code: ReasonCode, stage: Stage) -> ControlResult:
    return ControlResult(
        control_id=ControlId.BUDGET, decision=decision, reason_code=reason_code, stage=stage
    )


def _semantic(decision: Decision, reason_code: ReasonCode, stage: Stage) -> ControlResult:
    return ControlResult(
        control_id=ControlId.SEMANTIC, decision=decision, reason_code=reason_code, stage=stage
    )


def _redaction(removed: tuple[str, ...], counts: dict[str, int], stage: Stage) -> ControlResult:
    changed = bool(removed or counts)
    return ControlResult(
        control_id=ControlId.REDACTION,
        decision=Decision.REDACT if changed else Decision.ALLOW,
        reason_code=ReasonCode.PII_REDACTED if changed else ReasonCode.OK,
        stage=stage,
        redacted_fields=removed,
    )


def _artifacts(decision: Decision, reason_code: ReasonCode) -> ControlResult:
    return ControlResult(
        control_id=ControlId.ARTIFACTS,
        decision=decision,
        reason_code=reason_code,
        stage=Stage.ARTIFACT,
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
    context: RequestContext, trail: RequestTrail, reason_code: ReasonCode
) -> ExecuteResponse:
    """A denial; ``execution_status`` is that of the tool's own adapter so far, and
    ``usage`` lists the provider calls already made."""
    return ExecuteResponse(
        request_id=context.request_id,
        task_id=context.task_id,
        decision=Decision.DENY,
        reason_code=reason_code,
        policy_version=context.policy_version,
        execution_status=getattr(trail.calls, TOOL_ADAPTERS[trail.tool]),
        adapter_calls=trail.calls,
        output=None,
        usage=tuple(trail.usage),
        audit_event_ids=tuple(trail.event_ids),
    )


def _human(decision: Decision, reason: ReasonCode) -> ControlResult:
    return ControlResult(
        control_id=ControlId.HUMAN_REVIEW,
        decision=decision,
        reason_code=reason,
        stage=Stage.PRE_SUMMARY,
    )
