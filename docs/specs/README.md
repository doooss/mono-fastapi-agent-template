# 현재 사양 (Current Spec)

지금 코드가 하는 일 — 개체 단위. **현재만** 기록한다 (이력 = git · [agent-work](../../agent-work/README.md) · [ADR](../adr/README.md)).
규칙 → [.claude/rules/current-spec.md](../../.claude/rules/current-spec.md). 새 문서 = [_templates/](_templates/) 복사 후 아래 표에 등록.

## 인덱스

### modules (`apps/api/src/api/modules/*`)

| 개체 | 문서 | 코드 |
| --- | --- | --- |
| agents | [modules/agents.md](modules/agents.md) | `apps/api/src/api/modules/agents` · `apps/api/migrations` |
| health | [modules/health.md](modules/health.md) | `apps/api/src/api/modules/health` |

### packages

| 개체 | 문서 | 코드 |
| --- | --- | --- |
| agent-core | [packages/agent-core.md](packages/agent-core.md) | `packages/agent-core/src/agent_core` |
| fastapi-common | [packages/fastapi-common.md](packages/fastapi-common.md) | `packages/fastapi-common/src/fastapi_common` |

### flows

| 흐름 | 문서 |
| --- | --- |
| 에이전트 실행 — 이벤트 계약 · 백엔드 매핑 | [flows/agent-run.md](flows/agent-run.md) |

## 공통 규약

모든 모듈 문서의 `Response` 는 아래 성공 래퍼의 `data` 를 뜻한다 (SSE 제외). JSON 모양은 nestjs-template 과 같다. 근거: `api/main.py` `create_app`, [fastapi-common](packages/fastapi-common.md).

### 경로

- 모든 라우트 `/v1/<path>`.
- Swagger UI `/api` · OpenAPI `/api-json` · ReDoc `/docs` — basic auth (`DOCS_USER` / `DOCS_PASSWORD`). 배포 환경(dev · qa · production)은 기본 비밀번호(`admin`)로 부팅 불가.

### 성공 응답 — `ok(data)`

```json
{ "data": <핸들러 데이터>, "statusCode": 200, "statusMessage": "OK", "spendTime": "3ms" }
```

- `spendTime` = 요청이 미들웨어에 들어온 시점부터.
- SSE(`text/event-stream`) 는 감싸지 않는다.

### 에러 응답 — `register_exception_handlers`

```json
{
  "statusCode": 404, "statusMessage": "NOT_FOUND",
  "message": "<사용자 메시지>", "systemMessage": "<내부 메시지>",
  "code": "NOT_FOUND", "data": null,
  "path": "/v1/nope?x=1", "timestamp": "2026-11-21T05:19:54.562Z"
}
```

| 예외 | status | code | message |
| --- | --- | --- | --- |
| `AppError` | 지정값 | 지정 code (`AGENT_NOT_FOUND` 등 앱 코드 포함) | `client_message` |
| 요청 검증 실패 (`RequestValidationError`) | 400 | `BAD_REQUEST` | 위반 목록 `, ` join. `systemMessage` = **배열** (`"body.input: String should have at least 1 character"`) |
| `HTTPException` 400 / 401 / 403 / 404 / 429 | 그대로 | `BAD_REQUEST` / `UNAUTHORIZED` / `FORBIDDEN` / `NOT_FOUND` / `TOO_MANY_REQUESTS` | `detail` (문자열 아니면 `오류가 발생했습니다.`) |
| 그 외 `HTTPException` (405 등) | 그대로 | `INTERNAL_SERVER_ERROR` | 같음 |
| 기타 예외 | 500 | `INTERNAL_SERVER_ERROR` | `서버 내부 오류가 발생했습니다.` (`systemMessage` = 원본 메시지). `x-request-id` · CORS 헤더 포함 |

- production 은 모든 5xx 의 `systemMessage` 를 `Internal Server Error` 로 가린다. 원본은 로그에만.
- 로그: 5xx = error + traceback, 4xx = warning. 경로는 쿼리 제외. 요청 검증 실패는 FastAPI 기본 422 가 아니라 400.

### 요청 공통

- `x-request-id` — 클라이언트 값이 `[A-Za-z0-9._:-]{1,128}` 이면 그대로, 아니면 uuid hex. 모든 응답 헤더(CORS preflight 포함)와 그 요청의 모든 로그 줄에 붙는다.
- 목록 = `?page=1&limit=10` → `data: { items, pagination: { total, page, limit, totalPages, isLast } }`. `page` 1 ~ 1,000,000, `limit` 1~100 — 벗어나면 400.
- CORS — `ALLOWED_ORIGINS` (comma list), `credentials: true`. 요청 헤더 `x-request-id` · `traceparent` 허용, 응답 헤더 `x-request-id` · `x-session-id` · `x-run-id` 노출. production 은 명시 필수, `*` 불가.
- 인증 · 요청 제한 없음 (템플릿) — 서비스에서 라우터 의존성으로 추가.
