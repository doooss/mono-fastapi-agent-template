---
entity: module
name: agents
code: [apps/api/src/api/modules/agents, apps/api/migrations]
updated: 2026-11-21
refs: 261121_001_template-bootstrap
---

# agents

> 에이전트 목록 · 실행(SSE) · 세션 / 실행 기록. 실행 내부와 이벤트 계약은 [flows/agent-run.md](../flows/agent-run.md).

## 표면 (API)

`Response` = 공통 성공 래퍼의 `data` ([공통 규약](../README.md#공통-규약)). 인증 없음 (템플릿).

| Method | Path | Request | Response (`data`) | Errors |
| --- | --- | --- | --- | --- |
| GET | `/v1/agents` | — | `AgentOut[]` (`name` · `description` · `model` · `tools` · `subagents`) | — |
| POST | `/v1/agents/{name}/runs` | `{input (1~20000자), session_id?, backend?: messages\|agent_sdk\|managed}` | **SSE** (래퍼 없음) — `AgentEvent` 스트림. 헤더 `x-session-id` · `x-run-id` | 404 `AGENT_NOT_FOUND` · `SESSION_NOT_FOUND` / 409 `SESSION_AGENT_MISMATCH` · `SESSION_BACKEND_MISMATCH` · `RUN_IN_PROGRESS` / 400 `BACKEND_NOT_AVAILABLE` · `BAD_REQUEST` |
| GET | `/v1/sessions/{session_id}/runs` | query `page`, `limit` | `Page[RunOut]` (최신순) | 404 `SESSION_NOT_FOUND` |
| GET | `/v1/runs/{run_id}` | — | `RunOut` | 404 `RUN_NOT_FOUND` |
| GET | `/v1/runs/{run_id}/events` | — | `RunEventOut[]` (`seq` · `type` · `agent` · `ts` · `payload`) — `text.delta` 제외, `seq` 순 | 404 `RUN_NOT_FOUND` |

`RunOut` = `id` · `session_id` · `status` (`running` · `completed` · `failed` · `cancelled`) · `prompt` · `output` · `stop_reason` · `error_code` · `turns` · `input_tokens` · `output_tokens` · `cache_read_tokens` · `cache_write_tokens` · `duration_ms` · `created_at` · `completed_at`.

## 흐름

1. `start` — `session_id` 가 있으면 확인(에이전트 · 백엔드 일치), 없으면 세션 생성(`title` = 입력 앞 50자, 백엔드 = 요청값 또는 `AGENT_BACKEND`). 백엔드가 이 앱에 없으면 400. 세션 커밋 후 `running` run 삽입.
2. 검증 오류는 스트림 시작 전 JSON 에러로 끝난다. 통과하면 SSE 시작 (`ping` 15초).
3. `stream` — `Runner.stream` 이벤트를 그대로 SSE 로 보내며 `text.delta` 외 이벤트를 모은다.
4. 끝나면(정상 · 실패 · 연결 끊김) 한 트랜잭션에서 run 요약 갱신 + 이벤트 기록. 연결이 끊겨도 기록은 취소되지 않는다 (shield).

## 규칙 · 불변조건

- **R1** — 세션은 처음 백엔드에 고정된다 (state 가 백엔드별). 다른 `backend` 를 주면 409, 생략하면 세션 백엔드.
- **R2** — 세션당 `running` run 은 하나 — DB 부분 유니크 인덱스 `uq_agent_runs_running_session` (인스턴스 무관).
- **R3** — `running` run 이 `RUN_TIMEOUT_SECONDS` × 2 보다 오래됐으면 죽은 프로세스가 남긴 것으로 보고, 다음 실행 요청 때 `failed` / `RUN_INTERRUPTED` 로 바꾼 뒤 새 run 을 만든다.
- **R4** — run 종료 상태: `run.completed` → `completed` (+ 요약 · usage), `run.failed` → `failed` (+ `error_code`), 종료 이벤트 없이 끊김 → `cancelled` (`stop_reason` `cancelled`). 종료 기록은 아직 `running` 인 run 에만 쓴다 — R3 으로 이미 정리된 run 을 덮어쓰지 않는다.
- **R5** — 세션 state(`agent_sessions.state`)는 실행 성공 시에만 갱신된다.

## 예외 케이스

| 케이스 | 동작 | 근거 |
| --- | --- | --- |
| 실행 중인 세션에 또 요청 | 409 `RUN_IN_PROGRESS` | `test_agent_runs.py::test_a_running_run_blocks_its_session_until_it_goes_stale` |
| 남겨진 `running` run (2 × timeout 경과) | 정리 후 200 | 같은 테스트 |
| 백엔드 실패 | SSE `run.failed`, run `failed` + `error_code`, 같은 세션 재시도 가능 | `test_backend_failure_streams_run_failed_and_marks_the_run` |
| 빈 `input` · 정의 안 된 필드 | 400 `BAD_REQUEST`, `systemMessage` = 위반 배열 | `test_request_errors_use_the_error_envelope` |
| 세션의 백엔드와 다른 `backend` | 409 `SESSION_BACKEND_MISMATCH` | `test_session_continues_on_its_own_backend` |

## 알려진 한계

- 인증 · 세션 소유권 없음 — `session_id` 를 아는 누구나 이어 쓰고 기록을 읽는다. 실서비스는 인증 의존성을 라우터에 추가.
- 실행 = 요청 수명 ([ADR-0008](../../adr/0008-run-bound-to-request.md)) — 재접속 · 다른 인스턴스에서 이어 보기 없음. 프로세스가 죽으면 run 은 R3 까지 `running`.
- 이벤트는 실행 끝에 한 번에 기록 — 실행 중 프로세스가 죽으면 그 run 의 이벤트는 없다.
- 요청 제한 · 입력 크기 외 비용 제한 없음.

## 의존

- 주입: `app.state.agent_service` (`AgentRunService`), `Runner`, `SqlSessionStore`
- 외부: Anthropic API (백엔드별), DB
- 에이전트 정의: `registry.py` `build_agents(settings)` — 예시 `assistant` (+ 서브에이전트 `researcher`), 도구 없음

## 근거

- `apps/api/src/api/modules/agents/{router,service,models,schemas,registry}.py`
- `apps/api/migrations/versions/0001_agent_sessions_runs_events.py`
- `apps/api/tests/test_agent_runs.py`
