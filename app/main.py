"""ControlProof application factory.

Run with ``make dev`` (``uvicorn --factory app.main:create_app``): one process, one worker.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.api import admin, health, v1
from app.api.errors import ApiError, api_error_handler, validation_error_handler
from app.settings import Settings

STATIC_DIR = Path(__file__).with_name("static")

PANEL_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'"
)
# Swagger UI and ReDoc load their assets from a CDN, so the panel CSP is not applied there.
DOCS_PATHS = ("/docs", "/redoc")

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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Fails startup on an unknown schema version instead of serving with it.
        db.init_db(settings.db_path)
        yield

    app = FastAPI(title="ControlProof", version="0.1.0", lifespan=lifespan, telemetry=TELEMETRY_OFF)
    app.state.settings = settings

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
