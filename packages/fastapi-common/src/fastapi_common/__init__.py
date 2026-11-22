"""Shared FastAPI infra — settings, logging, request id, error/success envelopes, DB, docs."""

from fastapi_common.context import current_request_id, request_context
from fastapi_common.db import Base, Database, IdMixin, TimestampMixin, UTCDateTime, utcnow
from fastapi_common.docs import mount_docs
from fastapi_common.errors import (
    AppError,
    ErrorCode,
    ErrorResponse,
    UnhandledErrorMiddleware,
    register_exception_handlers,
)
from fastapi_common.logging import configure_logging
from fastapi_common.middleware import RequestContextMiddleware
from fastapi_common.responses import Page, PageQuery, StandardResponse, ok, page_query
from fastapi_common.settings import AppEnv, BaseAppSettings, parse_allowed_origins

__all__ = [
    "AppEnv",
    "AppError",
    "Base",
    "BaseAppSettings",
    "Database",
    "ErrorCode",
    "ErrorResponse",
    "IdMixin",
    "Page",
    "PageQuery",
    "RequestContextMiddleware",
    "StandardResponse",
    "TimestampMixin",
    "UTCDateTime",
    "UnhandledErrorMiddleware",
    "configure_logging",
    "current_request_id",
    "mount_docs",
    "ok",
    "page_query",
    "parse_allowed_origins",
    "register_exception_handlers",
    "request_context",
    "utcnow",
]
