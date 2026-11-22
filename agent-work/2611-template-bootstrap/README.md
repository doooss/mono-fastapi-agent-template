# 2611-template-bootstrap

- **상태**: 진행 중
- **시작**: 2026-11-21

## 목표

uv 모노레포 + 백엔드 무관 에이전트 런타임 + 커밋 단위 CI/CD + "현재 사양과 흐름을 남기는" 출고 게이트가 동작하는 상태.

## 배경

nestjs-template 의 작업 체계를 Python/FastAPI 에이전트 서비스에 그대로 쓰고, 에이전트 실행 방식(Messages API · Agent SDK · Managed Agents)을 바꿔도 출력이 같게 한다.
결정 → [ADR-0001](../../docs/adr/0001-uv-workspace-monorepo.md) · [ADR-0005](../../docs/adr/0005-backend-neutral-agent-events.md) · [ADR-0006](../../docs/adr/0006-subagent-as-delegate-tool.md).

## 작업

| id | 제목 | 상태 |
| --- | --- | --- |
| 261121_001_template-bootstrap | 모노레포 + 백엔드 무관 에이전트 런타임 + 출고 게이트 | done |

## 백로그

<!-- 아직 task 로 만들지 않은 메모. 착수 시 uv run poe task:new 2611-template-bootstrap <slug> -->

적대적 리뷰에서 이월한 항목 (사양 `## 알려진 한계` 와 대응). 착수 시 `uv run poe task:new misc <slug>`.

| 항목 | 사양 |
| --- | --- |
| Agent SDK transcript 영속화 — `ClaudeAgentOptions.session_store` 를 DB 에 연결하거나 `$HOME/.claude` 볼륨. 지금은 인스턴스 · 컨테이너 밖에서 `SESSION_STATE_LOST` | [agent-run](../../docs/specs/flows/agent-run.md#알려진-한계) |
| 실제 키로 세 백엔드 수동 스모크 — 같은 입력의 이벤트 타입 순서 비교, Managed 재시도 시 span 수 · 이벤트 순서 확인 | [agent-run](../../docs/specs/flows/agent-run.md#알려진-한계) |
| 인증 · 세션 소유권 · 요청 제한 | [agents](../../docs/specs/modules/agents.md#알려진-한계) |
| 재접속 가능한 실행 (백그라운드 + 이벤트 버스) | [ADR-0008](../../docs/adr/0008-run-bound-to-request.md) |

## 회고

<!-- 에픽 종료 시: 잘된 것 / 아쉬운 것 / 남은 사양 공백. 이후 archive/2611-template-bootstrap/ 로 이동 -->
