# mono-fastapi-agent-template

FastAPI 에이전트 백엔드 모노레포 템플릿. uv workspace + Python 3.14 + SQLAlchemy 2 (async, 기본 SQLite) + Alembic + pydantic 2.
에이전트 런타임 하나를 세 백엔드(Messages API · Claude Agent SDK · Claude Managed Agents)로 돌리고, 출력은 같은 이벤트 계약 하나로 낸다.

- `apps/api` — REST + SSE, port 3000, `/v1/*` (Swagger `/api`, ReDoc `/docs`)
- `packages/agent-core` — 백엔드 무관 에이전트 런타임 (이벤트 · spec · 도구 · 관측 · 백엔드 3종)
- `packages/fastapi-common` — 공유 인프라 (settings · 로그 · request id · 응답 / 에러 envelope · DB · 문서)

**작업 원칙 = 현재 사양과 흐름을 남긴다.** task(`agent-work/`) → 출고 게이트(적대적 리뷰 필수) → 현재 사양(`docs/specs/`) + 결정(`docs/adr/`) → 한 커밋. CI 가 커밋마다 검사한다.

규칙 본문 → [.claude/rules/](.claude/rules/). 트리거에 맞는 파일만 읽는다.

## Rules

| 영역 | 파일 | Trigger |
| --- | --- | --- |
| Task + 출고 게이트 | [agent-work.md](.claude/rules/agent-work.md) | 작업 시작 / 완료 |
| 적대적 리뷰 | [adversarial-review.md](.claude/rules/adversarial-review.md) | 출고 게이트 2 |
| 현재 사양 | [current-spec.md](.claude/rules/current-spec.md) | API / 동작 변경 |
| ADR | [adr.md](.claude/rules/adr.md) | 결정이 있을 때 |
| Commit & PR | [commit-pr.md](.claude/rules/commit-pr.md) | 커밋 / PR |
| Code style | [code-style.md](.claude/rules/code-style.md) | 코드 변경 |
| FastAPI | [fastapi.md](.claude/rules/fastapi.md) | `apps/api` 코드 · DB |
| Agent | [agent.md](.claude/rules/agent.md) | `packages/agent-core` · 에이전트 spec · 도구 |
| Monorepo | [monorepo.md](.claude/rules/monorepo.md) | 패키지 간 수정 / 새 앱 · 패키지 / 의존성 |
| Testing | [testing.md](.claude/rules/testing.md) | 테스트 작성 · 수정 |
| Security | [security.md](.claude/rules/security.md) | env / 로그 / 인증 |

## Skills / Agents

| 이름 | 용도 |
| --- | --- |
| [/ship-task](.claude/skills/ship-task/SKILL.md) | 출고 게이트 6단계 실행 (구현 끝났을 때) |
| [adversarial-reviewer](.claude/agents/adversarial-reviewer.md) | 적대적 리뷰 서브에이전트 (ship-task 가 호출) |

## Paths

| 경로 | 역할 |
| --- | --- |
| [agent-work/](agent-work/README.md) | task 추적 (에픽 / misc / manual-task / archive) |
| [docs/specs/](docs/specs/README.md) | **현재 사양** — modules / packages / flows + 공통 응답 · 에러 규약 |
| [docs/specs/flows/agent-run.md](docs/specs/flows/agent-run.md) | 이벤트 계약 + 백엔드별 매핑 (세 백엔드 출력이 같은 이유) |
| [docs/adr/](docs/adr/README.md) | 결정 기록 |
| [docs/ci-cd.md](docs/ci-cd.md) | CI(커밋 감사) · 릴리스 · Docker 배포 (opt-in) |

## Commands

```bash
uv sync                                  # 전체 워크스페이스 설치 (Python 3.14, .python-version)
uv run poe dev:api                       # http://localhost:3000/v1
uv run poe check-types && uv run poe lint && uv run poe test && uv run poe test:e2e
uv run poe db:upgrade                    # 마이그레이션 적용 · db:revision "<msg>" 새 리비전
uv run poe task:status                   # 세션 시작 스캔
uv run poe task:new <epic|misc> <slug>   # task 생성
uv run poe adr:new <slug> [제목]          # ADR 생성
uv run poe ship:check                    # 출고 게이트 검증 (커밋 전)
```

task · ADR · ship:check 도구는 Node(≥22) 스크립트다 (CI 와 같은 검증기, [ADR-0001](docs/adr/0001-uv-workspace-monorepo.md)).

## Session start

1. `uv run poe task:status` — 열린 task / manual-task 확인.
2. 작업 = task 파일부터 (`uv run poe task:new`). 영향 개체의 현재 사양(`docs/specs/`)을 먼저 읽는다.
3. 구현 완료 → `/ship-task`. 커밋 · 푸시는 사용자 요청 시에만.
