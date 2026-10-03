import sqlite3
from contextlib import closing

from fastapi import APIRouter, Request

from app import db
from app.contracts import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Process and configuration state. Does not ping paid providers or expose keys."""
    try:
        with closing(db.connect(request.app.state.settings.db_path)) as conn:
            rows = conn.execute("SELECT kind, version FROM active_config").fetchall()
    except sqlite3.Error:
        return HealthResponse(
            status="degraded",
            database="unavailable",
            policy_version=None,
            feed_version=None,
            protected_operations="disabled",
        )
    active = {row["kind"]: row["version"] for row in rows}
    policy_version = active.get("policy")
    feed_version = active.get("feed")
    # Without an active policy and feed the gateway refuses protected operations.
    ready = policy_version is not None and feed_version is not None
    return HealthResponse(
        status="ok" if ready else "degraded",
        database="ok",
        policy_version=policy_version,
        feed_version=feed_version,
        protected_operations="enabled" if ready else "disabled",
    )
