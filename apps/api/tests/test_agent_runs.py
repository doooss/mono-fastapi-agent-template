from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update

from agent_core import Backend, BackendError
from agent_core.testing import ScriptedBackend
from api.modules.agents.models import AgentRun
from fastapi_common import utcnow

pytestmark = pytest.mark.e2e

Sse = Callable[[str], list[dict[str, Any]]]


async def run(client: httpx.AsyncClient, body: dict[str, object]) -> httpx.Response:
    return await client.post("/v1/agents/assistant/runs", json=body)


async def test_run_streams_events_and_records_a_replayable_run(
    client: httpx.AsyncClient, parse_sse: Sse
) -> None:
    response = await run(client, {"input": "hello"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert types[-1] == "run.completed"
    assert ("subagent.started", "main") in [(e["type"], e["agent"]) for e in events]
    assert "main/researcher#call_assistant_1_0" in {e["agent"] for e in events}
    final = events[-1]
    assert (final["output"], final["turns"], final["usage"]["input_tokens"]) == ("answer", 3, 30)

    run_id = response.headers["x-run-id"]
    stored = (await client.get(f"/v1/runs/{run_id}")).json()["data"]
    assert (stored["status"], stored["output"], stored["turns"]) == ("completed", "answer", 3)
    replay = (await client.get(f"/v1/runs/{run_id}/events")).json()["data"]
    assert [e["seq"] for e in replay] == [e["seq"] for e in events if e["type"] != "text.delta"]


async def test_session_continues_on_its_own_backend(
    client: httpx.AsyncClient, parse_sse: Sse
) -> None:
    first = await run(client, {"input": "one", "backend": "managed"})
    session_id = first.headers["x-session-id"]

    second = await run(client, {"input": "two", "session_id": session_id})
    mismatch = await run(client, {"input": "x", "session_id": session_id, "backend": "messages"})

    assert parse_sse(second.text)[0]["backend"] == "managed"
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "SESSION_BACKEND_MISMATCH"
    runs = (await client.get(f"/v1/sessions/{session_id}/runs")).json()["data"]
    assert runs["pagination"]["total"] == 2
    assert [r["prompt"] for r in runs["items"]] == ["two", "one"]


async def test_request_errors_use_the_error_envelope(client: httpx.AsyncClient) -> None:
    unknown = await client.post("/v1/agents/nope/runs", json={"input": "x"})
    empty = await run(client, {"input": ""})
    no_session = await run(client, {"input": "x", "session_id": "missing"})
    no_backend = await run(client, {"input": "x", "backend": "agent_sdk"})

    assert (unknown.status_code, unknown.json()["code"]) == (404, "AGENT_NOT_FOUND")
    assert (empty.status_code, empty.json()["code"]) == (400, "BAD_REQUEST")
    assert isinstance(empty.json()["systemMessage"], list)
    assert (no_session.status_code, no_session.json()["code"]) == (404, "SESSION_NOT_FOUND")
    assert (no_backend.status_code, no_backend.json()["code"]) == (400, "BACKEND_NOT_AVAILABLE")


async def test_backend_failure_streams_run_failed_and_marks_the_run(
    make_app: Callable[[dict[str, Backend]], FastAPI], parse_sse: Sse
) -> None:
    failing = ScriptedBackend({}, fail_with=BackendError("UPSTREAM_UNAVAILABLE", "down"))
    app = make_app({"messages": failing})
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        response = await run(c, {"input": "hello"})
        stored = (await c.get(f"/v1/runs/{response.headers['x-run-id']}")).json()["data"]
        retry = await run(c, {"input": "again", "session_id": response.headers["x-session-id"]})

    final = parse_sse(response.text)[-1]
    assert (final["type"], final["code"]) == ("run.failed", "UPSTREAM_UNAVAILABLE")
    assert (stored["status"], stored["error_code"]) == ("failed", "UPSTREAM_UNAVAILABLE")
    assert retry.status_code == 200  # a finished run no longer blocks the session


async def test_a_running_run_blocks_its_session_until_it_goes_stale(
    make_app: Callable[[dict[str, Backend] | None], FastAPI],
) -> None:
    app = make_app(None)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        session_id = (await run(c, {"input": "first"})).headers["x-session-id"]
        db = app.state.db
        async with db.sessions() as s, s.begin():
            orphan = AgentRun(session_id=session_id, status="running", prompt="lost")
            s.add(orphan)
        blocked = await run(c, {"input": "x", "session_id": session_id})

        async with db.sessions() as s, s.begin():
            await s.execute(
                update(AgentRun)
                .where(AgentRun.id == orphan.id)
                .values(created_at=utcnow() - timedelta(hours=1))
            )
        resumed = await run(c, {"input": "y", "session_id": session_id})
        reaped = (await c.get(f"/v1/runs/{orphan.id}")).json()["data"]

    assert (blocked.status_code, blocked.json()["code"]) == (409, "RUN_IN_PROGRESS")
    assert resumed.status_code == 200
    assert (reaped["status"], reaped["error_code"]) == ("failed", "RUN_INTERRUPTED")
