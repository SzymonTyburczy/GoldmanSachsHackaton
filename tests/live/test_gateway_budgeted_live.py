from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import db
from app.budget import balances
from app.contracts import BudgetUnit
from app.main import create_app
from app.policy import CONFIG_FILES, DEFAULT_CONFIG_DIR, activate, read_config_file
from app.settings import Settings
from scripts.reporting import write_json_report


@pytest.mark.live
def test_real_gateway_summary_uses_redaction_budget_and_audit(tmp_path: Path) -> None:
    """Exercise the complete synthetic summary path with real Jev and Luna providers."""
    base = Settings.from_env()
    if base.openai_api_key is None or base.typesafe_api_key is None:
        pytest.fail("OPENAI_API_KEY and TYPESAFE_API_KEY are required for live tests")
    analyst_token = SecretStr(
        base.token_analyst_a.get_secret_value()
        if base.token_analyst_a is not None
        else "gateway-live-analyst-token-0123456789abcdef"
    )

    settings = Settings(
        db_path=tmp_path / "gateway-live.sqlite3",
        documents_dir=base.documents_dir,
        token_analyst_a=analyst_token,
        openai_api_key=base.openai_api_key,
        typesafe_api_key=base.typesafe_api_key,
    )
    db.init_db(settings.db_path)
    with db.connect(settings.db_path) as conn:
        activate(
            conn,
            "policy",
            read_config_file("policy", DEFAULT_CONFIG_DIR / CONFIG_FILES["policy"]),
            expected_version=None,
            created_by="live",
        )
        activate(
            conn,
            "feed",
            read_config_file("feed", DEFAULT_CONFIG_DIR / CONFIG_FILES["feed"]),
            expected_version=None,
            created_by="live",
        )

    headers = {
        "Authorization": f"Bearer {analyst_token.get_secret_value()}",
    }
    with TestClient(create_app(settings)) as client:
        task_response = client.post(
            "/v1/tasks",
            json={"schema_version": 1, "client_id": "client-a"},
            headers=headers,
        )
        assert task_response.status_code == 201, task_response.text
        task_id = task_response.json()["task_id"]

        started = time.perf_counter()
        response = client.post(
            "/v1/execute",
            json={
                "schema_version": 1,
                "task_id": task_id,
                "tool": "documents.summarize",
                "arguments": {
                    "document_id": "doc-a",
                    "prompt": "Summarize the synthetic company record in two short sentences.",
                },
            },
            headers=headers | {"Idempotency-Key": str(uuid4())},
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["decision"] in {"ALLOW", "REDACT"}
        assert body["execution_status"] == "SUCCEEDED"
        assert body["output"]["kind"] == "summary"
        assert body["output"]["text"].strip()
        assert body["adapter_calls"] == {
            "document_read": "SUCCEEDED",
            "token_count": "SUCCEEDED",
            "detector": "SUCCEEDED",
            "summary": "SUCCEEDED",
            "artifact_admit": "NOT_CALLED",
        }
        assert len(body["usage"]) == 3
        assert {usage["provider"] for usage in body["usage"]} == {"typesafe", "openai"}
        remaining = balances(
            settings.db_path,
            unit=BudgetUnit.NUSD,
            task_id=UUID(task_id),
            principal_id="analyst-a",
        )
        assert remaining["global"]["reserved"] == 0

        events = client.get(
            f"/v1/tasks/{task_id}/events",
            headers=headers,
        )
        assert events.status_code == 200, events.text
        event_body = events.json()
        assert any(event["execution_status"] == "SUCCEEDED" for event in event_body["events"])

    report_path = Path(__file__).resolve().parents[2] / "var" / "reports"
    report_path.mkdir(parents=True, exist_ok=True)
    write_json_report(
        report_path / f"gateway-live-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json",
        {
            "schema_version": 1,
            "mode": "live",
            "provider": "gateway",
            "recorded_at": datetime.now(UTC).isoformat(),
            "latency_ms": latency_ms,
            "latency_scope": "HTTP test client plus gateway, Presidio, Jev, Luna, budget and audit",
            "decision": body["decision"],
            "execution_status": body["execution_status"],
            "provider_call_count": len(body["usage"]),
            "estimated_cost_nusd": sum(usage["cost_nusd"] or 0 for usage in body["usage"]),
            "reserved_balance_nusd": remaining["global"]["reserved"],
        },
    )
