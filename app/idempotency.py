"""Stored requests of ``POST /v1/execute`` (docs/WSPOLNE_USTALENIA.md, sections 3–4).

Every admitted request gets a row in ``requests`` before any adapter runs. The row is
claimed in one write transaction together with the request limits of the pinned policy,
so two parallel requests cannot both take the last slot. ``app.budget`` checks the same
row (``IN_PROGRESS``) before each reservation.

The idempotency key belongs to the principal. The same key and body return the stored
response, which is already redacted, without running anything again; a different body
under that key is a conflict. A row without a stored response is still running or was
interrupted, and stays pending until resolved. Requests refused by a limit are not
stored, so the same key can be used again later.
"""

import hashlib
import math
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from app import db
from app.contracts import ExecuteResponse, ReasonCode, RequestContext, Tool, utc_now
from app.policy import ResourcesPolicy

RATE_WINDOW = timedelta(minutes=1)


@dataclass(frozen=True)
class Claimed:
    """The row is stored as ``IN_PROGRESS``; the request may run."""


@dataclass(frozen=True)
class Replay:
    response: ExecuteResponse


@dataclass(frozen=True)
class Pending:
    """The same request is running or its outcome is unresolved."""


@dataclass(frozen=True)
class Conflict:
    """The key was used for a different request."""


@dataclass(frozen=True)
class RateLimited:
    retry_after_seconds: int


@dataclass(frozen=True)
class LimitReached:
    reason_code: ReasonCode


Claim = Claimed | Replay | Pending | Conflict | RateLimited | LimitReached


def request_digest(body: BaseModel) -> str:
    """SHA-256 of the validated body; the body itself is never stored."""
    return hashlib.sha256(body.model_dump_json().encode()).hexdigest()


def claim(
    db_path: Path,
    context: RequestContext,
    *,
    tool: Tool,
    key: UUID,
    digest: str,
    resources: ResourcesPolicy,
    now: datetime,
) -> Claim:
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        stored = conn.execute(
            "SELECT request_sha256, response_body FROM requests"
            " WHERE principal_id = ? AND idempotency_key = ?",
            (context.principal_id, str(key)),
        ).fetchone()
        if stored is not None:
            if stored["request_sha256"] != digest:
                return Conflict()
            if stored["response_body"] is None:
                return Pending()
            return Replay(ExecuteResponse.model_validate_json(stored["response_body"]))

        recent, oldest = conn.execute(
            "SELECT count(*), min(created_at) FROM requests"
            " WHERE principal_id = ? AND created_at > ?",
            (context.principal_id, db.to_db_time(now - RATE_WINDOW)),
        ).fetchone()
        if recent >= resources.max_requests_per_minute_per_principal:
            wait = datetime.fromisoformat(oldest) + RATE_WINDOW - now
            return RateLimited(max(1, math.ceil(wait.total_seconds())))
        per_task = conn.execute(
            "SELECT count(*) FROM requests WHERE task_id = ?", (str(context.task_id),)
        ).fetchone()[0]
        if per_task >= resources.max_requests_per_task:
            return LimitReached(ReasonCode.BUDGET_EXCEEDED)
        running = conn.execute(
            "SELECT count(*) FROM requests WHERE principal_id = ? AND state = 'IN_PROGRESS'",
            (context.principal_id,),
        ).fetchone()[0]
        if running >= resources.max_concurrency_per_principal:
            return LimitReached(ReasonCode.CONCURRENCY_EXCEEDED)

        conn.execute(
            "INSERT INTO requests (request_id, principal_id, idempotency_key, request_sha256,"
            " task_id, tool, state, policy_version, feed_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'IN_PROGRESS', ?, ?, ?)",
            (
                str(context.request_id),
                context.principal_id,
                str(key),
                digest,
                str(context.task_id),
                tool.value,
                context.policy_version,
                context.feed_version,
                db.to_db_time(now),
            ),
        )
        return Claimed()


def complete(db_path: Path, request_id: UUID, response: ExecuteResponse) -> None:
    """Store the final response. A request whose provider outcome is uncertain keeps
    ``UNKNOWN`` (set by ``app.budget``) but still answers a retry with this response."""
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "UPDATE requests SET response_body = ?, completed_at = ?,"
            " state = CASE state WHEN 'IN_PROGRESS' THEN 'COMPLETED' ELSE state END"
            " WHERE request_id = ?",
            (response.model_dump_json(), db.to_db_time(utc_now()), str(request_id)),
        )


def abandon(db_path: Path, request_id: UUID, *, executed: bool) -> None:
    """Release a request that ends without a stored response.

    If nothing ran and nothing was reserved, the row is removed and the key can be used
    again. Otherwise the outcome is uncertain: the row becomes ``UNKNOWN``, which frees
    the concurrency slot but keeps the key pending.
    """
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        reserved = conn.execute(
            "SELECT 1 FROM reservations WHERE request_id = ? LIMIT 1", (str(request_id),)
        ).fetchone()
        if executed or reserved is not None:
            conn.execute(
                "UPDATE requests SET state = 'UNKNOWN'"
                " WHERE request_id = ? AND state = 'IN_PROGRESS'",
                (str(request_id),),
            )
        else:
            conn.execute(
                "DELETE FROM requests WHERE request_id = ? AND response_body IS NULL",
                (str(request_id),),
            )
