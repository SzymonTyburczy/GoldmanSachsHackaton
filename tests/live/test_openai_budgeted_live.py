from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app import db
from app.adapters.openai_luna import OpenAILunaAdapter
from app.budget import BudgetLimits, balances
from app.contracts import BudgetUnit, RequestContext, Role
from app.pricing import DEFAULT_PRICING
from app.provider_calls import summarize_with_budget
from app.settings import Settings


@pytest.mark.live
@pytest.mark.asyncio
async def test_openai_token_count_and_summary_are_budgeted(tmp_path: Path) -> None:
    settings = Settings.from_env()
    if settings.openai_api_key is None:
        pytest.fail("OPENAI_API_KEY is required; live tests must not pass by skipping")

    db_path = tmp_path / "live-openai.sqlite3"
    db.init_db(db_path)
    task_id, request_id = uuid4(), uuid4()
    now = datetime.now(UTC).isoformat()
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        conn.execute(
            """INSERT INTO tasks (task_id, principal_id, agent_id, client_id, created_at)
               VALUES (?, 'analyst-a', 'live-test-agent', 'client-a', ?)""",
            (str(task_id), now),
        )
        conn.execute(
            """INSERT INTO requests
               (request_id, principal_id, idempotency_key, request_sha256, task_id, tool,
                state, created_at)
               VALUES (?, 'analyst-a', ?, ?, ?, 'documents.summarize', 'IN_PROGRESS', ?)""",
            (str(request_id), str(uuid4()), "a" * 64, str(task_id), now),
        )
    context = RequestContext(
        request_id=request_id,
        task_id=task_id,
        principal_id="analyst-a",
        agent_id="live-test-agent",
        role=Role.ANALYST,
        client_id="client-a",
        policy_version=1,
        feed_version=1,
        created_at=datetime.now(UTC),
    )
    limits = BudgetLimits(
        task_limit=50_000_000,
        principal_limit=200_000_000,
        global_limit=500_000_000,
        max_requests_per_task=20,
        max_provider_calls_per_task=40,
        max_concurrency_per_principal=2,
        max_tasks_per_principal=10,
        limit_version=1,
    )
    _, summary, token_usage, summary_usage, _, _ = await summarize_with_budget(
        db_path=db_path,
        context=context,
        adapter=OpenAILunaAdapter(
            settings.openai_api_key.get_secret_value(), max_output_tokens=128
        ),
        input=(
            "Summarize this fictional company in one sentence: "
            "Acme Example makes reusable notebooks."
        ),
        limits=limits,
        pricing=DEFAULT_PRICING,
        max_input_tokens=8192,
        max_output_tokens=128,
    )

    current = balances(db_path, unit=BudgetUnit.NUSD, task_id=task_id, principal_id="analyst-a")
    report_dir = Path(__file__).resolve().parents[2] / "var" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"openai-smoke-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "live",
                "provider": "openai",
                "requested_model": "gpt-6-luna",
                "reported_model": summary_usage.model,
                "recorded_at": datetime.now(UTC).isoformat(),
                "input_tokens_counted": token_usage.input_tokens,
                "input_tokens_used": summary_usage.input_tokens,
                "output_tokens": summary_usage.output_tokens,
                "estimated_cost_nusd": summary_usage.cost_nusd,
                "pricing_version": summary_usage.pricing_version,
                "summary_nonempty": bool(summary.text.strip()),
                "reserved_balance_nusd": current["global"]["reserved"],
            },
            indent=2,
        )
        + "\\n",
        encoding="utf-8",
    )
    assert token_usage.input_tokens is not None
    assert summary_usage.input_tokens == token_usage.input_tokens
    assert summary_usage.output_tokens is not None
    assert summary_usage.cost_nusd is not None
    assert summary_usage.cost_status.value == "estimated"
    assert summary.text.strip()
    assert all(scope["reserved"] == 0 for scope in current.values())
    assert all(scope["spent"] >= 0 for scope in current.values())
