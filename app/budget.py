"""Transactional SQLite budget reservations and provider-operation limits."""

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from app import db
from app.contracts import (
    BudgetUnit,
    ReasonCode,
    RequestContext,
    Reservation,
    ReservationPurpose,
    ReservationState,
)


class BudgetError(RuntimeError):
    """Base class for safe budget-control failures."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class BudgetExceeded(BudgetError):
    """A configured money, request, provider-call, or concurrency limit was reached."""


class ReservationNotFound(BudgetError):
    def __init__(self) -> None:
        super().__init__(ReasonCode.INVALID_INPUT, "reservation not found")


class InvalidReservationState(BudgetError):
    def __init__(self, state: str, operation: str) -> None:
        super().__init__(ReasonCode.INVALID_INPUT, f"cannot {operation} reservation in {state}")


class BudgetContextError(BudgetError):
    def __init__(self) -> None:
        super().__init__(ReasonCode.TASK_FORBIDDEN, "request context does not match stored task")


@dataclass(frozen=True)
class BudgetLimits:
    """Snapshot of policy limits to apply to one reservation attempt."""

    task_limit: int
    principal_limit: int
    global_limit: int
    max_requests_per_task: int
    max_provider_calls_per_task: int
    max_concurrency_per_principal: int
    max_tasks_per_principal: int = 10
    limit_version: int = 1

    def __post_init__(self) -> None:
        values = (
            self.task_limit,
            self.principal_limit,
            self.global_limit,
            self.max_requests_per_task,
            self.max_provider_calls_per_task,
            self.max_concurrency_per_principal,
            self.max_tasks_per_principal,
            self.limit_version,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("budget limits and limit_version must be positive integers")


@dataclass(frozen=True)
class _Scope:
    scope: str
    scope_id: str
    limit: int


def reserve(
    db_path: Path,
    context: RequestContext,
    purpose: ReservationPurpose,
    unit: BudgetUnit,
    amount: int,
    limits: BudgetLimits,
    *,
    pricing_version: str | None = None,
) -> Reservation:
    """Atomically enforce parent budgets/quotas and record one durable reservation.

    Caller must have persisted the request as IN_PROGRESS before calling. No transaction
    is held open during provider work. ``test_credit`` is accepted only for fixture calls.
    """
    purpose = ReservationPurpose(purpose)
    unit = BudgetUnit(unit)
    if type(amount) is not int or amount <= 0:
        raise ValueError("reservation amount must be a positive integer")
    if (purpose is ReservationPurpose.FIXTURE) != (unit is BudgetUnit.TEST_CREDIT):
        raise ValueError("test_credit is reserved for fixture operations only")
    if unit is BudgetUnit.NUSD and not pricing_version:
        raise ValueError("nusd reservations require a pricing_version")
    # Validate the version and other contract fields before opening a write transaction.
    pricing_version_value = pricing_version if unit is BudgetUnit.NUSD else None
    reservation_id = uuid4()
    now = _now()
    scopes = (
        _Scope("task", str(context.task_id), limits.task_limit),
        _Scope("principal", context.principal_id, limits.principal_limit),
        _Scope("global", "global", limits.global_limit),
    )

    with closing(db.connect(db_path)) as conn, _write_transaction(conn):
        _validate_request_context(conn, context, limits)
        _validate_quotas(conn, context, purpose, limits)
        for scope in scopes:
            conn.execute(
                """INSERT OR IGNORE INTO budget_accounts
                       (scope, scope_id, unit, spent, reserved, updated_at)
                       VALUES (?, ?, ?, 0, 0, ?)""",
                (scope.scope, scope.scope_id, unit.value, now),
            )
            row = conn.execute(
                """SELECT spent, reserved FROM budget_accounts
                       WHERE scope = ? AND scope_id = ? AND unit = ?""",
                (scope.scope, scope.scope_id, unit.value),
            ).fetchone()
            if row is None:
                raise RuntimeError("budget account disappeared during reservation")
            if row["spent"] + row["reserved"] + amount > scope.limit:
                raise BudgetExceeded(ReasonCode.BUDGET_EXCEEDED, f"{scope.scope} budget exceeded")
            conn.execute(
                """UPDATE budget_accounts SET reserved = reserved + ?, updated_at = ?
                   WHERE scope = ? AND scope_id = ? AND unit = ?""",
                (amount, now, scope.scope, scope.scope_id, unit.value),
            )
        conn.execute(
            """INSERT INTO reservations
                   (reservation_id, request_id, task_id, principal_id, purpose, unit, amount,
                    settled_amount, state, pricing_version, limit_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
            (
                str(reservation_id),
                str(context.request_id),
                str(context.task_id),
                context.principal_id,
                purpose.value,
                unit.value,
                amount,
                ReservationState.RESERVED.value,
                pricing_version_value,
                limits.limit_version,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM reservations WHERE reservation_id = ?", (str(reservation_id),)
        ).fetchone()
        return _reservation_from_row(row)


def mark_started(db_path: Path, reservation_id: UUID) -> Reservation:
    """Persist intent immediately before sending a provider request."""
    return _transition(
        db_path, reservation_id, {ReservationState.RESERVED}, ReservationState.STARTED
    )


def settle(db_path: Path, reservation_id: UUID, actual_usage: int) -> Reservation:
    """Move reserved units to spent after known provider usage; actual may exceed reserve."""
    if type(actual_usage) is not int or actual_usage < 0:
        raise ValueError("actual_usage must be a non-negative integer")
    now = _now()
    with closing(db.connect(db_path)) as conn, _write_transaction(conn):
        row = _get_reservation(conn, reservation_id)
        state = ReservationState(row["state"])
        if state not in {ReservationState.STARTED, ReservationState.UNKNOWN}:
            raise InvalidReservationState(state.value, "settle")
        _adjust_accounts(
            conn, row, spent_delta=actual_usage, reserved_delta=-row["amount"], now=now
        )
        conn.execute(
            """UPDATE reservations SET state = ?, settled_amount = ?, updated_at = ?
               WHERE reservation_id = ?""",
            (ReservationState.SETTLED.value, actual_usage, now, str(reservation_id)),
        )
        return _read_reservation(conn, reservation_id)


def release_not_sent(db_path: Path, reservation_id: UUID) -> Reservation:
    """Release a reservation only while no upstream call has started."""
    now = _now()
    with closing(db.connect(db_path)) as conn, _write_transaction(conn):
        row = _get_reservation(conn, reservation_id)
        state = ReservationState(row["state"])
        if state is not ReservationState.RESERVED:
            raise InvalidReservationState(state.value, "release")
        _adjust_accounts(conn, row, spent_delta=0, reserved_delta=-row["amount"], now=now)
        conn.execute(
            "UPDATE reservations SET state = ?, updated_at = ? WHERE reservation_id = ?",
            (ReservationState.RELEASED.value, now, str(reservation_id)),
        )
        return _read_reservation(conn, reservation_id)


def mark_unknown(db_path: Path, reservation_id: UUID) -> Reservation:
    """Retain funds and provider-call slot when the upstream outcome is uncertain."""
    return _transition(
        db_path,
        reservation_id,
        {ReservationState.RESERVED, ReservationState.STARTED},
        ReservationState.UNKNOWN,
    )


def reconcile_after_restart(db_path: Path) -> int:
    """Conservatively turn stranded reservations into UNKNOWN without freeing balances."""
    now = _now()
    with closing(db.connect(db_path)) as conn, _write_transaction(conn):
        cursor = conn.execute(
            """UPDATE reservations SET state = ?, updated_at = ?
                   WHERE state IN (?, ?)""",
            (
                ReservationState.UNKNOWN.value,
                now,
                ReservationState.RESERVED.value,
                ReservationState.STARTED.value,
            ),
        )
        conn.execute("UPDATE requests SET state = 'UNKNOWN' WHERE state = 'IN_PROGRESS'")
        return cursor.rowcount


def get_reservation(db_path: Path, reservation_id: UUID) -> Reservation:
    """Read one reservation without mutating balances or lifecycle state."""
    with closing(db.connect(db_path)) as conn:
        return _read_reservation(conn, reservation_id)


def balances(
    db_path: Path, *, unit: BudgetUnit, task_id: UUID, principal_id: str
) -> dict[str, dict[str, int]]:
    """Read current spent/reserved figures for each budget scope."""
    scopes = (
        ("task", str(task_id)),
        ("principal", principal_id),
        ("global", "global"),
    )
    with closing(db.connect(db_path)) as conn:
        result = {}
        for scope, scope_id in scopes:
            row = conn.execute(
                """SELECT spent, reserved FROM budget_accounts
                   WHERE scope = ? AND scope_id = ? AND unit = ?""",
                (scope, scope_id, unit.value),
            ).fetchone()
            result[scope] = (
                {"spent": 0, "reserved": 0}
                if row is None
                else {
                    "spent": row["spent"],
                    "reserved": row["reserved"],
                }
            )
        return result


def _validate_request_context(
    conn: sqlite3.Connection, context: RequestContext, limits: BudgetLimits
) -> None:
    request = conn.execute(
        """SELECT principal_id, task_id, state FROM requests WHERE request_id = ?""",
        (str(context.request_id),),
    ).fetchone()
    task = conn.execute(
        "SELECT principal_id, agent_id, client_id FROM tasks WHERE task_id = ?",
        (str(context.task_id),),
    ).fetchone()
    if (
        request is None
        or task is None
        or request["state"] != "IN_PROGRESS"
        or request["principal_id"] != context.principal_id
        or request["task_id"] != str(context.task_id)
        or task["principal_id"] != context.principal_id
        or task["agent_id"] != context.agent_id
        or task["client_id"] != context.client_id
    ):
        raise BudgetContextError()
    task_count = conn.execute(
        "SELECT count(*) FROM tasks WHERE principal_id = ?", (context.principal_id,)
    ).fetchone()[0]
    if task_count > limits.max_tasks_per_principal:
        raise BudgetExceeded(ReasonCode.BUDGET_EXCEEDED, "principal task limit exceeded")


def _validate_quotas(
    conn: sqlite3.Connection,
    context: RequestContext,
    purpose: ReservationPurpose,
    limits: BudgetLimits,
) -> None:
    request_count = conn.execute(
        "SELECT count(*) FROM requests WHERE task_id = ?", (str(context.task_id),)
    ).fetchone()[0]
    if request_count > limits.max_requests_per_task:
        raise BudgetExceeded(ReasonCode.BUDGET_EXCEEDED, "task request limit exceeded")
    concurrency = conn.execute(
        """SELECT count(*) FROM requests WHERE principal_id = ? AND state = 'IN_PROGRESS'""",
        (context.principal_id,),
    ).fetchone()[0]
    if concurrency > limits.max_concurrency_per_principal:
        raise BudgetExceeded(
            ReasonCode.CONCURRENCY_EXCEEDED, "principal concurrency limit exceeded"
        )
    if purpose is not ReservationPurpose.FIXTURE:
        provider_calls = conn.execute(
            """SELECT count(*) FROM reservations
               WHERE task_id = ? AND purpose IN ('detector', 'summary') AND state <> 'RELEASED'""",
            (str(context.task_id),),
        ).fetchone()[0]
        if provider_calls >= limits.max_provider_calls_per_task:
            raise BudgetExceeded(ReasonCode.BUDGET_EXCEEDED, "task provider-call limit exceeded")
        active_provider_calls = conn.execute(
            """SELECT count(*) FROM reservations
               WHERE principal_id = ? AND purpose IN ('detector', 'summary')
                 AND state IN ('RESERVED', 'STARTED', 'UNKNOWN')""",
            (context.principal_id,),
        ).fetchone()[0]
        if active_provider_calls >= limits.max_concurrency_per_principal:
            raise BudgetExceeded(
                ReasonCode.CONCURRENCY_EXCEEDED, "principal provider concurrency limit exceeded"
            )


def _transition(
    db_path: Path,
    reservation_id: UUID,
    allowed_states: set[ReservationState],
    target_state: ReservationState,
) -> Reservation:
    now = _now()
    with closing(db.connect(db_path)) as conn, _write_transaction(conn):
        row = _get_reservation(conn, reservation_id)
        state = ReservationState(row["state"])
        if state not in allowed_states:
            raise InvalidReservationState(state.value, target_state.value.lower())
        conn.execute(
            "UPDATE reservations SET state = ?, updated_at = ? WHERE reservation_id = ?",
            (target_state.value, now, str(reservation_id)),
        )
        if target_state is ReservationState.UNKNOWN:
            conn.execute(
                """UPDATE requests SET state = 'UNKNOWN'
                   WHERE request_id = ? AND state = 'IN_PROGRESS'""",
                (row["request_id"],),
            )
        return _read_reservation(conn, reservation_id)


def _adjust_accounts(
    conn: sqlite3.Connection,
    reservation: sqlite3.Row,
    *,
    spent_delta: int,
    reserved_delta: int,
    now: str,
) -> None:
    scopes = (
        ("task", reservation["task_id"]),
        ("principal", reservation["principal_id"]),
        ("global", "global"),
    )
    for scope, scope_id in scopes:
        cursor = conn.execute(
            """UPDATE budget_accounts
               SET spent = spent + ?, reserved = reserved + ?, updated_at = ?
               WHERE scope = ? AND scope_id = ? AND unit = ? AND reserved >= ?""",
            (
                spent_delta,
                reserved_delta,
                now,
                scope,
                scope_id,
                reservation["unit"],
                -reserved_delta,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("budget balance invariant violated")


def _get_reservation(conn: sqlite3.Connection, reservation_id: UUID) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM reservations WHERE reservation_id = ?", (str(reservation_id),)
    ).fetchone()
    if row is None:
        raise ReservationNotFound()
    return row


def _read_reservation(conn: sqlite3.Connection, reservation_id: UUID) -> Reservation:
    return _reservation_from_row(_get_reservation(conn, reservation_id))


def _reservation_from_row(row: sqlite3.Row) -> Reservation:
    return Reservation.model_validate(
        {
            "reservation_id": row["reservation_id"],
            "request_id": row["request_id"],
            "task_id": row["task_id"],
            "principal_id": row["principal_id"],
            "purpose": row["purpose"],
            "unit": row["unit"],
            "amount": row["amount"],
            "state": row["state"],
            "created_at": row["created_at"],
            "pricing_version": row["pricing_version"],
            "limit_version": row["limit_version"],
        }
    )


def _write_transaction(conn: sqlite3.Connection):
    """Retry only SQLite busy/locked transactions, never provider operations."""
    attempts = 4
    for attempt in range(attempts):
        try:
            return _TransactionAttempt(conn)
        except sqlite3.OperationalError as exc:
            if not _is_busy(exc) or attempt == attempts - 1:
                raise
            time.sleep(0.02 * (2**attempt))
    raise AssertionError("unreachable")


class _TransactionAttempt:
    """Context wrapper so the bounded retry includes BEGIN IMMEDIATE."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        conn.execute("BEGIN IMMEDIATE")

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is not None:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            return False
        self._conn.execute("COMMIT")
        return False


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _now() -> str:
    return datetime.now(UTC).isoformat()
