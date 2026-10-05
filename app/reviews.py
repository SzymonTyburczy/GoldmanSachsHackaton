"""Durable, single-use human review of an evaluated, masked operation."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import TypeAdapter

from app import db, policy
from app.api.errors import ApiError
from app.auth import Principal
from app.contracts import (
    ExecuteRequest,
    ExecuteResponse,
    HumanReview,
    HumanReviewPage,
    ReasonCode,
    RequestContext,
    Role,
    SemanticResult,
    Tool,
    utc_now,
)
from app.controls.redaction import ProviderInput
from app.policy import Policy

REQUEST_ADAPTER = TypeAdapter(ExecuteRequest)


@dataclass(frozen=True)
class Continuation:
    context: RequestContext
    request: ExecuteRequest
    input_sha256: str
    pending: ExecuteResponse
    review: HumanReview


def input_digest(fields: dict[str, str], prepared: ProviderInput) -> str:
    """Bind every document field, including removed fields, without persisting values."""
    value = {"fields": fields, "document": prepared.document, "prompt": prepared.prompt}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def enqueue(
    db_path: Path,
    context: RequestContext,
    request: ExecuteRequest,
    fields: dict[str, str],
    prepared: ProviderInput,
    result: SemanticResult,
    pinned: Policy,
) -> UUID:
    now = utc_now()
    safe = request
    if request.tool == "documents.summarize":
        safe = request.model_copy(
            update={"arguments": request.arguments.model_copy(update={"prompt": prepared.prompt})}
        )
    item = HumanReview(
        review_id=context.request_id,
        request_id=context.request_id,
        task_id=context.task_id,
        principal_id=context.principal_id,
        agent_id=context.agent_id,
        client_id=context.client_id,
        tool=Tool(request.tool),
        document_id=request.arguments.document_id,
        policy_version=context.policy_version,
        feed_version=context.feed_version,
        risk_score=result.risk_score,
        review_threshold=pinned.semantic.review_threshold,
        block_threshold=pinned.semantic.block_threshold,
        status="PENDING",
        created_at=now,
        expires_at=now + timedelta(seconds=pinned.semantic.review_timeout_seconds),
        masked_prompt=prepared.prompt,
        masked_document=prepared.document,
    )
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO human_reviews (request_id, context_json, safe_request_json,"
            " input_sha256, review_json, state) VALUES (?, ?, ?, ?, ?, 'PENDING')",
            (
                str(context.request_id),
                context.model_dump_json(),
                safe.model_dump_json(),
                input_digest(fields, prepared),
                item.model_dump_json(),
            ),
        )
    return item.review_id


def can_review(principal: Principal, item: HumanReview) -> bool:
    return (
        principal.role in (Role.REVIEWER, Role.ADMIN)
        and item.principal_id != principal.principal_id
        and (principal.role is Role.ADMIN or item.client_id in principal.client_ids)
    )


def _view(row: sqlite3.Row) -> HumanReview:
    item = HumanReview.model_validate_json(row["review_json"])
    response = row["response_body"]
    reason = None
    if response and row["state"] not in ("PENDING", "RUNNING"):
        reason = ExecuteResponse.model_validate_json(response).reason_code
    return item.model_copy(update={"status": row["state"], "result_reason_code": reason})


_SELECT = "SELECT h.*, r.response_body FROM human_reviews h JOIN requests r USING (request_id)"


def _visible(conn: sqlite3.Connection, row: sqlite3.Row, principal: Principal) -> HumanReview:
    item = _view(row)
    try:
        active = policy.load_active(conn, "policy")
        context = RequestContext.model_validate_json(row["context_json"])
        allowed = (
            active is not None
            and active.version == item.policy_version
            and active.document.outbound_fields_for(context.role)
            <= active.document.fields_for(principal.role)
        )
    except policy.StoredConfigError:
        allowed = False
    if not allowed:
        return item.model_copy(
            update={
                "masked_prompt": None,
                "masked_document": "Input preview is unavailable under the current policy.",
            }
        )
    return item


def list_reviews(db_path: Path, principal: Principal, limit: int = 50) -> HumanReviewPage:
    if principal.role not in (Role.REVIEWER, Role.ADMIN):
        raise ApiError(403, ReasonCode.REVIEW_FORBIDDEN)
    maintain(db_path)
    with closing(db.connect(db_path)) as conn:
        # Filter before LIMIT so another client's queue cannot hide this client's items.
        rows = conn.execute(_SELECT + " ORDER BY (h.state = 'PENDING') DESC, r.created_at DESC")
        items = []
        for row in rows:
            item = _view(row)
            if can_review(principal, item):
                items.append(_visible(conn, row, principal))
                if len(items) == limit:
                    break
    return HumanReviewPage(reviews=tuple(items))


def get_review(db_path: Path, principal: Principal, review_id: UUID) -> HumanReview:
    with closing(db.connect(db_path)) as conn:
        row = conn.execute(_SELECT + " WHERE h.request_id = ?", (str(review_id),)).fetchone()
        if row is None:
            raise ApiError(404, ReasonCode.REVIEW_FORBIDDEN)
        item = _view(row)
        if item.principal_id != principal.principal_id and not can_review(principal, item):
            raise ApiError(403, ReasonCode.REVIEW_FORBIDDEN)
        return _visible(conn, row, principal)


def get_response(db_path: Path, principal: Principal, request_id: UUID) -> ExecuteResponse:
    maintain(db_path)
    with closing(db.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM requests WHERE request_id = ?", (str(request_id),)
        ).fetchone()
    if row is None or (
        row["principal_id"] != principal.principal_id and principal.role is not Role.ADMIN
    ):
        raise ApiError(403, ReasonCode.TASK_FORBIDDEN)
    if row["response_body"] is None:
        raise ApiError(409, ReasonCode.REQUEST_PENDING)
    return ExecuteResponse.model_validate_json(row["response_body"])


def claim(db_path: Path, principal: Principal, review_id: UUID, pinned: Policy) -> Continuation:
    """One reviewer wins the transaction; a replay can never execute a second time."""
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        row = conn.execute(_SELECT + " WHERE h.request_id = ?", (str(review_id),)).fetchone()
        if row is None:
            raise ApiError(404, ReasonCode.REVIEW_FORBIDDEN)
        item = _view(row)
        if not can_review(principal, item):
            raise ApiError(403, ReasonCode.REVIEW_FORBIDDEN)
        if row["state"] != "PENDING":
            raise ApiError(409, ReasonCode.REVIEW_RESOLVED)
        if row["response_body"] is None:
            raise ApiError(409, ReasonCode.REQUEST_PENDING)
        running = conn.execute(
            "SELECT count(*) FROM requests WHERE principal_id = ? AND state = 'IN_PROGRESS'",
            (item.principal_id,),
        ).fetchone()[0]
        if running >= pinned.resources.max_concurrency_per_principal:
            raise ApiError(429, ReasonCode.CONCURRENCY_EXCEEDED)
        decided = item.model_copy(
            update={
                "status": "RUNNING",
                "reviewer_id": principal.principal_id,
                "decided_at": utc_now(),
            }
        )
        conn.execute(
            "UPDATE human_reviews SET state = 'RUNNING', review_json = ? WHERE request_id = ?",
            (decided.model_dump_json(), str(review_id)),
        )
        conn.execute(
            "UPDATE requests SET state = 'IN_PROGRESS', completed_at = NULL WHERE request_id = ?",
            (str(review_id),),
        )
        return Continuation(
            RequestContext.model_validate_json(row["context_json"]),
            REQUEST_ADAPTER.validate_json(row["safe_request_json"]),
            row["input_sha256"],
            ExecuteResponse.model_validate_json(row["response_body"]),
            decided,
        )


def finish(db_path: Path, review_id: UUID, status: str) -> None:
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "UPDATE human_reviews SET state = ? WHERE request_id = ? AND state = 'RUNNING'",
            (status, str(review_id)),
        )


def reconcile(db_path: Path) -> None:
    """Interrupted approvals are uncertain and must never be automatically retried."""
    with closing(db.connect(db_path)) as conn:
        conn.execute("UPDATE human_reviews SET state = 'UNKNOWN' WHERE state = 'RUNNING'")


def maintain(db_path: Path) -> None:
    try:
        _maintain(db_path)
    except sqlite3.Error:
        raise ApiError(503, ReasonCode.AUDIT_UNAVAILABLE) from None


def _maintain(db_path: Path) -> None:
    """Close expired reviews and expose interrupted continuations without replaying them.

    The terminal audit record and response are written in the same transaction. This
    runs on reads too, so the owner's polling observes expiry without a reviewer click.
    """
    from app.contracts import (
        AdapterCalls,
        AuditEvent,
        ControlId,
        Decision,
        ExecutionStatus,
        Stage,
    )

    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        rows = conn.execute(_SELECT + " WHERE h.state IN ('PENDING', 'UNKNOWN')").fetchall()
        for row in rows:
            item = _view(row)
            if not row["response_body"]:
                continue
            pending = ExecuteResponse.model_validate_json(row["response_body"])
            if pending.decision is not Decision.REQUIRE_APPROVAL:
                continue
            expired = item.status == "PENDING" and item.expires_at <= utc_now()
            if not expired and item.status != "UNKNOWN":
                continue
            context = RequestContext.model_validate_json(row["context_json"])
            records = conn.execute(
                "SELECT event_json FROM audit_events WHERE request_id = ? ORDER BY seq",
                (row["request_id"],),
            ).fetchall()
            events = [AuditEvent.model_validate_json(record[0]) for record in records]
            calls = events[-1].adapter_calls if events else pending.adapter_calls
            calls = AdapterCalls.model_validate(
                {
                    key: ExecutionStatus.UNKNOWN if value is ExecutionStatus.STARTED else value
                    for key, value in calls.model_dump().items()
                }
            )
            reason = ReasonCode.REVIEW_EXPIRED if expired else ReasonCode.REQUEST_PENDING
            event = AuditEvent(
                event_id=uuid4(),
                request_id=context.request_id,
                task_id=context.task_id,
                principal_id=context.principal_id,
                agent_id=context.agent_id,
                client_id=context.client_id,
                occurred_at=utc_now(),
                tool=item.tool,
                control_id=ControlId.HUMAN_REVIEW,
                decision=Decision.DENY,
                reason_code=reason,
                stage=Stage.PRE_SUMMARY,
                execution_status=ExecutionStatus.NOT_CALLED,
                adapter_calls=calls,
                latency_ms=None,
                model=None,
                policy_version=context.policy_version,
                feed_version=context.feed_version,
            )
            conn.execute(
                "INSERT INTO audit_events (event_id, request_id, task_id, principal_id,"
                " occurred_at, control_id, decision, reason_code, stage, execution_status,"
                " policy_version, feed_version, event_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(event.event_id),
                    row["request_id"],
                    str(context.task_id),
                    context.principal_id,
                    db.to_db_time(event.occurred_at),
                    event.control_id,
                    event.decision,
                    reason,
                    event.stage,
                    event.execution_status,
                    context.policy_version,
                    context.feed_version,
                    event.model_dump_json(),
                ),
            )
            adapter = "document_read" if item.tool is Tool.DOCUMENTS_READ else "summary"
            response = pending.model_copy(
                update={
                    "decision": Decision.DENY,
                    "reason_code": reason,
                    "review_id": None,
                    "adapter_calls": calls,
                    "execution_status": getattr(calls, adapter),
                    "audit_event_ids": tuple(e.event_id for e in events) + (event.event_id,),
                    "usage": tuple(usage for e in events for usage in e.usage),
                }
            )
            conn.execute(
                "UPDATE requests SET response_body = ?, completed_at = ? WHERE request_id = ?",
                (response.model_dump_json(), db.to_db_time(utc_now()), row["request_id"]),
            )
            if expired:
                conn.execute(
                    "UPDATE human_reviews SET state = 'EXPIRED' WHERE request_id = ?",
                    (row["request_id"],),
                )
