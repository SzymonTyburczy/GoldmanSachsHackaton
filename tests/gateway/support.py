"""Test helpers shared by gateway tests: demo tokens, config activation, audit outage."""

import sqlite3
from contextlib import closing
from pathlib import Path

TOKENS = {
    "analyst-a": "analyst-a-test-token-0123456789abcdef",
    "reviewer-a": "reviewer-a-test-token-0123456789abcdef",
    "admin": "admin-test-token-0123456789abcdef0123",
}


def activate_config(db_path: Path, kind: str, version: int) -> None:
    """Store and activate a placeholder version; A4 replaces it with a validated policy."""
    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute(
            "INSERT INTO config_versions (kind, version, body, sha256, created_at, created_by)"
            " VALUES (?, ?, '{}', ?, '2026-10-03T00:00:00Z', 'test')",
            (kind, version, "0" * 64),
        )
        conn.execute(
            "INSERT INTO active_config (kind, version, activated_at)"
            " VALUES (?, ?, '2026-10-03T00:00:00Z')",
            (kind, version),
        )


def break_audit(db_path: Path, stage: str) -> None:
    """Make every audit insert for ``stage`` fail, as a full disk or a locked file would."""
    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute(
            f"CREATE TRIGGER audit_outage_{stage} BEFORE INSERT ON audit_events"
            f" WHEN NEW.stage = '{stage}' BEGIN SELECT RAISE(ABORT, 'disk I/O error'); END"
        )
