"""stdlib logging -> one JSON object per line (local: readable single line).

Every line carries `request_id` inside a request. Feature code uses `logging.getLogger(__name__)`
and passes structured fields via `extra={...}`; never log bodies, tokens or personal data.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from fastapi_common.context import current_request_id

_RESERVED = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

# Libraries whose DEBUG/INFO lines carry SQL parameters or request bodies (prompts, outputs).
QUIET_LOGGERS = (
    "aiosqlite",
    "sqlalchemy",
    "httpx",
    "httpcore",
    "anthropic",
    "claude_agent_sdk",
    "sse_starlette",
    "mcp",
)


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    fields = {k: v for k, v in vars(record).items() if k not in _RESERVED and not k.startswith("_")}
    request_id = current_request_id()
    if request_id and "request_id" not in fields:
        fields["request_id"] = request_id
    return fields


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": self._service,
            "logger": record.name,
            "msg": record.getMessage(),
            **_fields(record),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        when = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        extras = " ".join(f"{k}={v}" for k, v in _fields(record).items())
        line = f"{when} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if extras:
            line = f"{line} {extras}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(*, level: str, service: str, json_output: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service) if json_output else ConsoleFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # uvicorn logs through the root handler; its access log is replaced by RequestContextMiddleware.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
