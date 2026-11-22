# mono-fastapi-agent-template

FastAPI 에이전트 백엔드 모노레포 템플릿. uv workspace · Python 3.14 · SQLAlchemy 2 + Alembic · pydantic 2 · 커밋 단위 CI · 현재 사양 중심 작업 기록 (nestjs-template 과 같은 체계).

에이전트 하나를 **세 백엔드 중 무엇으로 돌려도 같은 출력**을 낸다:

| 백엔드 | 루프가 도는 곳 | `AGENT_BACKEND` |
| --- | --- | --- |
| Messages API | 이 프로세스 | `messages` |
| Claude Agent SDK | 번들 Claude Code CLI (내장 도구 · 설정 끔) | `agent_sdk` |
| Claude Managed Agents | Anthropic 서버 세션 | `managed` |

context(같은 system prompt · 도구 정의 · 결과 자르기) · 관측(이벤트에서 만든 로그 · OTel span · 합계) · 루프(`max_turns` · 실행 timeout) · 도구(실행기 하나) 가 백엔드와 무관하다 → [flows/agent-run.md](docs/specs/flows/agent-run.md).

## 시작

요구: [uv](https://docs.astral.sh/uv/) (Python 3.14 은 uv 가 설치), 작업 도구용 Node ≥22.

```bash
uv sync
cp apps/api/.env.example apps/api/.env.local     # ANTHROPIC_API_KEY 채우기
uv run poe dev:api                               # 기동 시 SQLite 마이그레이션 자동 적용
```

| 주소 | 내용 |
| --- | --- |
| http://localhost:3000/v1/health | 헬스체크 (DB ping) |
| http://localhost:3000/v1/agents | 에이전트 목록 |
| http://localhost:3000/api · `/docs` | Swagger · ReDoc (basic auth `DOCS_USER` / `DOCS_PASSWORD`) |

```bash
curl -N http://localhost:3000/v1/agents/assistant/runs \
  -H 'content-type: application/json' \
  -d '{"input": "안녕", "backend": "messages"}'
# event: run.started / turn.started / text.delta … / run.completed (SSE)
# 응답 헤더 x-session-id 를 다음 요청 body 의 session_id 로 → 대화 이어짐
```

## 구조

```
apps/api/                    FastAPI 앱 — src/api/{main,settings}.py · modules/{agents,health} · migrations/ · tests/
packages/agent-core/         agent_core — 이벤트 계약 · Runner · 도구 · 관측 · backends/{messages,agent_sdk,managed} · testing
packages/fastapi-common/     fastapi_common — settings · 로그 · request id · 응답 / 에러 envelope · DB · 문서
docker/api.Dockerfile        (선택) 배포 이미지
docs/specs/                  현재 사양 (모듈 · 패키지 · 흐름 · 공통 규약)
docs/adr/                    결정 기록
agent-work/                  task 추적 + 출고 게이트
.github/                     CI · PR 자동화 · 릴리스 · 배포
.claude/                     에이전트 규칙 · 스킬 · 서브에이전트 (CLAUDE.md 가 인덱스)
```

## 명령 (`uv run poe <task>`)

| 명령 | 역할 |
| --- | --- |
| `dev:api` · `start:api` | 개발 서버 (reload) · production 실행 |
| `check-types` · `lint` · `test` · `test:e2e` | 검사 (CI 동일) — mypy strict · ruff · unit · HTTP + SQLite |
| `lint:fix` · `format` | 자동 수정 |
| `db:upgrade` · `db:revision "<msg>"` | 마이그레이션 적용 · 모델에서 새 리비전 |
| `docker:build` | 로컬 이미지 (`api:local`) |
| `task:status` · `task:new <epic\|misc> <slug>` | task 조회 · 생성 |
| `adr:new <slug>` · `ship:check` | ADR 생성 · 출고 게이트 검증 |

## 에이전트 만들기

에이전트 = `AgentSpec` ([registry.py](apps/api/src/api/modules/agents/registry.py)). 템플릿은 도구를 싣지 않는다.

```python
class LookupInput(ToolInput):
    order_id: str = Field(description="Order id, e.g. ORD-123")

@tool()
async def lookup_order(args: LookupInput) -> str:
    """Look up an order's status."""
    return await orders.status(args.order_id)

support = AgentSpec(
    name="support",
    description="Answers order questions.",
    model=settings.AGENT_MODEL,
    instructions=(ROLE, STYLE),
    tools=(lookup_order,),
    subagents=(researcher,),          # 부모에게 delegate_to_researcher 도구로 보인다
    loop=LoopPolicy(max_turns=15),
    context=ContextPolicy(tool_result_max_chars=10_000),
)
```

규칙 → [.claude/rules/agent.md](.claude/rules/agent.md). 결정 → [ADR-0005](docs/adr/0005-backend-neutral-agent-events.md) · [ADR-0006](docs/adr/0006-subagent-as-delegate-tool.md).

## 작업 방식 — 현재 사양과 흐름을 남긴다

```
task 생성 → 구현 → [출고 게이트] → 한 커밋 (코드 + task + 사양 + ADR)
              1 로컬 검증
              2 적대적 리뷰 (필수 · 새 컨텍스트 리뷰어)
              3 작업 기록 압축 (최종 사양 · 예외 케이스 · 결정 · 검증)
              4 ADR (또는 none — 사유)
              5 현재 사양 덮어쓰기 (docs/specs)
```

상세: [agent-work](agent-work/README.md) · [사양 규칙](.claude/rules/current-spec.md) · [ADR-0002](docs/adr/0002-current-spec-ship-gate.md).

## 커밋 / CI

Conventional Commits + footer (`Refs:` task id · `Spec:` 사양 경로 | pending | none · `ADR:` 번호 | none). CI 가 커밋마다 감사한다. 릴리스 태깅 · Docker 배포는 저장소 변수로 켜는 선택 기능 → [docs/ci-cd.md](docs/ci-cd.md).

## 환경 변수

`apps/api/.env.example` 참고. production 은 `ALLOWED_ORIGINS` 명시(`*` 불가), 배포 환경은 `DOCS_PASSWORD` 기본값 교체 필수 — 아니면 부팅 실패. `ANTHROPIC_API_KEY` 는 `.env.<APP_ENV>` 에서 읽어 세 백엔드에 넘긴다.
