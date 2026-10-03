"""artifacts.admit and the threat feed (docs/WSPOLNE_USTALENIA.md, section 6; plan A6).

The artifacts are synthetic: inert JSON documents and one non-JSON file with a
pickle-like header that is never deserialized. The class of threat is CWE-502; these
tests show that a listed or altered artifact is refused before it is used, not a full
supply-chain attack.
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.artifacts import MAX_ARTIFACT_BYTES, ArtifactStore, ManifestEntry
from app.controls.artifacts import check_bytes
from app.main import create_app
from app.policy import Feed, FeedRule, Policy
from app.settings import DEFAULT_ARTIFACTS_DIR, Settings
from tests.gateway.support import StubProviders, activate_config, config_document

Execute = Callable[..., httpx.Response]
NewTask = Callable[..., str]
Headers = dict[str, dict[str, str]]

CONTENT = DEFAULT_ARTIFACTS_DIR / "content"


def digest_of(artifact_id: str) -> str:
    return hashlib.sha256((CONTENT / f"{artifact_id}.artifact").read_bytes()).hexdigest()


def rule(value: str, rule_id: str = "blk-template") -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "kind": "sha256",
        "value": value,
        "source": "Security team",
        "reason": "Known unsafe artifact",
        "is_test_fixture": True,
    }


def put_feed(
    client: TestClient, headers: Headers, rules: list[dict[str, Any]], expected: int | None
) -> httpx.Response:
    body = {
        "schema_version": 1,
        "expected_version": expected,
        "feed": {"schema_version": 1, "rules": rules},
    }
    return client.put("/admin/feed", json=body, headers=headers["admin"])


def events_of(client: TestClient, headers: Headers, request_id: str) -> list[dict[str, Any]]:
    response = client.get(
        "/admin/events", params={"request_id": request_id}, headers=headers["admin"]
    )
    return response.json()["events"]


def store(client: TestClient) -> ArtifactStore:
    return client.app.state.artifacts


@pytest.fixture
def admit(new_task: NewTask, execute: Execute) -> Callable[..., httpx.Response]:
    def call(artifact_id: str, identity: str = "admin") -> httpx.Response:
        return execute(identity, new_task(identity), "artifacts.admit", artifact_id=artifact_id)

    return call


# --------------------------------------------------------------------------------------
# Admission
# --------------------------------------------------------------------------------------


@pytest.mark.usefixtures("active_config")
def test_clean_artifact_is_admitted_with_its_digest(
    client: TestClient, headers: Headers, providers: StubProviders, admit: Callable
) -> None:
    response = admit("art-summary-template")

    assert response.status_code == 200
    body = response.json()
    assert (body["decision"], body["reason_code"]) == ("ALLOW", "OK")
    assert body["execution_status"] == "SUCCEEDED"
    assert body["output"] == {
        "kind": "artifact",
        "artifact_id": "art-summary-template",
        "sha256": digest_of("art-summary-template"),
    }
    assert body["adapter_calls"]["artifact_admit"] == "SUCCEEDED"
    assert body["usage"] == []
    # No model takes part in artifact admission.
    assert providers.jev.states == []
    assert providers.luna.counted == []
    steps = [
        (e["control_id"], e["stage"], e["decision"], e["execution_status"])
        for e in events_of(client, headers, body["request_id"])
    ]
    assert steps == [
        ("gateway", "admission", "ALLOW", "NOT_CALLED"),
        ("artifacts", "artifact", "ALLOW", "STARTED"),
        ("artifacts", "artifact", "ALLOW", "SUCCEEDED"),
    ]


@pytest.mark.usefixtures("active_config")
def test_adding_the_hash_to_the_feed_blocks_a_previously_admitted_artifact(
    client: TestClient, headers: Headers, admit: Callable
) -> None:
    before = admit("art-summary-template").json()
    assert before["decision"] == "ALLOW"

    update = put_feed(client, headers, [rule(digest_of("art-summary-template"))], expected=1)
    assert update.status_code == 200, update.text
    assert update.json()["feed_version"] == 2

    after = admit("art-summary-template").json()
    assert (after["decision"], after["reason_code"]) == ("DENY", "ARTIFACT_BLOCKED")
    assert after["output"] is None
    # The bytes were read and hashed before the feed refused them.
    assert after["adapter_calls"]["artifact_admit"] == "SUCCEEDED"
    final = events_of(client, headers, after["request_id"])[-1]
    assert (final["control_id"], final["reason_code"], final["feed_version"]) == (
        "artifacts",
        "ARTIFACT_BLOCKED",
        2,
    )
    # Another artifact is unaffected by the rule.
    assert admit("art-model-card").json()["decision"] == "ALLOW"


@pytest.mark.usefixtures("active_config")
def test_removing_the_rule_admits_the_artifact_again(
    client: TestClient, headers: Headers, admit: Callable
) -> None:
    put_feed(client, headers, [rule(digest_of("art-model-card"))], expected=1)
    assert admit("art-model-card").json()["decision"] == "DENY"

    put_feed(client, headers, [], expected=2)

    assert admit("art-model-card").json()["decision"] == "ALLOW"


@pytest.mark.parametrize(
    "artifact_id",
    [
        "art-tampered",  # valid JSON, but not the bytes the manifest declares
        "art-pickle",  # declared bytes, but not the accepted JSON format
    ],
)
@pytest.mark.usefixtures("active_config")
def test_altered_or_non_json_artifact_is_blocked_after_hashing(
    client: TestClient, admit: Callable, artifact_id: str
) -> None:
    body = admit(artifact_id).json()

    assert (body["decision"], body["reason_code"]) == ("DENY", "ARTIFACT_BLOCKED")
    assert body["output"] is None
    assert body["adapter_calls"]["artifact_admit"] == "SUCCEEDED"
    assert store(client).reads[artifact_id] == 1


@pytest.mark.usefixtures("active_config")
def test_unknown_artifact_is_blocked_before_reading(client: TestClient, admit: Callable) -> None:
    body = admit("art-unknown").json()

    assert (body["decision"], body["reason_code"]) == ("DENY", "ARTIFACT_BLOCKED")
    assert body["adapter_calls"]["artifact_admit"] == "NOT_CALLED"
    assert store(client).read_count == 0


@pytest.mark.usefixtures("active_config")
def test_role_without_the_tool_is_denied_before_reading(
    client: TestClient, admit: Callable
) -> None:
    body = admit("art-summary-template", identity="analyst-a").json()

    assert (body["decision"], body["reason_code"]) == ("DENY", "TOOL_FORBIDDEN")
    assert body["adapter_calls"]["artifact_admit"] == "NOT_CALLED"
    assert store(client).read_count == 0


def test_switched_off_artifact_control_admits_nothing(
    client: TestClient, db_path: Path, admit: Callable
) -> None:
    shipped = config_document("policy")
    assert isinstance(shipped, Policy)
    off = shipped.model_copy(
        update={"controls": shipped.controls.model_copy(update={"artifacts": False})}
    )
    activate_config(db_path, "policy", off)
    activate_config(db_path, "feed")

    body = admit("art-summary-template").json()

    assert (body["decision"], body["reason_code"]) == ("DENY", "TOOL_FORBIDDEN")
    assert store(client).read_count == 0


@pytest.mark.usefixtures("active_config")
def test_one_request_uses_the_feed_pinned_at_admission(
    client: TestClient,
    headers: Headers,
    db_path: Path,
    admit: Callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = store(client)
    read = artifacts.read
    blocking = Feed(
        schema_version=1,
        rules=(FeedRule.model_validate(rule(digest_of("art-summary-template"))),),
    )

    def read_while_the_feed_changes(entry: ManifestEntry) -> bytes:
        activate_config(db_path, "feed", blocking)
        return read(entry)

    monkeypatch.setattr(artifacts, "read", read_while_the_feed_changes)
    during = admit("art-summary-template").json()
    monkeypatch.setattr(artifacts, "read", read)
    after = admit("art-summary-template").json()

    assert during["decision"] == "ALLOW"
    assert {e["feed_version"] for e in events_of(client, headers, during["request_id"])} == {1}
    assert after["decision"] == "DENY"


@pytest.mark.usefixtures("active_config")
def test_invalid_stored_feed_stops_protected_operations(
    client: TestClient, db_path: Path, admit: Callable, execute: Execute, new_task: NewTask
) -> None:
    body = json.dumps({"schema_version": 1, "rules": [{"rule_id": "x"}]})
    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute(
            "INSERT INTO config_versions (kind, version, body, sha256, created_at, created_by)"
            " VALUES ('feed', 2, ?, ?, '2026-10-03T00:00:00Z', 'test')",
            (body, hashlib.sha256(body.encode()).hexdigest()),
        )
        conn.execute("UPDATE active_config SET version = 2 WHERE kind = 'feed'")

    for response in (
        admit("art-summary-template"),
        execute("analyst-a", new_task("analyst-a"), "documents.read", document_id="doc-a"),
    ):
        assert response.status_code == 503
        assert response.json()["reason_code"] == "INVALID_CONFIG"
    assert store(client).read_count == 0
    assert client.app.state.documents.read_count == 0


# --------------------------------------------------------------------------------------
# Feed API
# --------------------------------------------------------------------------------------


@pytest.mark.usefixtures("active_config")
def test_admin_reads_the_active_feed(client: TestClient, headers: Headers) -> None:
    response = client.get("/admin/feed", headers=headers["admin"])

    assert response.status_code == 200
    body = response.json()
    assert (body["feed_version"], body["created_by"]) == (1, "test")
    assert body["feed"] == {"schema_version": 1, "rules": []}
    canonical = json.dumps(body["feed"], sort_keys=True, separators=(",", ":"))
    assert body["sha256"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_feed_is_unavailable_until_one_is_active(client: TestClient, headers: Headers) -> None:
    response = client.get("/admin/feed", headers=headers["admin"])

    assert response.status_code == 503
    assert response.json()["reason_code"] == "INVALID_CONFIG"


@pytest.mark.parametrize(
    "rules",
    [
        [rule("A" * 64)],  # not lowercase hex
        [rule("ab" * 31)],  # too short
        [rule("0" * 64), rule("0" * 64, rule_id="blk-copy")],  # duplicate hash
        [rule("0" * 64) | {"kind": "regex"}],  # only sha256 rules exist
        [rule("0" * 64) | {"reason": "<script>alert(1)</script>"}],  # no markup
        [rule("0" * 64) | {"action": "exec"}],  # unknown field
    ],
)
@pytest.mark.usefixtures("active_config")
def test_invalid_feed_keeps_the_existing_rules(
    client: TestClient, headers: Headers, admit: Callable, rules: list[dict[str, Any]]
) -> None:
    blocked = digest_of("art-summary-template")
    assert put_feed(client, headers, [rule(blocked)], expected=1).status_code == 200

    response = put_feed(client, headers, rules, expected=2)

    assert response.status_code == 422
    assert response.json()["reason_code"] == "INVALID_INPUT"
    active = client.get("/admin/feed", headers=headers["admin"]).json()
    assert active["feed_version"] == 2
    assert [r["value"] for r in active["feed"]["rules"]] == [blocked]
    assert admit("art-summary-template").json()["reason_code"] == "ARTIFACT_BLOCKED"


@pytest.mark.usefixtures("active_config")
def test_stale_feed_update_is_refused(client: TestClient, headers: Headers) -> None:
    assert put_feed(client, headers, [rule("1" * 64)], expected=1).status_code == 200

    stale = put_feed(client, headers, [], expected=1)

    assert stale.status_code == 409
    assert stale.json()["reason_code"] == "VERSION_CONFLICT"
    active = client.get("/admin/feed", headers=headers["admin"]).json()
    assert (active["feed_version"], len(active["feed"]["rules"])) == (2, 1)


def test_feed_rule_limit_is_enforced(client: TestClient, headers: Headers) -> None:
    rules = [rule(f"{i:064x}", rule_id=f"blk-{i}") for i in range(1001)]

    assert put_feed(client, headers, rules, expected=None).status_code == 422


@pytest.mark.usefixtures("active_config")
def test_only_the_admin_reads_or_changes_the_feed(client: TestClient, headers: Headers) -> None:
    for identity in ("analyst-a", "reviewer-a"):
        assert client.get("/admin/feed", headers=headers[identity]).status_code == 403
        body = {
            "schema_version": 1,
            "expected_version": 1,
            "feed": {"schema_version": 1, "rules": []},
        }
        assert client.put("/admin/feed", json=body, headers=headers[identity]).status_code == 403
    assert client.get("/admin/feed").status_code == 401


# --------------------------------------------------------------------------------------
# Size limit and the check on its own
# --------------------------------------------------------------------------------------


@pytest.fixture
def large_artifact_client(
    tmp_path: Path, settings: Settings, providers: StubProviders
) -> Iterator[TestClient]:
    artifacts_dir = tmp_path / "artifacts"
    (artifacts_dir / "content").mkdir(parents=True)
    data = b'{"schema_version": 1, "padding": "' + b"x" * MAX_ARTIFACT_BYTES + b'"}'
    (artifacts_dir / "content" / "art-large.artifact").write_bytes(data)
    manifest = {
        "schema_version": 1,
        "artifacts": [{"artifact_id": "art-large", "sha256": hashlib.sha256(data).hexdigest()}],
    }
    (artifacts_dir / "manifest.json").write_text(json.dumps(manifest))
    custom = settings.model_copy(update={"artifacts_dir": artifacts_dir})
    with TestClient(create_app(custom, providers)) as test_client:
        activate_config(custom.db_path, "policy")
        activate_config(custom.db_path, "feed")
        yield test_client


def test_artifact_over_the_size_limit_is_refused(
    large_artifact_client: TestClient, headers: Headers
) -> None:
    client = large_artifact_client
    task = client.post(
        "/v1/tasks", json={"schema_version": 1, "client_id": "client-a"}, headers=headers["admin"]
    ).json()["task_id"]
    body = {
        "schema_version": 1,
        "task_id": task,
        "tool": "artifacts.admit",
        "arguments": {"artifact_id": "art-large"},
    }
    response = client.post(
        "/v1/execute",
        json=body,
        headers=headers["admin"] | {"Idempotency-Key": "00000000-0000-4000-8000-000000000001"},
    ).json()

    assert (response["decision"], response["reason_code"]) == ("DENY", "INPUT_TOO_LARGE")
    assert response["adapter_calls"]["artifact_admit"] == "FAILED"


def test_check_uses_the_bytes_it_is_given() -> None:
    data = (CONTENT / "art-model-card.artifact").read_bytes()
    entry = ManifestEntry(artifact_id="art-model-card", sha256=digest_of("art-model-card"))
    empty = Feed(schema_version=1, rules=())

    assert check_bytes(entry, data, empty)[0].decision == "ALLOW"
    # One changed byte changes the digest, so the manifest no longer matches.
    assert check_bytes(entry, data.replace(b"demo", b"dem0"), empty)[0].decision == "DENY"
    # Valid bytes under another ID are refused: the document names its own artifact.
    other = ManifestEntry(artifact_id="art-other", sha256=entry.sha256)
    assert check_bytes(other, data, empty)[0].decision == "DENY"
