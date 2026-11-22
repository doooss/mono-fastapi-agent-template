---
entity: package
name: fastapi-common
code: [packages/fastapi-common/src/fastapi_common]
updated: 2026-11-21
refs: 261121_001_template-bootstrap
---

# fastapi-common (`fastapi_common`)

> 앱 공용 FastAPI 인프라. 포맷 규약은 [공통 규약](../README.md#공통-규약).

## 표면 (공개 API)

| 이름 | 설명 |
| --- | --- |
| `BaseAppSettings` | pydantic-settings 베이스: `APP_ENV` (`local`·`dev`·`qa`·`production`) · `SERVICE_NAME` · `LOG_LEVEL` · `ALLOWED_ORIGINS` · `DOCS_USER` · `DOCS_PASSWORD`. `.env.<APP_ENV>` 읽음, 빈 값 = 미설정. 속성 `is_production` · `allowed_origins` · `log_level` |
| `AppEnv` · `parse_allowed_origins` | env enum · comma list 파서 |
| `configure_logging(*, level, service, json_output)` | root 로거 → stdout. JSON 한 줄(`time` · `level` · `service` · `logger` · `msg` · `extra` 필드 · `request_id`) 또는 local 한 줄 형식. uvicorn access 로그 끔. 본문을 찍는 라이브러리 로거(`aiosqlite` · `sqlalchemy` · `httpx` · `httpcore` · `anthropic` · `claude_agent_sdk` · `sse_starlette` · `mcp`)는 WARNING 이상만 |
| `RequestContextMiddleware` | pure ASGI — `x-request-id` 수신(형식 `[A-Za-z0-9._:-]{1,128}`, 아니면 uuid hex 생성) · 응답 헤더 · contextvar · 요청 완료 로그 1줄 (`method` · `path` · `status` · `duration_ms`) |
| `current_request_id()` · `request_context` | contextvar 접근 |
| `register_exception_handlers(app, *, expose_internal_errors)` | `AppError` · `HTTPException` · `RequestValidationError` → `ErrorResponse` (기타 예외는 최후 수단) |
| `UnhandledErrorMiddleware` | 기타 예외 → 500 `ErrorResponse` 를 CORS · request-id 미들웨어 **안쪽**에서 만든다 (첫 번째로 `add_middleware`). 응답이 이미 시작됐으면(SSE 도중) 다시 raise |
| `AppError(status, code, client_message, system_message=None, data=None)` · `ErrorCode` · `ErrorResponse` | 비즈니스 에러 · 기본 코드 · 에러 모델 |
| `StandardResponse[T]` · `ok(data, status_code=200)` | 성공 래퍼 (`spendTime` = 요청 시작부터) |
| `PageQuery` · `page_query` (Depends) · `Page[T]` · `Page.build(items, total, query)` | 목록 |
| `Base` · `IdMixin` · `TimestampMixin` · `UTCDateTime` · `utcnow` · `Database(url)` | SQLAlchemy 2 async — 이름 규칙 고정 metadata · uuid hex id · UTC aware 시각 · engine(`hide_parameters` — 오류 · 로그에 바인드 값 없음) / sessionmaker / `ping` / `dispose` |
| `mount_docs(app, *, user, password, title)` | `/api` (Swagger) · `/api-json` · `/docs` (ReDoc) basic auth |

## 규칙 · 불변조건

- **R1** — `APP_ENV != local` 이고 `DOCS_PASSWORD == admin` → 설정 생성 실패. `production` 이고 `ALLOWED_ORIGINS` 가 비거나 `*` 포함 → 실패. 사유는 한 메시지에 `;` 로.
- **R2** — `UTCDateTime` 에 naive datetime 을 쓰면 `ValueError`. 읽을 때 tz 없는 값(SQLite)은 UTC 로 붙인다.
- **R3** — `log_level` 기본 = production `INFO`, 그 외 `DEBUG`. DEBUG 에서도 prompt · 출력 · SQL 값은 로그에 없다.
- **R4** — `page` 1 ~ 1,000,000 (offset 이 64-bit 정수 안), `limit` 1 ~ 100.

## 예외 케이스

| 케이스 | 동작 | 근거 |
| --- | --- | --- |
| `x-request-id` 에 공백 · 개행 | 무시하고 새 id | `test_http.py::test_request_id_is_echoed_only_when_safe` |
| 없는 경로 | 404 envelope, `path` 에 쿼리 포함 | `test_http.py::test_unknown_route_uses_the_error_envelope` |
| 처리 안 된 예외 | 500 envelope + `x-request-id` + CORS 헤더 | `test_http.py::test_unhandled_errors_keep_request_id_and_cors` |
| DEBUG 레벨 실행 | 로그에 prompt · 모델 출력 없음 | `test_http.py::test_debug_logs_never_carry_prompt_or_output` |

## 알려진 한계

- `ok()` 는 핸들러가 직접 호출한다 — 전역 래핑이 없어 빠뜨리면 원시 응답이 나간다.

## 의존

- 외부: `fastapi` · `pydantic-settings` · `sqlalchemy[asyncio]` · `aiosqlite`

## 근거

- `packages/fastapi-common/src/fastapi_common/`
