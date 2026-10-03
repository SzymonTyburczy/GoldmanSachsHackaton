"""Request limits, budget, idempotency and restart (A5, sections 3, 4 and 7)."""

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app import budget, db, idempotency
from app.adapters.openai_luna import OpenAILunaError
from app.budget import balances
from app.contracts import (
    BudgetUnit,
    DocumentSummarizeRequest,
    RequestContext,
    ReservationPurpose,
    Role,
    Tool,
    utc_now,
)
from app.main import create_app
from app.settings import Settings
from tests.gateway.support import StubProviders, activate_config, break_audit, config_document
from tests.gateway.test_summary import (
    after_timeout,
    outcome,
    request_state,
    reservations,
    use_policy,
)

Execute = Callable[..., httpx.Response]
NewTask = Callable[..., str]
Headers = dict[str, dict[str, str]]

SUMMARY_COST = 180 * 42 + 120 * 125 + 40 * 500  # stub usage: Jev, count (free), Luna


def body_for(task_id: str, prompt: str = "Summarize this company.") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_id": task_id,
        "tool": "documents.summarize",
        "arguments": {"document_id": "doc-a", "prompt": prompt},
    }


def post(
    client: TestClient, headers: Headers, identity: str, body: dict[str, Any], key: UUID
) -> httpx.Response:
    return client.post(
        "/v1/execute", json=body, headers=headers[identity] | {"Idempotency-Key": str(key)}
    )


def event_count(client: TestClient, headers: Headers) -> int:
    return len(
        client.get("/admin/events", params={"limit": 200}, headers=headers["admin"]).json()[
            "events"
        ]
    )


# --------------------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------------------


@pytest.mark.usefixtures("active_config")
def test_exhausted_task_budget_stops_the_next_request_before_the_detector(
    db_path: Path, providers: StubProviders, new_task: NewTask, execute: Execute
) -> None:
    # Jev reserves 65536 x 42 nUSD up front, so a task with 0.003 USD fits six summaries.
    use_policy(db_path, budget={"task_limit_nusd": 3_000_000})
    task_id = new_task("analyst-a")

    results = []
    for _ in range(7):
        response = execute(
            "analyst-a", task_id, "documents.summarize", document_id="doc-a", prompt="Summarize."
        )
        results.append(response.json())

    assert [body["decision"] for body in results] == ["REDACT"] * 6 + ["DENY"]
    refused = results[-1]
    assert outcome(refused) == ("DENY", "BUDGET_EXCEEDED", "NOT_CALLED")
    assert refused["adapter_calls"]["detector"] == "NOT_CALLED"
    assert len(providers.jev.states) == len(providers.luna.summarized) == 6
    spent = balances(db_path, unit=BudgetUnit.NUSD, task_id=UUID(task_id), principal_id="analyst-a")
    assert spent["task"] == {"spent": 6 * SUMMARY_COST, "reserved": 0}


@pytest.mark.usefixtures("active_config")
def test_summary_reservation_over_the_limit_keeps_the_detector_cost(
    db_path: Path, providers: StubProviders, new_task: NewTask, execute: Execute
) -> None:
    # Enough for Jev's reservation, not for 16384 output tokens at 500 nUSD each.
    use_policy(
        db_path,
        budget={"task_limit_nusd": 5_000_000},
        models={"summary_max_output_tokens": 16384},
    )

    response = execute(
        "analyst-a", new_task("analyst-a"), "documents.summarize", document_id="doc-a", prompt="S."
    )

    body = response.json()
    assert outcome(body) == ("DENY", "BUDGET_EXCEEDED", "NOT_CALLED")
    assert body["adapter_calls"]["token_count"] == "SUCCEEDED"
    assert providers.luna.summarized == []
    assert [row[:2] for row in reservations(db_path)] == [
        ("detector", "SETTLED"),
        ("summary", "SETTLED"),  # the count marker, settled at zero
    ]
    assert [usage["provider"] for usage in body["usage"]] == ["typesafe", "openai"]


@pytest.mark.usefixtures("active_config")
def test_lower_limit_activated_mid_request_applies_to_the_next_reservation(
    db_path: Path, providers: StubProviders, new_task: NewTask, execute: Execute
) -> None:
    versions: list[int] = []

    async def admin_lowers_the_budget() -> None:
        versions.append(use_policy(db_path, budget={"task_limit_nusd": 1_000_000}))

    providers.jev.during = admin_lowers_the_budget

    response = execute(
        "analyst-a", new_task("analyst-a"), "documents.summarize", document_id="doc-a", prompt="S."
    )

    body = response.json()
    assert outcome(body) == ("DENY", "BUDGET_EXCEEDED", "NOT_CALLED")
    assert body["policy_version"] == 1  # decisions keep the pinned policy ...
    # ... while each reservation also respects the limits active when it is made.
    assert reservations(db_path) == [
        ("detector", "SETTLED", 180 * 42, 1),
        ("summary", "SETTLED", 0, versions[0]),
    ]


@pytest.mark.usefixtures("active_config")
def test_unreadable_active_policy_mid_request_stops_the_next_reservation(
    db_path: Path, providers: StubProviders, new_task: NewTask, execute: Execute
) -> None:
    async def policy_is_tampered_with() -> None:
        version = use_policy(db_path, semantic={"block_threshold": 0.9})
        with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
            conn.execute(
                "UPDATE config_versions SET body = '{}' WHERE kind = 'policy' AND version = ?",
                (version,),
            )

    providers.jev.during = policy_is_tampered_with

    response = execute(
        "analyst-a", new_task("analyst-a"), "documents.summarize", document_id="doc-a", prompt="S."
    )

    assert outcome(response.json()) == ("DENY", "INVALID_CONFIG", "NOT_CALLED")
    assert providers.luna.counted == []


# --------------------------------------------------------------------------------------
# Request limits at admission
# --------------------------------------------------------------------------------------


@pytest.mark.usefixtures("active_config")
def test_requests_per_task_limit_refuses_at_admission(
    client: TestClient, db_path: Path, new_task: NewTask, execute: Execute
) -> None:
    use_policy(db_path, resources={"max_requests_per_task": 2})
    task_id = new_task("analyst-a")
    for _ in range(2):
        execute("analyst-a", task_id, "documents.read", document_id="doc-a")

    refused = execute("analyst-a", task_id, "documents.read", document_id="doc-a").json()
    fresh = execute("analyst-a", new_task("analyst-a"), "documents.read", document_id="doc-a")

    assert outcome(refused) == ("DENY", "BUDGET_EXCEEDED", "NOT_CALLED")
    assert client.app.state.documents.read_count == 3
    assert fresh.json()["decision"] == "REDACT"


@pytest.mark.usefixtures("active_config")
def test_rate_limit_answers_429_with_retry_after(
    client: TestClient, headers: Headers, db_path: Path, new_task: NewTask, execute: Execute
) -> None:
    use_policy(db_path, resources={"max_requests_per_minute_per_principal": 2})
    task_id = new_task("analyst-a")
    for _ in range(2):
        execute("analyst-a", task_id, "documents.read", document_id="doc-a")

    limited = execute("analyst-a", task_id, "documents.read", document_id="doc-a")
    other = execute("reviewer-a", new_task("reviewer-a"), "documents.read", document_id="doc-a")

    assert limited.status_code == 429
    assert limited.json()["reason_code"] == "RATE_LIMITED"
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    assert client.app.state.documents.read_count == 3  # two reads + the reviewer
    assert other.json()["decision"] == "REDACT"
    events = client.get(
        "/admin/events",
        params={"request_id": limited.json()["request_id"]},
        headers=headers["admin"],
    ).json()["events"]
    assert [(e["control_id"], e["decision"], e["reason_code"]) for e in events] == [
        ("gateway", "DENY", "RATE_LIMITED")
    ]


@pytest.fixture
async def app_client(
    settings: Settings, providers: StubProviders, db_path: Path, headers: Headers
) -> AsyncIterator[httpx.AsyncClient]:
    """An in-process client on the test's event loop, so requests can overlap."""
    db.init_db(db_path)
    activate_config(db_path, "policy")
    activate_config(db_path, "feed")
    app = create_app(settings, providers)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway.test") as client:
        yield client


async def new_task_async(client: httpx.AsyncClient, headers: Headers, identity: str) -> str:
    response = await client.post(
        "/v1/tasks", json={"schema_version": 1, "client_id": "client-a"}, headers=headers[identity]
    )
    return response.json()["task_id"]


async def wait_for(condition: Callable[[], bool]) -> None:
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


async def test_parallel_requests_beyond_the_principal_limit_are_refused(
    app_client: httpx.AsyncClient, headers: Headers, providers: StubProviders
) -> None:
    release = asyncio.Event()

    async def hold() -> None:
        await release.wait()

    providers.jev.during = hold
    task_id = await new_task_async(app_client, headers, "analyst-a")

    async def send(key: UUID) -> httpx.Response:
        return await app_client.post(
            "/v1/execute",
            json=body_for(task_id),
            headers=headers["analyst-a"] | {"Idempotency-Key": str(key)},
        )

    running = [asyncio.create_task(send(uuid4())) for _ in range(2)]
    await wait_for(lambda: len(providers.jev.states) == 2)
    third = await send(uuid4())  # policy: max_concurrency_per_principal = 2
    release.set()
    first, second = await asyncio.gather(*running)

    assert outcome(third.json()) == ("DENY", "CONCURRENCY_EXCEEDED", "NOT_CALLED")
    assert third.json()["adapter_calls"]["document_read"] == "NOT_CALLED"
    assert [first.json()["decision"], second.json()["decision"]] == ["REDACT", "REDACT"]
    assert len(providers.jev.states) == 2
    assert (await send(uuid4())).json()["decision"] == "REDACT"  # the slots are free again


async def test_same_key_while_running_is_pending_then_replayed(
    app_client: httpx.AsyncClient, headers: Headers, providers: StubProviders
) -> None:
    release = asyncio.Event()

    async def hold() -> None:
        await release.wait()

    providers.jev.during = hold
    task_id = await new_task_async(app_client, headers, "analyst-a")
    key = str(uuid4())

    async def send() -> httpx.Response:
        return await app_client.post(
            "/v1/execute",
            json=body_for(task_id),
            headers=headers["analyst-a"] | {"Idempotency-Key": key},
        )

    first = asyncio.create_task(send())
    await wait_for(lambda: len(providers.jev.states) == 1)
    pending = await send()
    release.set()
    completed = await first
    replayed = await send()

    assert pending.status_code == 409
    assert pending.json()["reason_code"] == "REQUEST_PENDING"
    assert replayed.json() == completed.json()
    assert len(providers.jev.states) == len(providers.luna.summarized) == 1


# --------------------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------------------


@pytest.mark.usefixtures("active_config")
def test_same_key_and_body_returns_the_stored_response_without_running_again(
    client: TestClient, headers: Headers, providers: StubProviders, new_task: NewTask
) -> None:
    task_id, key = new_task("analyst-a"), uuid4()

    first = post(client, headers, "analyst-a", body_for(task_id), key)
    events = event_count(client, headers)
    again = post(client, headers, "analyst-a", body_for(task_id), key)

    assert again.status_code == 200
    assert again.json() == first.json()
    assert again.headers["X-Request-ID"] != first.json()["request_id"]
    assert client.app.state.documents.read_count == 1
    assert len(providers.jev.states) == len(providers.luna.summarized) == 1
    assert event_count(client, headers) == events


@pytest.mark.usefixtures("active_config")
def test_key_reused_for_another_request_is_a_conflict(
    client: TestClient, headers: Headers, providers: StubProviders, new_task: NewTask
) -> None:
    task_id, key = new_task("analyst-a"), uuid4()
    post(client, headers, "analyst-a", body_for(task_id), key)

    changed = post(client, headers, "analyst-a", body_for(task_id, "Another prompt."), key)

    assert changed.status_code == 409
    assert changed.json()["reason_code"] == "IDEMPOTENCY_CONFLICT"
    assert len(providers.jev.states) == 1


@pytest.mark.usefixtures("active_config")
def test_keys_belong_to_one_principal(
    client: TestClient, headers: Headers, providers: StubProviders, new_task: NewTask
) -> None:
    key = uuid4()
    post(client, headers, "analyst-a", body_for(new_task("analyst-a")), key)

    reviewer = post(client, headers, "reviewer-a", body_for(new_task("reviewer-a")), key)

    assert reviewer.json()["decision"] == "REDACT"
    assert len(providers.jev.states) == 2


@pytest.mark.usefixtures("active_config")
def test_uncertain_summary_is_replayed_not_sent_again(
    client: TestClient, headers: Headers, db_path: Path, providers: StubProviders, new_task: NewTask
) -> None:
    providers.luna.summary_error = after_timeout(OpenAILunaError, "APITimeoutError")
    task_id, key = new_task("analyst-a"), uuid4()

    first = post(client, headers, "analyst-a", body_for(task_id), key)
    providers.luna.summary_error = None
    again = post(client, headers, "analyst-a", body_for(task_id), key)

    assert outcome(first.json()) == ("DENY", "UPSTREAM_TIMEOUT", "UNKNOWN")
    assert again.json() == first.json()
    assert len(providers.luna.summarized) == 1
    assert request_state(db_path, first.json()["request_id"]) == "UNKNOWN"


@pytest.mark.usefixtures("active_config")
def test_key_can_be_retried_when_nothing_ran(
    client: TestClient, headers: Headers, db_path: Path, new_task: NewTask
) -> None:
    task_id, key = new_task("analyst-a"), uuid4()
    break_audit(db_path, "admission")

    failed = post(client, headers, "analyst-a", body_for(task_id), key)
    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute("DROP TRIGGER audit_outage_admission")
    retried = post(client, headers, "analyst-a", body_for(task_id), key)

    assert failed.status_code == 503
    assert retried.json()["decision"] == "REDACT"


def test_restart_marks_open_work_unknown_and_keeps_the_key_pending(
    settings: Settings, providers: StubProviders, db_path: Path, headers: Headers
) -> None:
    key = uuid4()
    with TestClient(create_app(settings, providers)) as client:
        activate_config(db_path, "policy")
        activate_config(db_path, "feed")
        task_id = client.post(
            "/v1/tasks",
            json={"schema_version": 1, "client_id": "client-a"},
            headers=headers["analyst-a"],
        ).json()["task_id"]
    # A process stopped during the detector call: the request is stored and the
    # reservation started, nothing was settled.
    context = RequestContext(
        request_id=uuid4(),
        task_id=UUID(task_id),
        principal_id="analyst-a",
        agent_id="demo-agent",
        role=Role.ANALYST,
        client_id="client-a",
        policy_version=1,
        feed_version=1,
        created_at=utc_now(),
    )
    request = DocumentSummarizeRequest.model_validate(body_for(task_id))
    policy = config_document("policy")
    idempotency.claim(
        db_path,
        context,
        tool=Tool(request.tool),
        key=key,
        digest=idempotency.request_digest(request),
        resources=policy.resources,
        now=context.created_at,
    )
    reservation = budget.reserve(
        db_path,
        context,
        ReservationPurpose.DETECTOR,
        BudgetUnit.NUSD,
        1000,
        policy.budget_limits(1),
        pricing_version=policy.pricing.version,
    )
    budget.mark_started(db_path, reservation.reservation_id)

    with TestClient(create_app(settings, providers)) as client:
        again = post(client, headers, "analyst-a", body_for(task_id), key)

    assert again.status_code == 409
    assert again.json()["reason_code"] == "REQUEST_PENDING"
    assert reservations(db_path) == [("detector", "UNKNOWN", None, 1)]
    assert request_state(db_path, str(context.request_id)) == "UNKNOWN"
    held = balances(db_path, unit=BudgetUnit.NUSD, task_id=UUID(task_id), principal_id="analyst-a")
    assert held["task"] == {"spent": 0, "reserved": 1000}  # not released by the restart
    assert providers.jev.states == []
