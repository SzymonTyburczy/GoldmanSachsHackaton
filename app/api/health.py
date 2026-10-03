import sqlite3
from contextlib import closing

from fastapi import APIRouter, Request

from app import db, policy
from app.contracts import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Process and configuration state. Does not ping paid providers or expose keys."""
    try:
        with closing(db.connect(request.app.state.settings.db_path)) as conn:
            versions = policy.active_versions(conn)
            ready = versions.ready and _loads(conn, versions)
    except sqlite3.Error:
        return HealthResponse(
            status="degraded",
            database="unavailable",
            policy_version=None,
            feed_version=None,
            protected_operations="disabled",
        )
    # Without a valid active policy and feed the gateway refuses protected operations.
    return HealthResponse(
        status="ok" if ready else "degraded",
        database="ok",
        policy_version=versions.policy_version,
        feed_version=versions.feed_version,
        protected_operations="enabled" if ready else "disabled",
    )


def _loads(conn: sqlite3.Connection, versions: policy.ActiveVersions) -> bool:
    try:
        policy.load(conn, "policy", versions.policy_version)
        policy.load(conn, "feed", versions.feed_version)
    except policy.StoredConfigError:
        return False
    return True
