# Monorepo

패키지를 넘나드는 수정 · 새 앱 / 패키지 · 의존성 추가 시. uv workspace.

## Layout

```
apps/
  api/                 FastAPI 앱 (project "api", import `api`) · migrations/ · VERSION · tests/
packages/
  agent-core/          백엔드 무관 에이전트 런타임 (import `agent_core`)
  fastapi-common/      공유 FastAPI 인프라 (import `fastapi_common`)
docker/  docs/  agent-work/  scripts/
```

## Import 방향

```
fastapi-common ──► apps/*        agent-core ──► apps/*
```

- `packages/*` 는 `apps/*` 를 import 하지 않는다. `agent-core` 는 FastAPI · DB 를 모른다 (HTTP 없는 worker 에서도 쓴다).
- 패키지 간 = 패키지 이름 import. `[tool.uv.sources] <pkg> = { workspace = true }` 로 연결.

## 알아둘 것

- lockfile = 루트 `uv.lock` 하나. `pip install` 쓰지 않는다. CI · 이미지 = `uv sync --locked`.
- 워크스페이스 멤버는 editable 설치 — 패키지 수정은 빌드 없이 바로 반영된다.
- `pyproject.toml` 의 `version` 은 올리지 않는다 (uv.lock 이 기록). 릴리스 버전 = `apps/*/VERSION` (릴리스 파이프라인이 기록).
- uv 버전을 올리면 `.github/workflows/ci.yml` 의 `setup-uv` `version` 과 `docker/api.Dockerfile` 의 uv 이미지 태그를 같이 올린다.
- 앱 작업 디렉터리 = `apps/api` — `.env.<APP_ENV>` · SQLite 파일 · `alembic.ini` 기준.

## 명령

| 작업 | 명령 |
| --- | --- |
| 의존성 추가 | `uv add --package <api\|agent-core\|fastapi-common> <dep>` · 개발 도구 `uv add --dev <dep>` |
| 새 패키지 | `packages/<name>/pyproject.toml` (build-backend `uv_build`, `src/<module>/`) → 루트 `[tool.uv.sources]` · `dependencies` · mypy `mypy_path` · ruff `known-first-party` |
| 새 앱 | `apps/<name>/` 같은 형식 + `docker/<name>.Dockerfile` + `DEPLOY_APPS` 변수 |

공개 API 사양 = `docs/specs/packages/<name>.md`.
