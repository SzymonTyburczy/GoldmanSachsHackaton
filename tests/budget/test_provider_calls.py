from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app import db
from app.adapters.openai_luna import OpenAILunaAdapter, SummaryResult, TokenCount
from app.budget import BudgetExceeded, BudgetLimits, balances, get_reservation
from app.contracts import (
    BudgetUnit,
    CostStatus,
    Provider,
    RequestContext,
    ReservationState,
    Role,
    SemanticCategory,
    SemanticResult,
    Usage,
)
from app.pricing import DEFAULT_PRICING, reserve_openai_nusd
from app.provider_calls import (
    InputTokenLimitExceeded,
    assess_with_budget,
    summarize_with_budget,
)

TASK_ID = UUID("33333333-3333-4333-8333-333333333333")
PRINCIPAL = "analyst-a"
NOW = "2026-10-03T00:00:00+00:00"


def _usage(
    provider: Provider,
    *,
    input_tokens: int | None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None,
) -> Usage:
    return Usage(
        provider=provider,
        requested_model="jev-1.13.0" if provider is Provider.TYPESAFE else "gpt-6-luna",
        model="jev-1.13.0" if provider is Provider.TYPESAFE else "gpt-6-luna",
        provider_response_id="resp-test" if provider is Provider.OPENAI else None,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        cost_nusd=None,
        pricing_version=None,
        cost_status=CostStatus.UNKNOWN,
    )


def _setup(db_path: Path) -> RequestContext:
    db.init_db(db_path)
    request_id = uuid4()
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO tasks (task_id, principal_id, agent_id, client_id, created_at) "
            "VALUES (?, ?, 'demo-agent', 'client-a', ?)",
            (str(TASK_ID), PRINCIPAL, NOW),
        )
        conn.execute(
            """INSERT INTO requests
               (request_id, principal_id, idempotency_key, request_sha256, task_id, tool,
                state, created_at)
               VALUES (?, ?, ?, ?, ?, 'documents.summarize', 'IN_PROGRESS', ?)""",
            (
                str(request_id),
                PRINCIPAL,
                str(uuid4()),
                hashlib.sha256(b"synthetic test request").hexdigest(),
                str(TASK_ID),
                NOW,
            ),
        )
    return RequestContext(
        request_id=request_id,
        task_id=TASK_ID,
        principal_id=PRINCIPAL,
        agent_id="demo-agent",
        role=Role.ANALYST,
        client_id="client-a",
        policy_version=1,
        feed_version=1,
        created_at=datetime.now(UTC),
    )


def _limits(
    *, task: int = 10_000_000, principal: int = 10_000_000, global_: int = 10_000_000
) -> BudgetLimits:
    return BudgetLimits(
        task_limit=task,
        principal_limit=principal,
        global_limit=global_,
        max_requests_per_task=20,
        max_provider_calls_per_task=40,
        max_concurrency_per_principal=2,
        max_tasks_per_principal=10,
        limit_version=1,
    )


class FakeJev:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def assess(self, state: Mapping[str, Any]):
        self.calls += 1
        if self.error:
            raise self.error
        result = SemanticResult(
            instruction_override_probability=0.1,
            data_exfiltration_probability=0.2,
            risk_score=0.2,
            category=SemanticCategory.DATA_EXFILTRATION,
        )
        return result, _usage(Provider.TYPESAFE, input_tokens=100, output_tokens=7)


class FakeLuna:
    def __init__(
        self,
        *,
        token_count: int = 85,
        count_error: Exception | None = None,
        summary_error: Exception | None = None,
    ) -> None:
        self.token_count = token_count
        self.count_error = count_error
        self.summary_error = summary_error
        self.count_calls = 0
        self.summary_calls = 0
        self.summary_max_output_tokens: int | None = None
        self.during_count: Callable[[], None] | None = None

    async def count_input_tokens(self, *, input: str) -> TokenCount:
        self.count_calls += 1
        if self.during_count is not None:
            self.during_count()
        if self.count_error:
            raise self.count_error
        return TokenCount(
            input_tokens=self.token_count,
            usage=_usage(Provider.OPENAI, input_tokens=self.token_count, output_tokens=None),
        )

    async def summarize(self, *, input: str, max_output_tokens: int | None = None) -> SummaryResult:
        self.summary_calls += 1
        self.summary_max_output_tokens = max_output_tokens
        if self.summary_error:
            raise self.summary_error
        return SummaryResult(
            text="Synthetic summary.",
            usage=_usage(
                Provider.OPENAI,
                input_tokens=self.token_count,
                cached_input_tokens=0,
                output_tokens=11,
            ),
        )


@pytest.mark.asyncio
async def test_jev_cost_is_reserved_then_settled_with_real_usage(db_path: Path) -> None:
    context = _setup(db_path)
    adapter = FakeJev()

    result, usage, reservation_id = await assess_with_budget(
        db_path=db_path,
        context=context,
        adapter=adapter,  # type: ignore[arg-type]
        state={"document": "already redacted synthetic text"},
        limits=_limits(),
        pricing=DEFAULT_PRICING,
    )

    assert adapter.calls == 1
    assert result.risk_score == 0.2
    assert usage.cost_nusd == 4_200
    assert usage.cost_status is CostStatus.CALCULATED
    assert get_reservation(db_path, reservation_id).state is ReservationState.SETTLED
    assert balances(db_path, unit=BudgetUnit.NUSD, task_id=TASK_ID, principal_id=PRINCIPAL)[
        "global"
    ] == {"spent": 4_200, "reserved": 0}


@pytest.mark.asyncio
async def test_jev_failure_keeps_conservative_reservation_unknown(db_path: Path) -> None:
    context = _setup(db_path)
    adapter = FakeJev(error=TimeoutError("no provider details should be logged"))

    with pytest.raises(TimeoutError):
        await assess_with_budget(
            db_path=db_path,
            context=context,
            adapter=adapter,  # type: ignore[arg-type]
            state={"document": "synthetic"},
            limits=_limits(),
            pricing=DEFAULT_PRICING,
        )
    assert balances(db_path, unit=BudgetUnit.NUSD, task_id=TASK_ID, principal_id=PRINCIPAL)[
        "global"
    ] == {"spent": 0, "reserved": 2_752_512}
    with closing(db.connect(db_path)) as conn:
        assert conn.execute("SELECT state FROM requests").fetchone()["state"] == "UNKNOWN"
        assert conn.execute("SELECT state FROM reservations").fetchone()["state"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_luna_counts_and_reserves_full_input_plus_output(db_path: Path) -> None:
    context = _setup(db_path)
    adapter = FakeLuna()

    (
        counted,
        summary,
        count_usage,
        summary_usage,
        count_id,
        summary_id,
    ) = await summarize_with_budget(
        db_path=db_path,
        context=context,
        adapter=adapter,  # type: ignore[arg-type]
        input="already-redacted synthetic input",
        limits=_limits(),
        pricing=DEFAULT_PRICING,
        max_input_tokens=8192,
        max_output_tokens=128,
    )

    assert adapter.count_calls == 1
    assert adapter.summary_calls == 1
    assert adapter.summary_max_output_tokens == 128
    assert counted.input_tokens == 85
    assert summary.text == "Synthetic summary."
    assert count_usage.cost_nusd == 0
    assert count_usage.cost_status is CostStatus.CALCULATED
    assert summary_usage.cost_nusd == 16_125  # 85 * 125 + 11 * 500
    assert summary_usage.cost_status is CostStatus.ESTIMATED
    assert get_reservation(db_path, count_id).state is ReservationState.SETTLED
    assert get_reservation(db_path, summary_id).state is ReservationState.SETTLED
    assert balances(db_path, unit=BudgetUnit.NUSD, task_id=TASK_ID, principal_id=PRINCIPAL)[
        "global"
    ] == {"spent": 16_125, "reserved": 0}


@pytest.mark.asyncio
async def test_luna_reserves_and_sends_same_cap_when_adapter_default_differs(
    db_path: Path,
) -> None:
    context = _setup(db_path)

    class FakeResponses:
        def __init__(self) -> None:
            self.create_args: dict[str, Any] | None = None
            self.input_tokens = SimpleNamespace(count=self.count)

        async def count(self, **kwargs: Any) -> Any:
            return SimpleNamespace(input_tokens=85)

        async def create(self, **kwargs: Any) -> Any:
            self.create_args = kwargs
            return SimpleNamespace(
                id="resp-cap-test",
                model="gpt-6-luna",
                output_text="Synthetic summary.",
                status="completed",
                output=(),
                usage=SimpleNamespace(
                    input_tokens=85,
                    output_tokens=11,
                    input_tokens_details=SimpleNamespace(cached_tokens=0),
                ),
            )

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    client = FakeClient()
    adapter = OpenAILunaAdapter(
        "test-key",
        max_output_tokens=64,
        client=client,  # type: ignore[arg-type]
    )
    cap_used_for_reservation = 2048

    *_, summary_reservation_id = await summarize_with_budget(
        db_path=db_path,
        context=context,
        adapter=adapter,
        input="already-redacted synthetic input",
        limits=_limits(),
        pricing=DEFAULT_PRICING,
        max_input_tokens=8192,
        max_output_tokens=cap_used_for_reservation,
    )

    reservation = get_reservation(db_path, summary_reservation_id)
    assert reservation.amount == reserve_openai_nusd(85, cap_used_for_reservation, DEFAULT_PRICING)
    assert client.responses.create_args is not None
    assert client.responses.create_args["max_output_tokens"] == cap_used_for_reservation
    assert client.responses.create_args["max_output_tokens"] != 64


@pytest.mark.asyncio
async def test_luna_rejects_generation_when_policy_changes_during_count(db_path: Path) -> None:
    context = _setup(db_path)
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        for version in (1, 2):
            conn.execute(
                """INSERT INTO config_versions
                   (kind, version, body, sha256, created_at, created_by)
                   VALUES ('policy', ?, '{}', ?, ?, 'test')""",
                (version, "0" * 64, NOW),
            )
        conn.execute(
            "INSERT INTO active_config (kind, version, activated_at) VALUES ('policy', 1, ?)",
            (NOW,),
        )
    adapter = FakeLuna()

    def lower_active_policy() -> None:
        with closing(db.connect(db_path)) as conn, db.transaction(conn):
            conn.execute("UPDATE active_config SET version = 2 WHERE kind = 'policy'")

    adapter.during_count = lower_active_policy
    with pytest.raises(BudgetExceeded, match="active policy changed"):
        await summarize_with_budget(
            db_path=db_path,
            context=context,
            adapter=adapter,  # type: ignore[arg-type]
            input="synthetic",
            limits=_limits(),
            pricing=DEFAULT_PRICING,
            max_input_tokens=8192,
            max_output_tokens=128,
        )

    assert adapter.count_calls == 1
    assert adapter.summary_calls == 0
    assert balances(db_path, unit=BudgetUnit.NUSD, task_id=TASK_ID, principal_id=PRINCIPAL)[
        "global"
    ] == {"spent": 0, "reserved": 0}


@pytest.mark.asyncio
async def test_luna_count_failure_blocks_summary_and_keeps_uncertainty(db_path: Path) -> None:
    context = _setup(db_path)
    adapter = FakeLuna(count_error=TimeoutError("provider timeout"))

    with pytest.raises(TimeoutError):
        await summarize_with_budget(
            db_path=db_path,
            context=context,
            adapter=adapter,  # type: ignore[arg-type]
            input="synthetic",
            limits=_limits(),
            pricing=DEFAULT_PRICING,
            max_input_tokens=8192,
            max_output_tokens=128,
        )
    assert adapter.summary_calls == 0
    assert balances(db_path, unit=BudgetUnit.NUSD, task_id=TASK_ID, principal_id=PRINCIPAL)[
        "global"
    ] == {"spent": 0, "reserved": 1}


@pytest.mark.asyncio
async def test_luna_input_token_limit_stops_before_generation(db_path: Path) -> None:
    context = _setup(db_path)
    adapter = FakeLuna(token_count=100)

    with pytest.raises(InputTokenLimitExceeded):
        await summarize_with_budget(
            db_path=db_path,
            context=context,
            adapter=adapter,  # type: ignore[arg-type]
            input="synthetic",
            limits=_limits(),
            pricing=DEFAULT_PRICING,
            max_input_tokens=99,
            max_output_tokens=128,
        )
    assert adapter.count_calls == 1
    assert adapter.summary_calls == 0
