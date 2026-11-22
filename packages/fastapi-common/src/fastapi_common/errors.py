"""Error envelope — same shape as the NestJS template's AllExceptionsFilter."""

import logging
from datetime import UTC, datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("errors")


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


_CODE_BY_STATUS = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    429: ErrorCode.TOO_MANY_REQUESTS,
}


class AppError(Exception):
    """Business error. `code` may be any app-specific string, not only `ErrorCode`."""

    def __init__(
        self,
        status: int,
        code: str,
        client_message: str,
        system_message: str | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(system_message or client_message)
        self.status = status
        self.code = code
        self.client_message = client_message
        self.system_message = system_message or client_message
        self.data = data


class ErrorResponse(BaseModel):
    statusCode: int
    statusMessage: str
    message: str
    systemMessage: str | list[str]
    code: str
    data: Any = None
    path: str
    timestamp: str


def _status_name(status: int) -> str:
    try:
        return HTTPStatus(status).name
    except ValueError:
        return "Error"


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    system_message: str | list[str],
    *,
    expose_internal_errors: bool,
    data: Any = None,
    exc: BaseException | None = None,
) -> JSONResponse:
    is_server_error = status >= 500
    line = f"[{request.method}] {request.url.path} - {status} - {system_message}"
    if is_server_error:
        logger.error(line, exc_info=exc)
    else:
        logger.warning(line)
    body = ErrorResponse(
        statusCode=status,
        statusMessage=_status_name(status),
        message=message,
        # Production never leaks SQL / driver messages in 5xx bodies; the log keeps them.
        systemMessage=(
            "Internal Server Error"
            if is_server_error and not expose_internal_errors
            else system_message
        ),
        code=code,
        data=data,
        path=str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""),
        timestamp=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    )
    return JSONResponse(body.model_dump(), status_code=status)


def _unhandled(request: Request, exc: BaseException, expose_internal_errors: bool) -> JSONResponse:
    return error_response(
        request,
        500,
        ErrorCode.INTERNAL_SERVER_ERROR,
        "서버 내부 오류가 발생했습니다.",
        str(exc) or type(exc).__name__,
        expose_internal_errors=expose_internal_errors,
        exc=exc,
    )


class UnhandledErrorMiddleware:
    """Unexpected exceptions -> 500 envelope *inside* CORS / request-id middleware.

    FastAPI's `Exception` handler runs in the outermost ServerErrorMiddleware, after request
    context and CORS have unwound — the 500 would lack `x-request-id`, CORS headers and a
    request id in its log line. Add this first (innermost) with `app.add_middleware`.
    """

    def __init__(self, app: ASGIApp, *, expose_internal_errors: bool) -> None:
        self.app = app
        self.expose_internal_errors = expose_internal_errors

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if started:  # e.g. mid-stream (SSE): too late for an error body
                raise
            response = _unhandled(Request(scope), exc, self.expose_internal_errors)
            await response(scope, receive, send)


def register_exception_handlers(app: FastAPI, *, expose_internal_errors: bool) -> None:
    def respond(
        request: Request,
        status: int,
        code: str,
        message: str,
        system_message: str | list[str],
        data: Any = None,
        exc: BaseException | None = None,
    ) -> JSONResponse:
        return error_response(
            request,
            status,
            code,
            message,
            system_message,
            expose_internal_errors=expose_internal_errors,
            data=data,
            exc=exc,
        )

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return respond(
            request, exc.status, exc.code, exc.client_message, exc.system_message, exc.data, exc
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        violations = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        ]
        return respond(request, 400, ErrorCode.BAD_REQUEST, ", ".join(violations), violations)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _CODE_BY_STATUS.get(exc.status_code, ErrorCode.INTERNAL_SERVER_ERROR)
        detail = exc.detail if isinstance(exc.detail, str) else "오류가 발생했습니다."
        response = respond(request, exc.status_code, code, detail, detail, exc=exc)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    # Fallback only — UnhandledErrorMiddleware answers first when it is installed.
    @app.exception_handler(Exception)
    async def _last_resort(request: Request, exc: Exception) -> JSONResponse:
        return _unhandled(request, exc, expose_internal_errors)
