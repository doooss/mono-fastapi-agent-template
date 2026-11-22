from collections.abc import Callable, Mapping

import httpx
import pytest
from fastapi import FastAPI

from agent_core import Backend

pytestmark = pytest.mark.e2e

AppFactory = Callable[[Mapping[str, Backend] | None], FastAPI]


async def test_request_id_is_echoed_only_when_safe(client: httpx.AsyncClient) -> None:
    kept = await client.get("/v1/health", headers={"x-request-id": "abc-123"})
    replaced = await client.get("/v1/health", headers={"x-request-id": "bad id\nforged"})

    assert kept.headers["x-request-id"] == "abc-123"
    assert replaced.headers["x-request-id"] != "bad id\nforged"
    assert len(replaced.headers["x-request-id"]) == 32


async def test_health_reports_db_in_the_success_envelope(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/health")).json()

    assert body["data"]["db"] == "up"
    assert (body["statusCode"], body["statusMessage"]) == (200, "OK")
    assert body["spendTime"].endswith("ms")


async def test_docs_require_basic_auth(client: httpx.AsyncClient) -> None:
    for path in ("/api", "/api-json", "/docs"):
        assert (await client.get(path)).status_code == 401
    authed = await client.get("/api-json", auth=("admin", "docs-secret"))

    assert authed.status_code == 200
    assert "/v1/agents/{name}/runs" in authed.json()["paths"]


async def test_unknown_route_uses_the_error_envelope(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/nope?x=1")).json()

    assert (body["statusCode"], body["code"], body["path"]) == (404, "NOT_FOUND", "/v1/nope?x=1")


async def test_unhandled_errors_keep_request_id_and_cors(make_app: AppFactory) -> None:
    app = make_app(None)

    @app.get("/v1/boom")
    async def boom() -> None:
        raise RuntimeError("driver said no")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        response = await c.get("/v1/boom", headers={"origin": "https://x.test"})

    body = response.json()
    assert (response.status_code, body["code"]) == (500, "INTERNAL_SERVER_ERROR")
    assert response.headers["x-request-id"]
    assert "access-control-allow-origin" in response.headers


async def test_debug_logs_never_carry_prompt_or_output(
    make_app: AppFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    app = make_app(None)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        response = await c.post("/v1/agents/assistant/runs", json={"input": "SECRET-PROMPT-7"})

    logs = capsys.readouterr().out
    assert response.status_code == 200
    assert "request completed" in logs  # logging was captured at all
    assert "SECRET-PROMPT-7" not in logs
    assert "finding" not in logs  # scripted model output
