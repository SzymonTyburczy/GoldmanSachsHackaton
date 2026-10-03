"""Error envelope shared by all API routes.

Error bodies carry ``request_id`` and a ``ReasonCode``; validation errors list only the
location and type of each problem and never echo submitted values.
"""

from uuid import UUID

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.contracts import ErrorDetail, ErrorResponse, ReasonCode

MAX_REPORTED_ERRORS = 20
MAX_LOC_PART_CHARS = 64


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        reason_code: ReasonCode,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(reason_code.value)
        self.status_code = status_code
        self.reason_code = reason_code
        self.headers = headers


def request_id_of(request: Request) -> UUID:
    return request.state.request_id


def error_response(
    request: Request,
    status_code: int,
    reason_code: ReasonCode,
    errors: tuple[ErrorDetail, ...] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(request_id=request_id_of(request), reason_code=reason_code, errors=errors)
    return JSONResponse(
        status_code=status_code, content=body.model_dump(mode="json"), headers=headers
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(request, exc.status_code, exc.reason_code, headers=exc.headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = tuple(
        ErrorDetail(
            loc=tuple(
                part if isinstance(part, int) else str(part)[:MAX_LOC_PART_CHARS]
                for part in error.get("loc", ())
            ),
            type=str(error.get("type", "value_error"))[:MAX_LOC_PART_CHARS],
        )
        for error in exc.errors()[:MAX_REPORTED_ERRORS]
    )
    return error_response(request, 422, ReasonCode.INVALID_INPUT, errors)
