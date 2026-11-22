---
entity: package
name: agent-core
code: [packages/agent-core/src/agent_core]
updated: 2026-11-21
refs: 261121_001_template-bootstrap
---

# agent-core (`agent_core`)

> 백엔드 무관 에이전트 런타임. FastAPI · DB 를 모른다. 이벤트 계약 · 백엔드 매핑은 [flows/agent-run.md](../flows/agent-run.md).

## 표면 (공개 API)

| 이름 | 종류 | 설명 |
| --- | --- | --- |
| `AgentSpec(name, description, model, instructions, tools=(), subagents=(), loop, context)` | dataclass | 에이전트 정의. `name` = `^[a-z][a-z0-9_]{0,41}$` (`delegate_to_<name>` 이 도구 이름 한도 안), 도구 · 위임 도구 이름 중복 금지 |
| `LoopPolicy(max_turns=20, max_tokens=8192, tool_timeout_s=60)` | dataclass | 에이전트 실행 1회의 모델 요청 수 · 요청당 출력 토큰(Messages) · 도구 timeout |
| `ContextPolicy(tool_result_max_chars=20000, compact_at_tokens=150000, clear_tool_uses_at_tokens=None, keep_tool_uses=3)` | dataclass | 결과 자르기(전 백엔드) · 압축 / 결과 지우기(Messages). `compact_at_tokens` ≥ 50000 |
| `@tool(name=None, description=None, timeout_s=None)` | decorator | `async def f(args: <BaseModel>) -> str` → `ToolSpec`. 설명 = docstring (없으면 TypeError) |
| `ToolInput` | BaseModel | 도구 입력 베이스 (`extra="forbid"`, `strict=True`). 검증 = strict JSON 모드, 중첩 모델 포함 |
| `ToolSpec` | dataclass | `name` (`^[a-zA-Z0-9_-]{1,54}$` — API 64자 − SDK `mcp__app__`) · `description` · `input_model` · `handler` · `timeout_s` · `kind` (`tool` \| `subagent`) |
| `Runner(backends, store, *, run_timeout_s=None)` | class | `stream(spec=, prompt=, backend=, session_id=, run_id=None) -> AsyncIterator[AgentEvent]`. iterator 를 닫으면 실행 취소 |
| `RunContext` | class | 백엔드가 받는 실행 문맥: `spec` · `tools` (위임 도구 포함) · `emit(event)` · `execute_tool(call_id, name, input) -> ToolOutcome` · `output` |
| `Backend` | Protocol | `name` · `run(ctx, prompt, state) -> BackendResult(stop_reason, state)` |
| `agent_core.runtime.gather_all(*coros)` | function | 하나가 실패하면 나머지를 취소하는 gather (병렬 도구용, `BackendError` 우선 전파) |
| `BackendError(code, message)` | Exception | 클라이언트에 그대로 가는 실패 (`message` = 안내 문구) |
| `SessionStore` · `InMemorySessionStore` | Protocol · class | `load_state` / `save_state` (백엔드별 JSON) |
| 이벤트 · `Usage` · `StopReason` · `TERMINAL_EVENTS` | pydantic | `events.py` — [이벤트 계약](../flows/agent-run.md#이벤트-계약-agent_coreeventspy) |
| `agent_core.backends.{MessagesBackend, AgentSdkBackend, ManagedBackend}` | class | 백엔드 3종 (vendor SDK 는 여기서만 import) |
| `agent_core.testing.{ScriptedBackend, ScriptedTurn}` | class | 모델 호출 없는 테스트 백엔드 — 같은 `RunContext` 경로 |

생성자:

- `MessagesBackend(client: AsyncAnthropic)`
- `AgentSdkBackend(*, api_key: str | None, workdir: Path)` — `api_key` 는 CLI 환경 변수로만 전달
- `ManagedBackend(client: AsyncAnthropic, *, environment_name: str)`

## 흐름

- `Runner.stream` → `run.started` → `store.load_state` → `backend.run` (timeout 안) → `store.save_state` → `run.completed` (합계 = Observer). 예외 → `run.failed` (`BackendError` code | `RUN_TIMEOUT` | `AGENT_RUN_FAILED`). store 호출은 shield — 취소가 DB 쿼리 중간을 끊지 않는다. 소비자가 iterator 를 닫으면 실행 task 를 한 번 취소하고 정리를 최대 30초 기다린다 (shield).
- `ManagedBackend` 는 처음 쓸 때 환경(`environment_name`, cloud · networking limited)과 에이전트를 찾거나 만든다. 에이전트 = `name` + metadata `template_hash` (정의의 sha256 앞 16자) — spec 이 바뀌면 새 에이전트를 만든다. 프로세스 안에서 캐시.

## 규칙 · 불변조건

- **R1** — 패키지는 FastAPI · SQLAlchemy 를 import 하지 않는다.
- **R2** — `execute_tool` 은 예외를 던지지 않는다 (`BackendError` 제외 — 자식 실행 실패 포함) — 그 밖의 실패는 `ToolOutcome(is_error=True)`.
- **R3** — 위임 도구 이름 = `delegate_to_<subagent name>`, 입력 = `{task: str (1자 이상)}`, timeout 없음 (자식 루프 한도 · run timeout 으로 제한). 자식 `agent` = `child_agent_path(parent, name, call_id)`.
- **R4** — `Observer` 로그는 `TextDelta` 를 남기지 않고, 이벤트별 메타 필드만 (`log_fields`). `is_error` 이벤트 = WARNING, `run.failed` = ERROR.

## 예외 케이스

[flows/agent-run.md](../flows/agent-run.md#예외-케이스) 참조.

## 알려진 한계

- Managed 에이전트 · 환경은 지우지 않는다 (spec 이 바뀔 때마다 에이전트가 늘어난다 — 콘솔 / API 로 archive).
- `MessagesBackend` 는 서버 도구(웹 검색 등) · extended thinking 설정을 노출하지 않는다.
- Claude Platform on AWS 등 다른 클라이언트는 `AsyncAnthropic` 대신 해당 클라이언트를 `MessagesBackend` · `ManagedBackend` 에 넘긴다 (Managed 지원 여부는 플랫폼에 따름).

## 의존

- 외부: `anthropic` · `claude-agent-sdk` (번들 CLI, 플랫폼별 휠) · `pydantic` · `opentelemetry-api`

## 근거

- `packages/agent-core/src/agent_core/` · `packages/agent-core/tests/`
