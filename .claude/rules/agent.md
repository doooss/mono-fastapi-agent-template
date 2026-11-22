# Agent runtime

`packages/agent-core` · 에이전트 spec(`apps/api/src/api/modules/agents/registry.py`) · 도구에 적용.
구조와 백엔드별 매핑 → [flows/agent-run.md](../../docs/specs/flows/agent-run.md).

## 불변조건 (세 백엔드 출력이 같은 이유)

1. **이벤트 계약 = `agent_core/events.py` 하나.** 백엔드는 네이티브 스트림을 `ctx.emit(AgentEvent)` 로 번역만 한다. 새 이벤트 타입이 필요하면 계약을 먼저 바꾸고 세 백엔드를 같은 커밋에서 맞춘다.
2. **도구 실행 = `RunContext.execute_tool` 하나.** 검증 · timeout · 결과 자르기 · tool.call / tool.result 이벤트가 여기서만 일어난다. 백엔드가 도구 핸들러를 직접 부르지 않는다.
3. **로그 · trace · 합계 · 최종 출력 = 이벤트에서만 계산** (`observe.py`, `Runner`). 백엔드가 알려주는 usage 합계 · 비용 · 결과 문자열을 쓰지 않는다.
4. **모델이 보는 것 = 같은 문자열.** system prompt = `context.system_prompt(spec)`, 도구 설명 = `ToolSpec.description`, 서브에이전트 = `delegate_to_<name>` 도구. 백엔드별 기본 prompt · 내장 도구 · 설정 파일은 끈다 (Agent SDK `tools=[]` · `setting_sources=[]` · 문자열 system prompt, Managed 는 `agent_toolset` 없음).

## 도구 추가

```python
class SearchInput(ToolInput):
    query: str = Field(description="...")


@tool()
async def search(args: SearchInput) -> str:
    """Search ... (설명 = 모델이 읽는 문서)."""
```

→ `AgentSpec(tools=(search,))`. 실패는 예외로 던지면 된다 — 모델에는 오류 결과로 간다. 결과는 문자열, 크기는 `ContextPolicy.tool_result_max_chars` 로 잘린다.

## 백엔드 추가

`Backend` 프로토콜(`name`, `run(ctx, prompt, state) -> BackendResult`) 구현 → `api/main.py` `build_backends`. 네이티브 이벤트 → `TurnStarted` · `TextDelta` · `TurnCompleted`(usage) · `Context*` 번역은 순수 함수 / 클래스로 떼어 `tests/test_backends.py` 에 실제 SDK 타입으로 테스트한다.

## Prompt

prompt · 도구 설명은 영어, 사용자 응답 언어는 prompt 로 지정한다. 테스트에서 prompt 문구 자체를 단언하지 않는다.
