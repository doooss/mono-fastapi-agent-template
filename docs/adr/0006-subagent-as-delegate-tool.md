# ADR-0006 — 서브에이전트 = 모든 백엔드에서 위임 도구

- **Status**: Accepted
- **Date**: 2026-11-21
- **Refs**: 261121_001_template-bootstrap
- **Supersedes**: —

## Context

Agent SDK 는 `AgentDefinition` + 내장 Task 도구로 서브에이전트를 돌리고, Managed Agents 는 multiagent 스레드가, Messages API 에는 개념이 없다.
기본 기능을 쓰면 부모 모델이 보는 위임 도구의 설명 · 입력 · 결과 형식이 백엔드마다 달라진다 — context 가 같지 않다.

## Decision

- `AgentSpec.subagents` 의 각 에이전트는 부모에게 **`delegate_to_<name>` 도구** 하나로 보인다 (입력 `{task}`, 설명 = 서브에이전트 `description` + 공통 안내, 결과 = 서브에이전트 마지막 턴 텍스트).
- 도구 핸들러가 **같은 백엔드로** 자식 실행을 돈다 (`RunContext._delegate`). 자식은 빈 context 에서 시작하고, 이벤트는 `agent` 경로(`main/researcher#<call_id>`)를 달고 같은 스트림에 흐른다.
- 이벤트는 `subagent.started` / `subagent.completed` (tool.call / tool.result 대신). 자식의 usage · 턴도 run 합계에 들어간다.

## Alternatives

| 대안 | 기각 이유 |
| --- | --- |
| SDK `AgentDefinition` (Task 도구) | 위임 도구 문구 · 결과 형식이 Claude Code 고유 — 세 백엔드의 부모 context 가 달라진다. 내장 Task 도구를 켜야 해서 `tools=[]` 와도 충돌 |
| Managed multiagent 스레드 | Managed 전용. 이벤트(`session.thread_*`)를 다른 백엔드에서 재현할 수 없다 |
| 서브에이전트 없음 | 조합(오케스트레이터 + 전문 에이전트)이 템플릿 목표 |

## Consequences

- **긍정**: 부모가 보는 도구 · 결과 · 이벤트 순서가 백엔드와 무관하다. 서브에이전트마다 모델 · 루프 한도를 따로 둔다.
- **부정**: SDK 에서는 위임마다 CLI 프로세스, Managed 에서는 위임마다 세션이 하나 더 생긴다 (지연 · 비용). 백엔드 고유의 병렬 서브에이전트 최적화는 쓰지 않는다.
- **후속**: 비용이 문제면 서브에이전트에 더 작은 모델(`SUBAGENT_MODEL`)을 둔다.
