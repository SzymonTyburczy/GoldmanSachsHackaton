"""Admin API skeleton (docs/WSPOLNE_USTALENIA.md, section 5).

Every route refuses with 501 ``NOT_IMPLEMENTED`` until its step is built.
"""

from fastapi import APIRouter

from app.api.errors import ApiError
from app.contracts import ReasonCode

router = APIRouter(prefix="/admin")


def _not_implemented() -> ApiError:
    return ApiError(501, ReasonCode.NOT_IMPLEMENTED)


@router.get("/policy")
def get_policy() -> None:
    """A4: full active policy and its version."""
    raise _not_implemented()


@router.put("/policy")
def put_policy() -> None:
    """A4: validate a complete policy and activate it atomically."""
    raise _not_implemented()


@router.get("/feed")
def get_feed() -> None:
    """A6: active artifact feed and its version."""
    raise _not_implemented()


@router.put("/feed")
def put_feed() -> None:
    """A6: validate a complete feed and activate it atomically."""
    raise _not_implemented()


@router.get("/events")
def list_events() -> None:
    """A3: audit events with bounded pagination and a task filter."""
    raise _not_implemented()


@router.get("/metrics")
def get_metrics() -> None:
    """A6/B4: counters, active and disabled controls, cost and reservations."""
    raise _not_implemented()


@router.get("/audit/export")
def export_audit() -> None:
    """A3: JSONL export from the same audit_events table as the panel."""
    raise _not_implemented()


@router.get("/test-results")
def get_test_results() -> None:
    """B5/A6: last saved test report with time and commit; never runs tests."""
    raise _not_implemented()
