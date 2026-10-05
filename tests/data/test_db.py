import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import create_app
from app.settings import Settings

EXPECTED_TABLES = {
    "active_config",
    "audit_events",
    "budget_accounts",
    "config_versions",
    "requests",
    "reservations",
    "tasks",
}
NOW = "2026-10-03T00:00:00Z"


@pytest.fixture
def conn(db_path: Path):
    db.init_db(db_path)
    with closing(db.connect(db_path)) as connection:
        yield connection


def insert_task(conn: sqlite3.Connection, task_id: str = "task-1") -> None:
    conn.execute(
        "INSERT INTO tasks (task_id, principal_id, agent_id, client_id, created_at)"
        " VALUES (?, 'analyst-a', 'demo-agent', 'client-a', ?)",
        (task_id, NOW),
    )


def insert_reservation(conn: sqlite3.Connection, **overrides: object) -> None:
    row: dict[str, object] = {
        "reservation_id": "res-1",
        "request_id": "req-1",
        "task_id": "task-1",
        "principal_id": "analyst-a",
        "purpose": "detector",
        "unit": "nusd",
        "amount": 1000,
        "state": "RESERVED",
        "pricing_version": "typesafe-2026-10-03",
        "limit_version": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT INTO reservations ({columns}) VALUES ({placeholders})", tuple(row.values())
    )


def insert_audit_event(conn: sqlite3.Connection, event_id: str = "evt-1") -> None:
    conn.execute(
        "INSERT INTO audit_events (event_id, request_id, occurred_at, control_id, decision,"
        " reason_code, stage, execution_status, event_json)"
        " VALUES (?, 'req-1', ?, 'access', 'DENY', 'CLIENT_FORBIDDEN', 'pre_document',"
        " 'NOT_CALLED', '{}')",
        (event_id, NOW),
    )


def test_init_creates_schema_once(db_path: Path) -> None:
    db.init_db(db_path)
    db.init_db(db_path)  # second start keeps the existing database

    with closing(db.connect(db_path)) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables >= EXPECTED_TABLES
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_unknown_schema_version_stops_startup(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA user_version = 99")

    with pytest.raises(db.SchemaVersionError):
        db.init_db(db_path)
    with pytest.raises(db.SchemaVersionError), TestClient(create_app(Settings(db_path=db_path))):
        pass


def test_transaction_rolls_back_on_error(conn: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError), db.transaction(conn):
        insert_task(conn)
        raise RuntimeError("simulated failure after the write")

    assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert not conn.in_transaction


def test_transaction_commits_on_success(conn: sqlite3.Connection, db_path: Path) -> None:
    with db.transaction(conn):
        insert_task(conn)

    with closing(db.connect(db_path)) as other:
        assert other.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


def test_audit_events_are_append_only(conn: sqlite3.Connection) -> None:
    insert_audit_event(conn)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_events SET decision = 'ALLOW'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_events")
    assert conn.execute("SELECT decision FROM audit_events").fetchone()[0] == "DENY"


def test_active_config_must_point_at_a_stored_version(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO active_config (kind, version, activated_at) VALUES ('policy', 1, ?)",
            (NOW,),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"unit": "test_credit"},  # test credits only for fixtures
        {"purpose": "fixture"},  # fixtures never spend nUSD
        {"pricing_version": None},
        {"amount": 0},
        {"state": "CANCELLED"},
        {"task_id": "missing-task"},
    ],
)
def test_reservation_constraints(conn: sqlite3.Connection, overrides: dict[str, object]) -> None:
    insert_task(conn)

    with pytest.raises(sqlite3.IntegrityError):
        insert_reservation(conn, **overrides)


def test_valid_reservations_are_stored(conn: sqlite3.Connection) -> None:
    insert_task(conn)
    insert_reservation(conn)
    insert_reservation(
        conn, reservation_id="res-2", purpose="fixture", unit="test_credit", pricing_version=None
    )

    assert conn.execute("SELECT count(*) FROM reservations").fetchone()[0] == 2


def test_migration_from_v1_preserves_tasks_and_adds_review_queue(db_path: Path) -> None:
    db.init_db(db_path)
    with closing(db.connect(db_path)) as conn:
        insert_task(conn)
        conn.execute("DROP TABLE human_reviews")
        conn.execute("PRAGMA user_version = 1")
    db.init_db(db_path)
    with closing(db.connect(db_path)) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM human_reviews").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
