"""Per-request context carried by contextvars (safe across concurrent requests)."""

import time
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    started: float = field(default_factory=time.perf_counter)


request_context: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def current_request_id() -> str | None:
    ctx = request_context.get()
    return ctx.request_id if ctx else None


def elapsed_ms() -> int:
    ctx = request_context.get()
    return round((time.perf_counter() - ctx.started) * 1000) if ctx else 0
