"""Test helpers shared by gateway tests: demo tokens, config activation, audit outage."""

import sqlite3
from contextlib import closing
from pathlib import Path

from app import db, policy

TOKENS = {
    "analyst-a": "analyst-a-test-token-0123456789abcdef",
    "reviewer-a": "reviewer-a-test-token-0123456789abcdef",
    "admin": "admin-test-token-0123456789abcdef0123",
}


def config_document(kind: policy.ConfigKind) -> policy.Policy | policy.Feed:
    path = policy.DEFAULT_CONFIG_DIR / policy.CONFIG_FILES[kind]
    return policy.read_config_file(kind, path)


def activate_config(
    db_path: Path, kind: policy.ConfigKind, document: policy.Policy | policy.Feed | None = None
) -> int:
    """Activate ``document`` (default: the file in config/) as the next version."""
    with closing(db.connect(db_path)) as conn:
        current = policy.active_versions(conn)
        stored = policy.activate(
            conn,
            kind,
            document or config_document(kind),
            expected_version=getattr(current, f"{kind}_version"),
            created_by="test",
        )
    return stored.version


def break_audit(db_path: Path, stage: str) -> None:
    """Make every audit insert for ``stage`` fail, as a full disk or a locked file would."""
    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute(
            f"CREATE TRIGGER audit_outage_{stage} BEFORE INSERT ON audit_events"
            f" WHEN NEW.stage = '{stage}' BEGIN SELECT RAISE(ABORT, 'disk I/O error'); END"
        )
