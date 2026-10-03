import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.gateway.support import activate_config


def store_raw(db_path: Path, kind: str, version: int, body: str) -> None:
    """A stored version that bypassed validation, e.g. from an older schema."""
    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute(
            "INSERT INTO config_versions (kind, version, body, sha256, created_at, created_by)"
            " VALUES (?, ?, ?, ?, '2026-10-03T00:00:00Z', 'test')",
            (kind, version, body, hashlib.sha256(body.encode()).hexdigest()),
        )
        conn.execute(
            "INSERT INTO active_config (kind, version, activated_at)"
            " VALUES (?, ?, '2026-10-03T00:00:00Z')",
            (kind, version),
        )


def test_health_without_configuration_disables_protected_operations(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": 1,
        "status": "degraded",
        "database": "ok",
        "policy_version": None,
        "feed_version": None,
        "protected_operations": "disabled",
    }
    UUID(response.headers["X-Request-ID"])


def test_health_reads_active_versions_from_the_database(client: TestClient, db_path: Path) -> None:
    activate_config(db_path, "policy")
    activate_config(db_path, "policy")
    assert client.get("/health").json()["protected_operations"] == "disabled"

    activate_config(db_path, "feed")
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["policy_version"] == 2
    assert body["feed_version"] == 1
    assert body["protected_operations"] == "enabled"


def test_health_disables_operations_when_the_stored_policy_is_invalid(
    client: TestClient, db_path: Path
) -> None:
    store_raw(db_path, "policy", 1, '{"schema_version": 1}')
    activate_config(db_path, "feed")

    body = client.get("/health").json()

    assert (body["policy_version"], body["feed_version"]) == (1, 1)
    assert (body["status"], body["protected_operations"]) == ("degraded", "disabled")


def test_health_reports_unavailable_database(client: TestClient, tmp_path: Path) -> None:
    # A directory cannot be opened as a database file.
    client.app.state.settings = Settings(db_path=tmp_path)

    body = client.get("/health").json()

    assert body["database"] == "unavailable"
    assert body["status"] == "degraded"
    assert body["protected_operations"] == "disabled"


def test_health_never_exposes_secrets(db_path: Path) -> None:
    secrets = {
        "token_analyst_a": "tok-analyst-sentinel-0123456789abcdef",
        "token_admin": "tok-admin-sentinel-0123456789abcdef",
        "openai_api_key": "sk-openai-sentinel",
        "typesafe_api_key": "ts-typesafe-sentinel",
    }
    app = create_app(Settings(db_path=db_path, **secrets))

    with TestClient(app) as client:
        response = client.get("/health")

    for secret in secrets.values():
        assert secret not in response.text
        assert secret not in str(response.headers)
