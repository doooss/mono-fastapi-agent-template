# ADR-0005 — 에이전트 = 백엔드 3종 + 이벤트 계약 하나 (프레임워크 없음)

- **Status**: Accepted
- **Date**: 2026-11-21
- **Refs**: 261121_001_template-bootstrap
- **Supersedes**: —

## Context

같은 에이전트를 세 방식으로 돌릴 수 있어야 한다 — Messages API(루프를 직접), Claude Agent SDK(루프 = 번들 CLI), Claude Managed Agents(루프 = Anthropic 서버).
셋은 스트림 모양 · usage 의미(턴별 / 누적, 서브에이전트 포함 여부) · 내장 도구 · 기본 prompt 가 다르다. 그대로 쓰면 context · 관측 · 루프 · 도구 출력이 백엔드마다 달라진다.

## Decision

- **이벤트 계약 하나**(`agent_core.events`): run / turn / text / tool / subagent / context 이벤트. 백엔드는 네이티브 스트림을 이 계약으로 **번역만** 한다.
- **공통 처리는 런타임 한 곳**: 도구 실행(검증 · timeout · 결과 자르기 · 이벤트) = `RunContext.execute_tool`, 이벤트 봉투 · 합계 · 최종 출력 = `Runner`, 로그 · OTel span = `Observer` (이벤트에서만 계산).
- **모델이 보는 것을 맞춘다**: 같은 system prompt 문자열 · 같은 도구 정의. Agent SDK 는 `tools=[]` · 문자열 system prompt · `setting_sources=[]`, Managed 는 `agent_toolset` 없이 custom tool 만.
- 루프 한도 = `LoopPolicy.max_turns` — Messages 는 루프 상한, SDK 는 `max_turns`, Managed 는 요청 수를 세어 `user.interrupt`.
- 에이전트 프레임워크(Strands · LangGraph · Pydantic AI)는 쓰지 않는다.

## Alternatives

| 대안 | 기각 이유 |
| --- | --- |
| Strands Agents 위에 구성 | Strands 는 자기 루프를 돈다 — 루프가 CLI(SDK) · 서버(Managed)에 있는 백엔드를 감쌀 수 없어 Messages 만 덮는다. 이벤트 모델이 하나 더 생긴다 |
| 백엔드별 출력 그대로 + 프론트에서 분기 | 관측 · 저장 · 클라이언트가 백엔드 수만큼 갈린다 |
| 백엔드가 알려주는 합계 사용 | SDK `ResultMessage.usage` 는 서브에이전트 제외, Managed 는 누적 스냅샷 — 의미가 다르다 |

## Consequences

- **긍정**: 클라이언트 · 저장 · trace 가 백엔드를 모른다. 백엔드 추가 = 번역기 하나.
- **부정**: 백엔드 고유 기능(SDK 내장 도구 · Managed 샌드박스 · 메모리 스토어)은 계약 밖이라 쓰려면 계약을 넓혀야 한다. Managed 텍스트는 요청 단위로 와 `text.delta` 조각이 크다.
- **후속**: 압축 임계값(`ContextPolicy.compact_at_tokens`)은 Messages 에만 적용된다 — SDK · Managed 는 자체 기준, 이벤트만 같다.
