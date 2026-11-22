# FastAPI

`apps/api` 코드 · DB 에 적용.

## Stack

| 영역 | 선택 |
| --- | --- |
| Runtime | Python 3.14 + uv workspace |
| Framework | FastAPI + uvicorn (`api.main:create_app --factory`) · SSE = `sse-starlette` |
| DB | SQLAlchemy 2 async — 기본 SQLite(`aiosqlite`), Postgres 전환 가능 · Alembic 마이그레이션 |
| Validation | pydantic 2 (HTTP 모델 · settings) |
| Docs | Swagger `/api` · OpenAPI `/api-json` · ReDoc `/docs` (basic auth) |
| Test | pytest + pytest-asyncio · httpx `ASGITransport` (e2e) |

모든 라우트 `/v1/...` (`APIRouter(prefix="/v1")`).

## 모듈

```
apps/api/src/api/modules/<feature>/
  router.py      HTTP — 경로 · 의존성 · 응답 envelope
  service.py     로직 · 트랜잭션
  models.py      이 모듈 소유 ORM 모델
  schemas.py     요청 / 응답 pydantic 모델
```

- 새 기능 = 모듈 폴더 + `main.py` 의 `v1.include_router`. 서비스는 `app.state` 에 만들어 두고 `Depends` 로 받는다.
- 두 앱 이상이 쓰는 인프라 → `packages/fastapi-common` ([monorepo.md](monorepo.md)).

## API 경계

- **응답**: 핸들러는 `ok(data)` 를 반환하고 `-> StandardResponse[T]` 를 선언한다 (OpenAPI 타입 유지). SSE 는 감싸지 않는다.
- **에러**: 비즈니스 에러 = `AppError(status, code, client_message, system_message)`. 포맷은 `register_exception_handlers` 가 만든다 — 손으로 JSON 에러를 만들지 않는다.
- **목록**: `Depends(page_query)` + `Page.build(items, total, query)`. `limit` 상한 100.
- **설정**: `Settings`(`api/settings.py`) 만 읽는다. 기능 코드에서 `os.environ` 직접 사용 금지 (`APP_DIR` 같은 부팅 경로 제외).

응답 / 에러 포맷 사양 → [docs/specs/README.md](../../docs/specs/README.md#공통-규약).

## DB

- 모델 = 소유 모듈 `models.py`, `fastapi_common.Base` 상속. 공통 칼럼 = `IdMixin`(uuid hex) · `TimestampMixin`. 시각은 `UTCDateTime` (SQLite 에서도 UTC aware).
- 스키마 변경 = 모델 수정 → `uv run poe db:revision "<msg>"` → 생성된 리비전 검토 → 같은 커밋. env.py 가 모델을 import 해야 autogenerate 가 본다.
- `DB_MIGRATE_ON_START` (기본 production 외 on, 이미지 on) 가 기동 시 `upgrade head` 를 돈다. 다중 인스턴스 · Postgres 운영은 off 로 두고 배포 단계에서 돌린다.
- 쿼리는 SQLAlchemy 표현식 · 바인딩. 문자열 SQL 조립 금지.
