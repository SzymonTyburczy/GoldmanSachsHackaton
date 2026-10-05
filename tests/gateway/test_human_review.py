"""Human approval must control real adapter calls, not just the panel's buttons."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app import db, policy, reviews
from app.auth import Principal
from app.contracts import Role, utc_now
from app.main import create_app
from tests.gateway.support import activate_config, break_audit

pytestmark = pytest.mark.usefixtures("active_config")


def pause(execute, new_task, providers, identity="analyst-a", tool="documents.summarize"):
    providers.jev.override = 0.65
    arguments = {"document_id": "doc-a"}
    if tool == "documents.summarize":
        arguments["prompt"] = (
            "Summarize. Contact jan.kowalski@example.test, key cpdemo_7Hq2Lm9Xa4Rt8Vw3Nb6Kp1Zc."
        )
    response = execute(identity, new_task(identity), tool, **arguments)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "REQUIRE_APPROVAL"
    assert body["output"] is None
    assert providers.luna.counted == providers.luna.summarized == []
    return body


def decide(client, headers, body, decision="approve", identity="reviewer-a"):
    return client.post(
        f"/v1/reviews/{body['review_id']}/decision",
        json={"schema_version": 1, "decision": decision},
        headers=headers[identity],
    )


def result(client, headers, body):
    response = client.get(f"/v1/requests/{body['request_id']}", headers=headers["analyst-a"])
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        (0.499, "REDACT"),
        (0.5, "REQUIRE_APPROVAL"),
        (0.65, "REQUIRE_APPROVAL"),
        (0.799, "REQUIRE_APPROVAL"),
        (0.8, "DENY"),
        (1, "DENY"),
    ],
)
def test_risk_bands(execute, new_task, providers, risk, expected):
    providers.jev.override = risk
    body = execute(
        "analyst-a",
        new_task("analyst-a"),
        "documents.summarize",
        document_id="doc-a",
        prompt="Summarize.",
    ).json()
    assert body["decision"] == expected
    assert bool(providers.luna.summarized) == (expected == "REDACT")
    assert bool(body["review_id"]) == (expected == "REQUIRE_APPROVAL")


def test_approve_resumes_exact_masked_input_once(
    client, headers, execute, new_task, providers, db_path
):
    body = pause(execute, new_task, providers)
    inbox = client.get("/v1/reviews", headers=headers["reviewer-a"]).json()["reviews"]
    assert len(inbox) == 1
    assert inbox[0]["risk_score"] == 0.65
    assert "<EMAIL_ADDRESS>" in inbox[0]["masked_prompt"]
    assert "<SECRET>" in inbox[0]["masked_prompt"]
    response = decide(client, headers, body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APPROVED"
    final = result(client, headers, body)
    assert final["decision"] == "REDACT"
    assert final["output"]["kind"] == "summary"
    assert len(providers.jev.states) == 1
    assert len(providers.luna.summarized) == 1
    assert providers.luna.counted == providers.luna.summarized
    assert providers.jev.states[0]["untrusted_prompt"] in providers.luna.summarized[0]
    events = client.get(f"/v1/tasks/{body['task_id']}/events", headers=headers["analyst-a"]).json()[
        "events"
    ]
    human = [e for e in events if e["control_id"] == "human_review"]
    assert len(human) == 1
    assert human[0]["reason_code"] == "HUMAN_APPROVED"
    assert human[0]["reviewer_id"] == "reviewer-a"
    assert human[0]["adapter_calls"]["summary"] == "NOT_CALLED"
    assert decide(client, headers, body).status_code == 409
    assert len(providers.luna.summarized) == 1
    with closing(db.connect(db_path)) as conn:
        persisted = " ".join(
            row[0] for row in conn.execute("SELECT safe_request_json FROM human_reviews")
        )
        persisted += " ".join(
            row[0] for row in conn.execute("SELECT review_json FROM human_reviews")
        )
    assert "jan.kowalski" not in persisted
    assert "cpdemo_7Hq2" not in persisted


def test_block_never_calls_summary_or_reads_again(client, headers, execute, new_task, providers):
    body = pause(execute, new_task, providers)
    assert decide(client, headers, body, "block").json()["status"] == "BLOCKED"
    final = result(client, headers, body)
    assert (final["decision"], final["reason_code"]) == ("DENY", "HUMAN_BLOCKED")
    assert final["output"] is None
    assert client.app.state.documents.read_count == 1
    assert providers.luna.counted == providers.luna.summarized == []
    assert decide(client, headers, body).status_code == 409


def test_authorization_and_scope(client, headers, execute, new_task, providers, db_path):
    body = pause(execute, new_task, providers)
    assert client.get("/v1/reviews").status_code == 401
    assert client.get("/v1/reviews", headers=headers["analyst-a"]).status_code == 403
    assert decide(client, headers, body, identity="analyst-a").status_code == 403
    assert (
        client.get(f"/v1/requests/{body['request_id']}", headers=headers["reviewer-a"]).status_code
        == 403
    )
    stranger = Principal("reviewer-b", Role.REVIEWER, "demo-agent", frozenset({"client-b"}))
    assert reviews.list_reviews(db_path, stranger).reviews == ()
    with pytest.raises(Exception) as err:
        reviews.get_review(db_path, stranger, UUID(body["review_id"]))
    assert err.value.status_code == 403
    # A reviewer cannot approve their own operation, even though they have review rights.
    own = pause(execute, new_task, providers, identity="reviewer-a")
    assert decide(client, headers, own).status_code == 403
    assert decide(client, headers, own, identity="admin").status_code == 200


@pytest.mark.parametrize("kind", ["policy", "feed"])
def test_new_configuration_invalidates_approval(
    client, headers, execute, new_task, providers, db_path, kind
):
    body = pause(execute, new_task, providers)
    activate_config(db_path, kind)
    response = decide(client, headers, body)
    assert response.status_code == 200
    assert response.json()["status"] == "STALE"
    assert result(client, headers, body)["reason_code"] == "REVIEW_STALE"
    assert providers.luna.counted == providers.luna.summarized == []


def test_changed_document_requires_new_assessment(
    client, headers, execute, new_task, providers, monkeypatch
):
    body = pause(execute, new_task, providers)
    adapter = client.app.state.documents
    original_read = adapter.read

    def changed(entry):
        return original_read(entry) | {"notes": "Changed after assessment"}

    monkeypatch.setattr(adapter, "read", changed)
    assert decide(client, headers, body).json()["status"] == "STALE"
    assert result(client, headers, body)["reason_code"] == "REVIEW_STALE"
    assert providers.luna.counted == providers.luna.summarized == []


def test_expiry_is_audited_without_a_reviewer_click(
    client, headers, execute, new_task, providers, monkeypatch
):
    body = pause(execute, new_task, providers)
    monkeypatch.setattr(reviews, "utc_now", lambda: utc_now() + timedelta(hours=1))
    assert result(client, headers, body)["reason_code"] == "REVIEW_EXPIRED"
    inbox = client.get("/v1/reviews", headers=headers["reviewer-a"]).json()["reviews"]
    assert inbox[0]["status"] == "EXPIRED"
    assert decide(client, headers, body).status_code == 409
    assert providers.luna.summarized == []


def test_pending_survives_restart(client, settings, headers, execute, new_task, providers):
    body = pause(execute, new_task, providers)
    with TestClient(create_app(settings, providers)) as restarted:
        assert result(restarted, headers, body)["decision"] == "REQUIRE_APPROVAL"
        assert decide(restarted, headers, body).status_code == 200
        assert result(restarted, headers, body)["output"] is not None
    assert len(providers.jev.states) == len(providers.luna.summarized) == 1


def test_interrupted_approval_never_replays(
    client, settings, headers, execute, new_task, providers, db_path
):
    body = pause(execute, new_task, providers)
    with closing(db.connect(db_path)) as conn:
        pinned = policy.load_active(conn, "policy").document
    from app.auth import REVIEWER_A

    reviews.claim(db_path, REVIEWER_A, UUID(body["review_id"]), pinned)
    with TestClient(create_app(settings, providers)) as restarted:
        final = result(restarted, headers, body)
        assert (final["decision"], final["reason_code"]) == ("DENY", "REQUEST_PENDING")
        assert decide(restarted, headers, body).status_code == 409
    assert providers.luna.summarized == []


def test_two_reviewers_only_one_execution(client, headers, execute, new_task, providers):
    body = pause(execute, new_task, providers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(decide, client, headers, body, "approve", identity)
            for identity in ("reviewer-a", "admin")
        ]
        responses = [future.result() for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(providers.luna.summarized) == 1


def test_audit_failure_prevents_approval_execution(
    client, headers, execute, new_task, providers, db_path
):
    body = pause(execute, new_task, providers)
    break_audit(db_path, "pre_summary")
    assert decide(client, headers, body).status_code == 503
    assert providers.luna.counted == providers.luna.summarized == []
    assert decide(client, headers, body).status_code == 409


def test_detector_error_and_hard_denial_never_create_reviews(
    client, headers, execute, new_task, providers
):
    providers.jev.override = 0.65
    assert (
        execute(
            "analyst-a",
            new_task("analyst-a"),
            "documents.summarize",
            document_id="doc-b",
            prompt="Summarize.",
        ).json()["reason_code"]
        == "CLIENT_FORBIDDEN"
    )
    from app.adapters.jev import JevAdapterError

    providers.jev.error = JevAdapterError("unavailable")
    assert (
        execute(
            "analyst-a",
            new_task("analyst-a"),
            "documents.summarize",
            document_id="doc-a",
            prompt="Summarize.",
        ).json()["reason_code"]
        == "DETECTOR_UNAVAILABLE"
    )
    assert client.get("/v1/reviews", headers=headers["reviewer-a"]).json()["reviews"] == []


def test_request_replay_returns_current_result(client, headers, new_task, providers):
    providers.jev.override = 0.65
    task = new_task("analyst-a")
    body = {
        "schema_version": 1,
        "task_id": task,
        "tool": "documents.summarize",
        "arguments": {"document_id": "doc-a", "prompt": "Summarize."},
    }
    request_headers = headers["analyst-a"] | {"Idempotency-Key": str(uuid4())}
    pending = client.post("/v1/execute", json=body, headers=request_headers).json()
    assert client.post("/v1/execute", json=body, headers=request_headers).json() == pending
    altered = json.loads(json.dumps(body))
    altered["arguments"]["prompt"] = "Changed"
    assert client.post("/v1/execute", json=altered, headers=request_headers).status_code == 409
    assert decide(client, headers, pending).status_code == 200
    final = client.post("/v1/execute", json=body, headers=request_headers).json()
    assert final["output"] is not None
    assert len(providers.jev.states) == len(providers.luna.summarized) == 1


def test_read_review_releases_only_checked_role_fields(
    client, headers, execute, new_task, providers
):
    body = pause(execute, new_task, providers, tool="documents.read")
    assert body["execution_status"] == "SUCCEEDED"  # document was read, not released
    assert decide(client, headers, body).status_code == 200
    assert set(result(client, headers, body)["output"]["fields"]) == {
        "company_name",
        "status",
        "notes",
    }
    assert len(providers.jev.states) == 1
    assert providers.luna.counted == providers.luna.summarized == []


def test_approved_result_cannot_bypass_new_acl(
    client, headers, execute, new_task, providers, db_path
):
    body = pause(execute, new_task, providers)
    assert decide(client, headers, body).status_code == 200
    with closing(db.connect(db_path)) as conn:
        active = policy.load_active(conn, "policy")
    document = active.document.model_dump(mode="json")
    document["acl"]["analyst"]["tools"] = []
    document["acl"]["reviewer"]["fields"] = []
    activate_config(db_path, "policy", policy.Policy.model_validate(document))
    final = result(client, headers, body)
    assert (final["decision"], final["reason_code"]) == ("DENY", "TOOL_FORBIDDEN")
    assert final["output"] is None
    preview = client.get(f"/v1/reviews/{body['review_id']}", headers=headers["reviewer-a"]).json()
    assert "Fabrikam" not in preview["masked_document"]
    assert preview["masked_prompt"] is None


def test_approval_provider_failure_preserves_cost_and_denial(
    client, headers, execute, new_task, providers, db_path
):
    from app.adapters.openai_luna import OpenAILunaError

    body = pause(execute, new_task, providers)
    providers.luna.summary_error = OpenAILunaError("provider failed")
    decided = decide(client, headers, body).json()
    assert decided["status"] == "APPROVED"  # human decision does not imply successful generation
    assert decided["result_reason_code"] == "UPSTREAM_FAILED"
    assert result(client, headers, body)["output"] is None
    assert len(providers.luna.summarized) == 1
    with closing(db.connect(db_path)) as conn:
        assert (
            conn.execute(
                "SELECT state FROM reservations WHERE purpose='summary'"
                " ORDER BY created_at DESC LIMIT 1"
            ).fetchone()[0]
            == "UNKNOWN"
        )
    assert decide(client, headers, body).status_code == 409
