"""ControlProof application factory.

Run with ``make dev`` (``uvicorn --factory app.main:create_app``): one process, one worker.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import budget, db
from app.adapters.documents import DocumentAdapter, DocumentCatalog
from app.adapters.providers import Providers
from app.api import admin, health, v1
from app.api.errors import ApiError, api_error_handler, validation_error_handler
from app.auth import TokenDirectory
from app.gateway import Gateway
from app.pii.engine import SUPPORTED_LANGUAGES, PiiEngineUnavailable, get_engine
from app.settings import Settings

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).with_name("static")

PANEL_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)
# Swagger UI and ReDoc load their assets from a CDN, so the panel CSP is not applied there.
DOCS_PATHS = ("/docs", "/redoc")
# Authenticated answers (tasks, audit history, exports) must not stay in shared caches.
NO_STORE_PATHS = ("/v1/", "/admin/")

# FastAPI's native OpenTelemetry can record validation failures, including submitted
# values, and export them when OTEL_* variables are set. ControlProof keeps its own audit
# and must not ship request contents elsewhere.
TELEMETRY_OFF = {
    "tracing": False,
    "metrics": False,
    "logs": False,
    "operation_spans": False,
    "auto_configure": False,
}


class _AccessLogWithoutQuery(logging.Filter):
    """Uvicorn's access log records the full URL. A query string can carry a token sent
    there by mistake or other client input, so only the path is kept."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, http_version, status = record.args
            record.args = (client, method, str(path).split("?", 1)[0], http_version, status)
        return True


ACCESS_LOG_FILTER = _AccessLogWithoutQuery()


def create_app(settings: Settings | None = None, providers: Providers | None = None) -> FastAPI:
    """``providers`` replaces the Jev and Luna adapters built from the local keys (tests)."""
    settings = settings or Settings.from_env()
    access_log = logging.getLogger("uvicorn.access")
    if ACCESS_LOG_FILTER not in access_log.filters:
        access_log.addFilter(ACCESS_LOG_FILTER)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Fails startup on an unknown schema version instead of serving with it.
        db.init_db(settings.db_path)
        # Reservations and requests left open by a stopped process may have reached a
        # provider: they become UNKNOWN and keep their amounts (section 7).
        stranded = budget.reconcile_after_restart(settings.db_path)
        if stranded:
            logger.warning("%d open reservations marked UNKNOWN after restart", stranded)
        # Load the spaCy pipelines now rather than on the first request. A failure is not
        # fatal: requests needing redaction are refused until the engine can be built.
        try:
            get_engine(SUPPORTED_LANGUAGES)
        except PiiEngineUnavailable:
            logger.warning("PII engine unavailable; document requests will be refused")
        yield

    app = FastAPI(title="ControlProof", version="0.1.0", lifespan=lifespan, telemetry=TELEMETRY_OFF)
    app.state.settings = settings
    # Weak or duplicated demo tokens and an invalid document catalog stop startup.
    app.state.tokens = TokenDirectory.from_settings(settings)
    catalog = DocumentCatalog.load(settings.documents_dir)
    app.state.documents = DocumentAdapter(settings.documents_dir)
    app.state.gateway = Gateway(settings, catalog, app.state.documents, providers)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith(DOCS_PATHS):
            response.headers["Content-Security-Policy"] = PANEL_CSP
        if request.url.path.startswith(NO_STORE_PATHS):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.include_router(health.router)
    app.include_router(v1.router)
    app.include_router(admin.router)

    @app.get("/", include_in_schema=False)
    def panel() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
