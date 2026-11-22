"""App factory. Run: `uv run poe dev:api` (uvicorn api.main:create_app --factory)."""

import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from anthropic import AsyncAnthropic
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_core import Backend, Runner
from api.modules.agents.registry import build_agents
from api.modules.agents.router import router as agents_router
from api.modules.agents.service import AgentRunService, SqlSessionStore
from api.modules.health.router import router as health_router
from api.settings import Settings
from fastapi_common import (
    AppEnv,
    Database,
    RequestContextMiddleware,
    UnhandledErrorMiddleware,
    configure_logging,
    mount_docs,
    register_exception_handlers,
)

# apps/api in the repo; the image sets APP_DIR because the package is installed into site-packages.
APP_DIR = Path(os.environ.get("APP_DIR") or Path(__file__).resolve().parents[2])


def app_version() -> str:
    path = APP_DIR / "VERSION"
    return path.read_text().strip() if path.exists() else "0.0.0"


def run_migrations(database_url: str) -> None:
    config = Config(str(APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(APP_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def build_backends(settings: Settings) -> dict[str, Backend]:
    # Imported here so a test app with fake backends never loads the vendor SDKs.
    from agent_core.backends import AgentSdkBackend, ManagedBackend, MessagesBackend

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return {
        "messages": MessagesBackend(client),
        "agent_sdk": AgentSdkBackend(
            api_key=settings.anthropic_api_key, workdir=settings.AGENT_SDK_WORKDIR
        ),
        "managed": ManagedBackend(client, environment_name=settings.MANAGED_ENVIRONMENT_NAME),
    }


def create_app(
    settings: Settings | None = None, *, backends: Mapping[str, Backend] | None = None
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(
        level=settings.log_level,
        service=settings.SERVICE_NAME,
        json_output=settings.APP_ENV is not AppEnv.LOCAL,
    )
    db = Database(settings.DATABASE_URL)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.migrate_on_start:
            # Alembic's env runs its own event loop; keep it off ours.
            await asyncio.to_thread(run_migrations, settings.DATABASE_URL)
        yield
        await db.dispose()

    app = FastAPI(
        title=f"{settings.SERVICE_NAME} API",
        version=app_version(),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    runner = Runner(
        backends or build_backends(settings),
        SqlSessionStore(db),
        run_timeout_s=settings.RUN_TIMEOUT_SECONDS,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.agent_service = AgentRunService(
        db, runner, build_agents(settings), default_backend=settings.AGENT_BACKEND
    )

    expose = not settings.is_production
    register_exception_handlers(app, expose_internal_errors=expose)
    # Middleware: first added = innermost. Unhandled 500s are rendered inside CORS + request id.
    app.add_middleware(UnhandledErrorMiddleware, expose_internal_errors=expose)
    origins = settings.allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "HEAD", "PUT", "PATCH", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "Accept", "x-request-id", "traceparent"],
        expose_headers=["x-request-id", "x-session-id", "x-run-id"],
    )
    # Added last = outermost: every response (CORS preflight included) gets an x-request-id.
    app.add_middleware(RequestContextMiddleware)

    v1 = APIRouter(prefix="/v1")
    v1.include_router(health_router)
    v1.include_router(agents_router)
    app.include_router(v1)
    mount_docs(
        app,
        user=settings.DOCS_USER,
        password=settings.DOCS_PASSWORD.get_secret_value(),
        title=settings.SERVICE_NAME,
    )
    return app
