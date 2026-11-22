import json
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from agent_core import Backend
from agent_core.testing import ScriptedBackend, ScriptedTurn
from api.main import create_app
from api.settings import Settings

SCRIPT = {
    "assistant": [
        ScriptedTurn(text="looking", tool_calls=[("delegate_to_researcher", {"task": "q"})]),
        ScriptedTurn(text="answer"),
    ],
    "researcher": [ScriptedTurn(text="finding")],
}


AppFactory = Callable[[Mapping[str, Backend] | None], FastAPI]


def _make_app(tmp_path: Path, backends: Mapping[str, Backend] | None = None) -> FastAPI:
    settings = Settings(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        DB_MIGRATE_ON_START=True,
        AGENT_BACKEND="messages",
        DOCS_PASSWORD=SecretStr("docs-secret"),
    )
    return create_app(
        settings,
        backends=backends
        or {"messages": ScriptedBackend(SCRIPT), "managed": ScriptedBackend(SCRIPT)},
    )


@pytest.fixture
def make_app(tmp_path: Path) -> AppFactory:
    """App on a fresh SQLite file (migrated at startup) with scripted backends."""

    def factory(backends: Mapping[str, Backend] | None = None) -> FastAPI:
        return _make_app(tmp_path, backends)

    return factory


@pytest.fixture
async def client(make_app: AppFactory) -> AsyncIterator[httpx.AsyncClient]:
    app = make_app(None)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture
def parse_sse() -> Callable[[str], list[dict[str, Any]]]:
    return _parse_sse


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "data" in fields and "event" in fields:
            events.append(json.loads(fields["data"]))
    return events
