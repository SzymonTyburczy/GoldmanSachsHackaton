"""Read-only admin views: /admin/metrics and /admin/test-results (plan A6)."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import reports
from app.main import create_app
from app.settings import Settings
from tests.gateway.support import StubProviders

Execute = Callable[..., httpx.Response]
NewTask = Callable[..., str]
Headers = dict[str, dict[str, str]]


def metrics(client: TestClient, headers: Headers) -> dict[str, Any]:
    response = client.get("/admin/metrics", headers=headers["admin"])
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------


def test_metrics_without_configuration_show_no_controls(
    client: TestClient, headers: Headers
) -> None:
    body = metrics(client, headers)

    assert (body["policy_version"], body["feed_version"], body["feed_rules"]) == (None, None, None)
    assert body["controls"] == []
    assert body["budget"] == []
    assert body["requests_seen"] == 0


@pytest.mark.usefixtures("active_config")
def test_metrics_count_what_the_gateway_stored(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    task = new_task("analyst-a")
    summary = execute("analyst-a", task, "documents.summarize", document_id="doc-a", prompt="Hi")
    denied = execute("analyst-a", task, "documents.read", document_id="doc-b")
    assert summary.json()["decision"] in ("ALLOW", "REDACT")
    assert denied.json()["reason_code"] == "CLIENT_FORBIDDEN"

    body = metrics(client, headers)

    assert (body["policy_version"], body["feed_version"], body["feed_rules"]) == (1, 1, 0)
    assert {c["control_id"]: c["enabled"] for c in body["controls"]} == {
        "access": True,
        "redaction": True,
        "semantic": True,
        "budget": True,
        "artifacts": True,
    }
    assert body["requests_seen"] == 2
    assert sum(body["outcomes"].values()) == 2
    assert body["outcomes"]["DENY"] == 1
    assert body["denials"] == {"CLIENT_FORBIDDEN": 1}

    cost = {row["purpose"]: row for row in body["cost"]}
    assert cost["detector"]["reservations"] == 1
    # Luna's token count and the summary each have a reservation.
    assert cost["summary"]["reservations"] == 2
    [global_scope] = [s for s in body["budget"] if s["scope"] == "global"]
    [analyst] = [s for s in body["budget"] if s["scope"] == "principal"]
    assert analyst["scope_id"] == "analyst-a"
    assert global_scope["limit_nusd"] == 500_000_000
    assert (
        global_scope["spent_nusd"]
        == cost["detector"]["settled_nusd"] + cost["summary"]["settled_nusd"]
    )
    assert global_scope["remaining_nusd"] == (
        global_scope["limit_nusd"] - global_scope["spent_nusd"] - global_scope["reserved_nusd"]
    )
    assert sum(body["reservations_by_state"].values()) == 3
    stages = {(row["control_id"], row["stage"]) for row in body["latency"]}
    assert ("semantic", "pre_detector") in stages


@pytest.mark.usefixtures("active_config")
def test_metrics_never_contain_document_values(
    client: TestClient, headers: Headers, new_task: NewTask, execute: Execute
) -> None:
    execute("reviewer-a", new_task("reviewer-a"), "documents.read", document_id="doc-a")

    text = client.get("/admin/metrics", headers=headers["admin"]).text

    assert "Fabrikam" not in text
    assert "cpdemo_" not in text


@pytest.mark.parametrize("path", ["/admin/metrics", "/admin/test-results"])
def test_admin_views_need_the_admin_role(client: TestClient, headers: Headers, path: str) -> None:
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers["analyst-a"]).status_code == 403


# --------------------------------------------------------------------------------------
# Test results
# --------------------------------------------------------------------------------------


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    path = tmp_path / "reports"
    path.mkdir()
    return path


@pytest.fixture
def reports_client(
    settings: Settings, providers: StubProviders, reports_dir: Path
) -> Iterator[TestClient]:
    custom = settings.model_copy(update={"reports_dir": reports_dir})
    with TestClient(create_app(custom, providers)) as test_client:
        yield test_client


def write(directory: Path, name: str, report: object) -> None:
    (directory / name).write_text(json.dumps(report), encoding="utf-8")


def test_no_saved_reports_is_reported_as_such(reports_client: TestClient, headers: Headers) -> None:
    body = reports_client.get("/admin/test-results", headers=headers["admin"]).json()

    assert body["reports"] == []
    assert body["unreadable_files"] == 0
    assert body["offline_suite"] == "not_recorded"


def test_newest_report_of_each_kind_with_its_commit(
    reports_client: TestClient, headers: Headers, reports_dir: Path
) -> None:
    current = reports.current_commit()
    old_commit = "0" * 40
    write(
        reports_dir,
        "jev-evaluation-20261003T100000Z.json",
        {"recorded_at": "2026-10-03T10:00:00+00:00", "git_commit": old_commit, "passed": False},
    )
    write(
        reports_dir,
        "jev-evaluation-20261003T120000Z.json",
        {
            "recorded_at": "2026-10-03T12:00:00+00:00",
            "git_commit": current,
            "sample_count": 12,
            "passed": True,
            "false_positives": 1,
            "false_negatives": 0,
            "errors": 0,
            "cases": [{"case_id": "secret-sample", "text": "SAMPLE TEXT"}],
        },
    )
    write(
        reports_dir,
        "benchmark-offline-20261003T110000Z.json",
        {
            "recorded_at": "2026-10-03T11:00:00+00:00",
            "git_commit": old_commit,
            "offline": {"iterations": 100},
            "live": None,
        },
    )
    write(reports_dir, "benchmark-live-20261003T130000Z.json", ["not", "an", "object"])
    write(reports_dir, "notes.json", {"passed": True})  # not a report name

    response = reports_client.get("/admin/test-results", headers=headers["admin"])

    body = response.json()
    assert body["current_commit"] == current
    assert body["unreadable_files"] == 1
    by_kind = {report["kind"]: report for report in body["reports"]}
    assert set(by_kind) == {"jev-evaluation", "benchmark-offline"}
    jev = by_kind["jev-evaluation"]
    assert jev["file"] == "jev-evaluation-20261003T120000Z.json"
    assert (jev["mode"], jev["sample_count"], jev["passed"]) == ("live", 12, True)
    assert (jev["false_positives"], jev["false_negatives"], jev["errors"]) == (1, 0, 0)
    assert jev["matches_current_commit"] is (current is not None)
    offline = by_kind["benchmark-offline"]
    assert (offline["mode"], offline["sample_count"], offline["passed"]) == ("offline", 100, None)
    assert offline["matches_current_commit"] is False
    # Only summary numbers leave the report.
    assert "SAMPLE TEXT" not in response.text
    assert "secret-sample" not in response.text
