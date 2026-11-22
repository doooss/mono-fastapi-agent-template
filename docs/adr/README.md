# ADR

결정 기록 — "왜 이렇게 했나". 규칙 → [.claude/rules/adr.md](../../.claude/rules/adr.md). 생성 = `uv run poe adr:new <slug> [제목]` 후 아래 표에 한 줄.

| # | 제목 | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-uv-workspace-monorepo.md) | uv workspace 모노레포 + poe 명령 + Node 작업 도구 공유 | Accepted | 2026-11-21 |
| [0002](0002-current-spec-ship-gate.md) | 현재 사양 중심 출고 게이트 | Accepted | 2026-11-21 |
| [0003](0003-release-version-file.md) | CI 기본 on · 릴리스 / 배포 opt-in · 버전 = `apps/*/VERSION` | Accepted | 2026-11-21 |
| [0004](0004-minimal-tests.md) | 테스트는 버그를 잡을 수 있을 때만 | Accepted | 2026-11-21 |
| [0005](0005-backend-neutral-agent-events.md) | 에이전트 = 백엔드 3종 + 이벤트 계약 하나 (프레임워크 없음) | Accepted | 2026-11-21 |
| [0006](0006-subagent-as-delegate-tool.md) | 서브에이전트 = 모든 백엔드에서 위임 도구 | Accepted | 2026-11-21 |
| [0007](0007-sqlalchemy-alembic.md) | DB = SQLAlchemy 2 async + Alembic, 기본 SQLite | Accepted | 2026-11-21 |
| [0008](0008-run-bound-to-request.md) | 실행 = 요청에 묶인 SSE + 이벤트 기록 | Accepted | 2026-11-21 |
