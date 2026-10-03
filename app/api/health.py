import sqlite3
from contextlib import closing

from fastapi import APIRouter, Request

from app import db
from app.contracts import HealthResponse
from app.policy import active_versions

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Process and configuration state. Does not ping paid providers or expose keys."""
    try:
        with closing(db.connect(request.app.state.settings.db_path)) as conn:
            versions = active_versions(conn)
    except sqlite3.Error:
        return HealthResponse(
            status="degraded",
            database="unavailable",
            policy_version=None,
            feed_version=None,
            protected_operations="disabled",
        )
    # Without an active policy and feed the gateway refuses protected operations.
    return HealthResponse(
        status="ok" if versions.ready else "degraded",
        database="ok",
        policy_version=versions.policy_version,
        feed_version=versions.feed_version,
        protected_operations="enabled" if versions.ready else "disabled",
    )
