"""SQLite access shared by all modules.

Open one connection per unit of work with ``connect()``. Connections run in autocommit
mode; group writes with ``transaction()``. It takes the write lock up front
(``BEGIN IMMEDIATE``), so a balance check and the update that follows cannot interleave
with another writer. Never hold a transaction open while calling an external provider.

``python -m app.db`` creates or checks the database configured in the environment.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.settings import Settings

SCHEMA_VERSION = 1
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
BUSY_TIMEOUT_SECONDS = 5.0


class SchemaVersionError(RuntimeError):
    """The database file was created with a schema this code does not know."""


def to_db_time(value: datetime) -> str:
    """Fixed-width UTC text, e.g. ``2026-10-03T16:00:00.000000Z``; sorts chronologically."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_SECONDS, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def init_db(db_path: Path) -> None:
    """Create the schema in a new database or verify the version of an existing one."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        with transaction(conn):
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == SCHEMA_VERSION:
                return
            if version != 0:
                raise SchemaVersionError(
                    f"database schema version {version}, expected {SCHEMA_VERSION}"
                )
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


if __name__ == "__main__":
    path = Settings.from_env().db_path
    init_db(path)
    print(f"Database ready: {path} (schema version {SCHEMA_VERSION})")
