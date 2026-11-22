---
id: 261121_001_template-bootstrap
date: 2026-11-21
task: template-bootstrap
epic: 2611-template-bootstrap
status: done
started-at: 2026-11-21
completed-at: 2026-11-22
related-code: [apps/api, packages/agent-core, packages/fastapi-common, .github, scripts/agent-work.mjs, .claude, docs, agent-work, docker]
spec:
  - docs/specs/flows/agent-run.md
  - docs/specs/modules/agents.md
  - docs/specs/modules/health.md
  - docs/specs/packages/agent-core.md
  - docs/specs/packages/fastapi-common.md
adr: [0001, 0002, 0003, 0004, 0005, 0006, 0007, 0008]
review: passed (2026-11-22, rounds 3)
acceptance:
  - uv workspace 모노레포 (apps/api, packages/agent-core, packages/fastapi-common), FastAPI + pydantic 2 + SQLAlchemy 2 async + Alembic
  - 에이전트 백엔드 3종 (Messages API · Claude Agent SDK · Claude Managed Agents) 이 같은 AgentSpec 으로 돌고 같은 이벤트 계약을 낸다
  - context · 관측 · 루프 · 도구 처리가 백엔드와 무관 (같은 system prompt / 도구 정의 / 결과 자르기, 이벤트에서만 로그 · trace · 합계, max_turns · timeout, 실행기 하나)
  - 내장 도구는 전 백엔드에서 꺼져 있고, 템플릿은 도구를 싣지 않는다 (도구 등록 방법만 제공)
  - 서브에이전트 조합 (부모 → 위임 → 자식 이벤트가 같은 스트림)
  - nestjs-template 과 같은 작업 체계 — task:new · task:status · adr:new · ship:check · 커밋 감사 CI · 릴리스 / 배포 opt-in
  - 응답 / 에러 envelope 이 nestjs-template 과 같은 JSON
  - check-types · lint · test · test:e2e · CI 스크립트 테스트 green
links: []
---

# 모노레포 + 백엔드 무관 에이전트 런타임 + 출고 게이트

## 최종 사양

- 구조: uv workspace (Python 3.14) — `apps/api` (FastAPI · SSE · SQLAlchemy 2 async · Alembic) + `packages/agent-core` (FastAPI · DB 모름) + `packages/fastapi-common`. 명령 = `uv run poe <task>` (nestjs-template 과 같은 이름), task · ADR · ship:check · 커밋 감사 = nestjs-template 의 무의존 Node 스크립트 (언어별 경로 판정 · release 버전 파일만 조정) → [ADR-0001](../../../docs/adr/0001-uv-workspace-monorepo.md).
- 에이전트: `AgentSpec` 하나를 `messages` · `agent_sdk` · `managed` 중 무엇으로 돌려도 같은 이벤트 계약(run / turn / text / tool / subagent / context). 도구 실행 · 합계 · 출력 · 로그 · OTel span 은 런타임 한 곳, 백엔드는 번역만. 내장 도구 · 기본 prompt · 설정 파일은 끔 (SDK `tools=[]` · 문자열 system prompt · `setting_sources=[]` · `strict_mcp_config` · `verbatim_prompts`). 서브에이전트 = `delegate_to_<name>` 도구 (`agent` = `main/<name>#<call_id>`) → [agent-run](../../../docs/specs/flows/agent-run.md) · [ADR-0005](../../../docs/adr/0005-backend-neutral-agent-events.md) · [ADR-0006](../../../docs/adr/0006-subagent-as-delegate-tool.md).
- 루프: `max_turns` (Messages 루프 상한 · SDK 옵션 · Managed interrupt) · 실행 timeout(`RUN_TIMEOUT_SECONDS`) · 병렬 도구 중 run 실패 시 형제 취소 · 끊김 시 백엔드 정리 대기(최대 30초).
- API: `GET /v1/agents` · `POST /v1/agents/{name}/runs` (SSE) · `GET /v1/sessions/{id}/runs` · `GET /v1/runs/{id}` · `GET /v1/runs/{id}/events` (리플레이). 세션은 첫 백엔드에 고정, 세션당 running 하나(부분 유니크 인덱스), 2×timeout 넘은 running 은 정리 → [agents](../../../docs/specs/modules/agents.md) · [ADR-0008](../../../docs/adr/0008-run-bound-to-request.md).
- 공통: nestjs-template 과 같은 성공 / 에러 envelope, `x-request-id` (처리 안 된 500 포함), docs basic auth, 배포 환경 env 가드, prompt · 출력 · SQL 값이 없는 로그 → [공통 규약](../../../docs/specs/README.md#공통-규약) · [fastapi-common](../../../docs/specs/packages/fastapi-common.md).
- 배포: 이미지 = `uv sync --locked --no-dev --package api`, venv 최종 경로 고정, `PORT` · `APP_DIR`, SQLite + 기동 시 마이그레이션. release 버전 = `apps/*/VERSION` → [ADR-0003](../../../docs/adr/0003-release-version-file.md) · [ADR-0007](../../../docs/adr/0007-sqlalchemy-alembic.md).

## 예외 케이스

적대적 리뷰 3 round (1: 런타임 · 앱/인프라 2명 병렬 18건, 2: 수정 검증 + 신규 7건, 3: 2라운드 수정분 3건). blocking 6건 전부 수용.

| # | 케이스 | 판정 | 처리 · 근거 |
| --- | --- | --- | --- |
| 1 | SDK 입력의 `@/경로` 가 서버 파일을 읽고 `/명령` 실행 (blocking) | 수용 | `verbatim_prompts` · `strict_mcp_config` |
| 2 | SDK `success` + `is_error`(429 · 5xx · 401) 를 `end_turn` 처리 (blocking) | 수용 | `result_stop_reason` → `UPSTREAM_*`, `test_sdk_api_failures_reported_as_success_fail_the_run` |
| 3 | 이미지 venv 경로 이동으로 `uvicorn` shebang 깨짐 (blocking) | 수용 | `UV_PROJECT_ENVIRONMENT=/app/.venv` (이미지 빌드는 데몬 없어 미실행, 레이아웃은 리뷰어가 재현) |
| 4 | `poe lint` 가 README python 블록에서 실패 (blocking) | 수용 | ruff `*.md` 제외 |
| 5 | DEBUG 로그 · SQL 예외 문자열로 prompt · 출력 누출 (blocking) | 수용 | `QUIET_LOGGERS` · `hide_parameters`, `test_debug_logs_never_carry_prompt_or_output` (수정 전 실패 확인) |
| 6 | 클라이언트 끊김 시 anyio 반복 취소가 백엔드 정리를 끊어 CLI 잔존 (blocking) | 수용 | shield + `asyncio.wait`, `test_closing_the_stream_under_anyio_lets_backend_cleanup_finish` (수정 전 실패 확인) |
| 7 | SDK handler 가 자식 실패를 도구 오류로 삼킴 · 내부 예외 문구가 모델로 | 수용 | `fatal` → run 실패, 안전 문구만 반환 |
| 8 | 같은 서브에이전트 병렬 위임 시 `agent` 경로 · span 충돌 | 수용 | `#call_id`, `test_parallel_delegations_to_one_subagent_get_distinct_agent_paths` |
| 9 | 병렬 도구 하나 실패 후 형제 계속 실행 · Managed 실패 task 예외 유실 | 수용 | `gather_all` · `_settle` · finally cancel, `test_gather_all_cancels_siblings_when_one_fails` |
| 10 | SDK 만 한 턴 도구를 순차 실행 | 수용 | `readOnlyHint` (리뷰어가 실제 CLI 로 동시 실행 확인) |
| 11 | 도구 입력 판정이 백엔드마다 다름 (`"5"` · 중첩 모델 · `5.0`) | 수용 | strict JSON + 정수 float 정규화, `test_tool_input_is_strict_json_like_the_agent_sdk_schema_check` |
| 12 | 재배포 후 SDK 세션 영구 실패 · 일시 실패를 LOST 로 오분류 | 수용 / 이월 | 로컬 transcript 사전 확인 → `SESSION_STATE_LOST`, `test_sdk_session_without_a_local_transcript_fails_before_starting_the_cli`. 영속화는 백로그 |
| 13 | 처리 안 된 500 에 `x-request-id` · CORS 없음 | 수용 | `UnhandledErrorMiddleware`, `test_unhandled_errors_keep_request_id_and_cors` |
| 14 | 프로세스가 죽으면 running run 이 세션을 영구 차단 | 수용 | `RUN_TIMEOUT_SECONDS` + 2× 정리, `test_a_running_run_blocks_its_session_until_it_goes_stale` |
| 15 | `load_state` 중 끊김 → SQLite 잠금 · `_finish` 가 정리된 run 덮어씀 | 수용 | store 호출 shield, `_finish` 는 `status='running'` 만 |
| 16 | R5 "실패 시 마지막 성공 state" 가 SDK · Managed 에선 거짓 | 수용 | 사양 정정 (원격 transcript 는 되돌릴 수 없음) |
| 17 | `agent` 경로 `String(200)` 초과 · `page` 무제한 500 · `PORT` 미사용 · env 문서 누락 · 얕은 복사로 저장 state 변경 | 수용 | `Text` · `le=1_000_000` · `${PORT:-3000}` · `.env.example` · deepcopy |
| 18 | save_state 중 끊김 → run `cancelled` 인데 state 저장 · 위임 중 끊김 정리 30초 초과 시 CLI 잠시 잔존 | 이월 | ms 창 / 드묾 — [agent-run 알려진 한계](../../../docs/specs/flows/agent-run.md#알려진-한계) |

## 결정

[ADR-0001](../../../docs/adr/0001-uv-workspace-monorepo.md) uv workspace + poe + Node 작업 도구 공유 · [0002](../../../docs/adr/0002-current-spec-ship-gate.md) 현재 사양 출고 게이트 · [0003](../../../docs/adr/0003-release-version-file.md) 버전 = `apps/*/VERSION` · [0004](../../../docs/adr/0004-minimal-tests.md) 최소 테스트 · [0005](../../../docs/adr/0005-backend-neutral-agent-events.md) 백엔드 3종 + 이벤트 계약 (Strands 기각) · [0006](../../../docs/adr/0006-subagent-as-delegate-tool.md) 서브에이전트 = 위임 도구 · [0007](../../../docs/adr/0007-sqlalchemy-alembic.md) SQLAlchemy + Alembic · [0008](../../../docs/adr/0008-run-bound-to-request.md) 실행 = 요청 수명.

## 검증

- `uv run poe check-types` ✅ mypy strict 39 files · `uv run poe lint` ✅ ruff check + format
- `uv run poe test` ✅ 17 passed · `uv run poe test:e2e` ✅ 11 passed (실제 SQLite + Alembic + SSE)
- `node --test ".github/scripts/*.test.mjs" "scripts/*.test.mjs"` ✅ 100 passed
- `alembic upgrade head` → `alembic check` (드리프트 없음) → `downgrade base` ✅
- 미실행: 실제 API 키 백엔드 스모크 (키 없음 — 백로그) · `docker build` (데몬 없음)
