"""Request id in/out + one access log line per request.

Pure ASGI (not BaseHTTPMiddleware) so streaming responses (SSE) pass through untouched and the
contextvar is visible to the endpoint and everything it awaits.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fastapi_common.context import RequestContext, request_context

logger = logging.getLogger("http")

# Client-supplied ids end up in every log line; reject anything that could forge log structure.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def resolve_request_id(header: str | None) -> str:
    if header and _REQUEST_ID_RE.fullmatch(header):
        return header
    return uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get("x-request-id"))
        token = request_context.set(RequestContext(request_id=request_id))
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append("x-request-id", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            logger.info(
                "request completed",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_context.reset(token)
