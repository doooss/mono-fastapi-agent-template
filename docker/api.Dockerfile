# syntax=docker/dockerfile:1.7
# Build context = repo root. Installs only `api` and the workspace packages it depends on.
#   docker build -f docker/api.Dockerfile -t api:local .     (uv run poe docker:build)

FROM python:3.14-slim AS build
# Same uv as CI (.github/workflows/ci.yml) — the one that wrote uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /bin/uv
# Venv at its final path: console-script shebangs are absolute, so it cannot move between stages.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /repo

# Dependencies first (cached until a pyproject / lock changes).
COPY pyproject.toml uv.lock .python-version ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/agent-core/pyproject.toml packages/agent-core/
COPY packages/fastapi-common/pyproject.toml packages/fastapi-common/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package api --no-install-workspace

COPY packages packages
COPY apps/api apps/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package api --no-editable

FROM python:3.14-slim
# Agent SDK's bundled CLI writes session transcripts under $HOME/.claude.
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown app /app/data
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY apps/api/alembic.ini apps/api/VERSION ./
COPY apps/api/migrations ./migrations
ENV PATH=/app/.venv/bin:$PATH \
    APP_DIR=/app \
    APP_ENV=production \
    DATABASE_URL=sqlite+aiosqlite:////app/data/database.sqlite \
    DB_MIGRATE_ON_START=true
USER app
EXPOSE 3000
# PORT: platforms (Cloud Run, Render, …) inject it; default 3000.
CMD ["sh", "-c", "exec uvicorn api.main:create_app --factory --host 0.0.0.0 --port ${PORT:-3000}"]
