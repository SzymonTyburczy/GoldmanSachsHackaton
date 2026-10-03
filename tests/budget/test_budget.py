from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from uuid import UUID, uuid4

import pytest

from app import db
from app.budget import (
    BudgetContextError,
    BudgetExceeded,
    BudgetLimits,
    InvalidReservationState,
    balances,
    mark_started,
    mark_unknown,
    reconcile_after_restart,
    release_not_sent,
    reserve,
    settle,
)
from app.contracts import (
    BudgetUnit,
    ReasonCode,
    RequestContext,
    ReservationPurpose,
    ReservationState,
    Role,
)

NOW = "2026-10-03T00:00:00+00:00"
TASK_ID = UUID("11111111-1111-4111-8111-111111111111")
PRINCIPAL = "analyst-a"


def limits(
    *,
    task: int = 10_000,
    principal: int = 10_000,
    global_: int = 10_000,
    requests: int = 20,
    provider_calls: int = 40,
    concurrency: int = 20,
) -> BudgetLimits:
    return BudgetLimits(
        task_limit=task,
        principal_limit=principal,
        global_limit=global_,
        max_requests_per_task=requests,
        max_provider_calls_per_task=provider_calls,
        max_concurrency_per_principal=concurrency,
        max_tasks_per_principal=10,
        limit_version=1,
    )


def _prepare(db_path: Path, *, task_id: UUID = TASK_ID, count: int = 1) -> list[RequestContext]:
    db.init_db(db_path)
    contexts = []
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO tasks (task_id, principal_id, agent_id, client_id, created_at) "
            "VALUES (?, ?, 'demo-agent', 'client-a', ?)",
            (str(task_id), PRINCIPAL, NOW),
        )
        for _ in range(count):
            request_id = uuid4()
            idem = uuid4()
            conn.execute(
                """INSERT INTO requests
                   (request_id, principal_id, idempotency_key, request_sha256, task_id, tool,
                    state, created_at)
                   VALUES (?, ?, ?, ?, ?, 'documents.summarize', 'IN_PROGRESS', ?)""",
                (
                    str(request_id),
                    PRINCIPAL,
                    str(idem),
                    hashlib.sha256(str(request_id).encode()).hexdigest(),
                    str(task_id),
                    NOW,
                ),
            )
            contexts.append(
                RequestContext(
                    request_id=request_id,
                    task_id=task_id,
                    principal_id=PRINCIPAL,
                    agent_id="demo-agent",
                    role=Role.ANALYST,
                    client_id="client-a",
                    policy_version=1,
                    feed_version=1,
                    created_at=datetime.now(UTC),
                )
            )
    return contexts


def _reserve_fixture(db_path: Path, context: RequestContext, amount: int, lim: BudgetLimits):
    return reserve(
        db_path,
        context,
        ReservationPurpose.FIXTURE,
        BudgetUnit.TEST_CREDIT,
        amount,
        lim,
    )


def test_atomic_twenty_parallel_reservations_allow_exactly_five(db_path: Path) -> None:
    contexts = _prepare(db_path, count=20)
    lim = limits(task=500, principal=500, global_=500)

    denials_reached = Event()
    counter_lock = Lock()
    denied_count = 0
    provider_executions = 0

    def try_reserve(context: RequestContext):
        nonlocal denied_count, provider_executions
        try:
            reservation = _reserve_fixture(db_path, context, 100, lim)
        except BudgetExceeded as exc:
            with counter_lock:
                denied_count += 1
                if denied_count == 15:
                    denials_reached.set()
            return exc
        assert denials_reached.wait(timeout=5), "15 over-budget attempts did not get denied"
        mark_started(db_path, reservation.reservation_id)
        with counter_lock:
            provider_executions += 1
        return settle(db_path, reservation.reservation_id, 100)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(try_reserve, contexts))
    accepted = [result for result in results if not isinstance(result, BudgetExceeded)]
    rejected = [result for result in results if isinstance(result, BudgetExceeded)]

    assert len(accepted) == 5
    assert len(rejected) == 15
    assert provider_executions == 5
    assert all(result.reason_code is ReasonCode.BUDGET_EXCEEDED for result in rejected)
    assert all(result.state is ReservationState.SETTLED for result in accepted)
    assert balances(
        db_path, unit=BudgetUnit.TEST_CREDIT, task_id=TASK_ID, principal_id=PRINCIPAL
    ) == {
        "task": {"spent": 500, "reserved": 0},
        "principal": {"spent": 500, "reserved": 0},
        "global": {"spent": 500, "reserved": 0},
    }


def test_nusd_and_test_credits_have_independent_accounts(db_path: Path) -> None:
    context = _prepare(db_path)[0]
    fixture = _reserve_fixture(db_path, context, 100, limits())
    paid = reserve(
        db_path,
        context,
        ReservationPurpose.DETECTOR,
        BudgetUnit.NUSD,
        250,
        limits(),
        pricing_version="typesafe-test-pricing-v1",
    )

    assert fixture.unit is BudgetUnit.TEST_CREDIT
    assert paid.unit is BudgetUnit.NUSD
    assert (
        balances(db_path, unit=BudgetUnit.TEST_CREDIT, task_id=TASK_ID, principal_id=PRINCIPAL)[
            "global"
        ]["reserved"]
        == 100
    )
    assert (
        balances(db_path, unit=BudgetUnit.NUSD, task_id=TASK_ID, principal_id=PRINCIPAL)["global"][
            "reserved"
        ]
        == 250
    )


def test_parent_limit_is_not_reset_by_new_task(db_path: Path) -> None:
    context = _prepare(db_path)[0]
    lim = limits(task=1000, principal=100, global_=1000)
    _reserve_fixture(db_path, context, 100, lim)

    second_task = UUID("22222222-2222-4222-8222-222222222222")
    second_context = _prepare(db_path, task_id=second_task)[0]
    with pytest.raises(BudgetExceeded, match="principal budget"):
        _reserve_fixture(db_path, second_context, 1, lim)


def test_provider_call_and_request_quotas_are_enforced(db_path: Path, tmp_path: Path) -> None:
    request_contexts = _prepare(db_path, count=2)
    with pytest.raises(BudgetExceeded, match="request limit"):
        _reserve_fixture(db_path, request_contexts[0], 1, limits(requests=1))

    provider_db = tmp_path / "provider-quota.sqlite3"
    provider_contexts = _prepare(provider_db, count=2)
    provider_limits = limits(requests=2, provider_calls=1)
    first = reserve(
        provider_db,
        provider_contexts[0],
        ReservationPurpose.DETECTOR,
        BudgetUnit.NUSD,
        1,
        provider_limits,
        pricing_version="typesafe-test-pricing-v1",
    )
    # Mark the first call's request complete so only the provider-call quota is exercised.
    with closing(db.connect(provider_db)) as conn:
        conn.execute(
            "UPDATE requests SET state = 'COMPLETED' WHERE request_id = ?",
            (str(provider_contexts[0].request_id),),
        )
    with pytest.raises(BudgetExceeded, match="provider-call limit"):
        reserve(
            provider_db,
            provider_contexts[1],
            ReservationPurpose.SUMMARY,
            BudgetUnit.NUSD,
            1,
            provider_limits,
            pricing_version="typesafe-test-pricing-v1",
        )
    assert first.state is ReservationState.RESERVED


def test_concurrency_limit_uses_persisted_in_progress_requests(db_path: Path) -> None:
    contexts = _prepare(db_path, count=2)
    with pytest.raises(BudgetExceeded) as error:
        _reserve_fixture(db_path, contexts[0], 1, limits(concurrency=1))
    assert error.value.reason_code is ReasonCode.CONCURRENCY_EXCEEDED


def test_release_only_before_send_and_timeout_keeps_reservation(db_path: Path) -> None:
    context = _prepare(db_path)[0]
    reservation = _reserve_fixture(db_path, context, 100, limits())
    released = release_not_sent(db_path, reservation.reservation_id)
    assert released.state is ReservationState.RELEASED

    next_reservation = _reserve_fixture(db_path, context, 100, limits())
    mark_started(db_path, next_reservation.reservation_id)
    unknown = mark_unknown(db_path, next_reservation.reservation_id)
    assert unknown.state is ReservationState.UNKNOWN
    with closing(db.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT state FROM requests WHERE request_id = ?", (str(context.request_id),)
            ).fetchone()["state"]
            == "UNKNOWN"
        )
    assert balances(
        db_path, unit=BudgetUnit.TEST_CREDIT, task_id=TASK_ID, principal_id=PRINCIPAL
    ) == {
        "task": {"spent": 0, "reserved": 100},
        "principal": {"spent": 0, "reserved": 100},
        "global": {"spent": 0, "reserved": 100},
    }
    with pytest.raises(InvalidReservationState):
        release_not_sent(db_path, next_reservation.reservation_id)
    settled = settle(db_path, next_reservation.reservation_id, 80)
    assert settled.state is ReservationState.SETTLED


def test_restart_conservatively_marks_unresolved_reservations_unknown(db_path: Path) -> None:
    context = _prepare(db_path)[0]
    reservation = _reserve_fixture(db_path, context, 100, limits())
    mark_started(db_path, reservation.reservation_id)

    assert reconcile_after_restart(db_path) == 1
    with closing(db.connect(db_path)) as conn:
        state = conn.execute(
            "SELECT state FROM reservations WHERE reservation_id = ?",
            (str(reservation.reservation_id),),
        ).fetchone()["state"]
    assert state == ReservationState.UNKNOWN.value
    with closing(db.connect(db_path)) as conn:
        request_state = conn.execute(
            "SELECT state FROM requests WHERE request_id = ?", (str(context.request_id),)
        ).fetchone()["state"]
    assert request_state == "UNKNOWN"
    assert (
        balances(db_path, unit=BudgetUnit.TEST_CREDIT, task_id=TASK_ID, principal_id=PRINCIPAL)[
            "global"
        ]["reserved"]
        == 100
    )


def test_unknown_provider_call_keeps_provider_slot_after_http_request_is_released(
    db_path: Path,
) -> None:
    contexts = _prepare(db_path, count=4)
    lim = limits(concurrency=3)
    with closing(db.connect(db_path)) as conn:
        conn.execute("UPDATE requests SET state = 'COMPLETED'")
    for context in contexts[:3]:
        with closing(db.connect(db_path)) as conn:
            conn.execute(
                "UPDATE requests SET state = 'IN_PROGRESS' WHERE request_id = ?",
                (str(context.request_id),),
            )
        reservation = reserve(
            db_path,
            context,
            ReservationPurpose.DETECTOR,
            BudgetUnit.NUSD,
            10,
            lim,
            pricing_version="typesafe-test-pricing-v1",
        )
        mark_started(db_path, reservation.reservation_id)
        mark_unknown(db_path, reservation.reservation_id)

    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "UPDATE requests SET state = 'IN_PROGRESS' WHERE request_id = ?",
            (str(contexts[3].request_id),),
        )
    # HTTP slots are released, but three uncertain calls keep the provider slots occupied.
    with pytest.raises(BudgetExceeded) as error:
        reserve(
            db_path,
            contexts[3],
            ReservationPurpose.SUMMARY,
            BudgetUnit.NUSD,
            10,
            lim,
            pricing_version="openai-test-pricing-v1",
        )
    assert error.value.reason_code is ReasonCode.CONCURRENCY_EXCEEDED


def test_context_must_match_server_owned_task_and_request(db_path: Path) -> None:
    context = _prepare(db_path)[0]
    forged = context.model_copy(update={"principal_id": "reviewer-a"})
    with pytest.raises(BudgetContextError):
        _reserve_fixture(db_path, forged, 1, limits())


def test_failed_transaction_does_not_leave_partial_accounts(db_path: Path) -> None:
    context = _prepare(db_path)[0]
    with pytest.raises(BudgetExceeded):
        _reserve_fixture(db_path, context, 101, limits(task=100, principal=1000, global_=1000))
    assert balances(
        db_path, unit=BudgetUnit.TEST_CREDIT, task_id=TASK_ID, principal_id=PRINCIPAL
    ) == {
        "task": {"spent": 0, "reserved": 0},
        "principal": {"spent": 0, "reserved": 0},
        "global": {"spent": 0, "reserved": 0},
    }


def test_budget_rejects_invalid_units_and_amounts(db_path: Path) -> None:
    context = _prepare(db_path)[0]
    with pytest.raises(ValueError):
        reserve(db_path, context, ReservationPurpose.FIXTURE, BudgetUnit.NUSD, 1, limits())
    with pytest.raises(ValueError):
        reserve(db_path, context, ReservationPurpose.FIXTURE, BudgetUnit.TEST_CREDIT, 0, limits())
