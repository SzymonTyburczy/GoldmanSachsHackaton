"""Request body limit, enforced before any route parses the body (section 3, step 1).

Client routes take at most 32 KiB; ``/admin/`` takes more for complete policy and feed
documents. ``Content-Length`` above the limit is refused at once. The bytes actually
received are counted as well, so a missing or false header or a chunked body cannot get
past the limit: the route then fails while reading and nothing is stored.
"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import error_response
from app.contracts import ErrorResponse, ReasonCode

MAX_BODY_BYTES = 32 * 1024
MAX_ADMIN_BODY_BYTES = 256 * 1024
ADMIN_PREFIX = "/admin/"


class BodyTooLarge(HTTPException):
    """An ``HTTPException``, because FastAPI turns any other error raised while it reads
    the body into a 400."""

    def __init__(self) -> None:
        super().__init__(status_code=413)


async def body_too_large_handler(request: Request, _: Exception) -> JSONResponse:
    return error_response(request, 413, ReasonCode.INPUT_TOO_LARGE)


def limit_for(path: str) -> int:
    return MAX_ADMIN_BODY_BYTES if path.startswith(ADMIN_PREFIX) else MAX_BODY_BYTES


class BodySizeLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope["path"])
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await _send_413(scope, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge()
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except BodyTooLarge:
            if started:
                raise
            await _send_413(scope, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _send_413(scope: Scope, send: Callable[[Message], Awaitable[None]]) -> None:
    state: MutableMapping[str, Any] = scope.get("state", {})
    request_id = state.get("request_id")
    body = ErrorResponse(
        request_id=request_id if isinstance(request_id, UUID) else UUID(int=0),
        reason_code=ReasonCode.INPUT_TOO_LARGE,
    ).model_dump_json()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body.encode()})
