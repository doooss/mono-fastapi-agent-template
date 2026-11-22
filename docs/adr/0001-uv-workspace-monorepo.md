# ADR-0001 — uv workspace 모노레포 + poe 명령 + Node 작업 도구 공유

- **Status**: Accepted
- **Date**: 2026-11-21
- **Refs**: 261121_001_template-bootstrap
- **Supersedes**: —

## Context

에이전트 백엔드는 앱(HTTP)과 런타임(에이전트 루프)이 따로 자란다 — worker · 배치가 같은 런타임을 쓸 수 있어야 한다.
작업 체계(task · 출고 게이트 · 커밋 감사)는 nestjs-template 과 같아야 하고, 두 템플릿을 오가는 사람이 같은 명령 이름을 쓰는 게 낫다.

## Decision

- **uv workspace** — `apps/api` + `packages/agent-core` (FastAPI · DB 모름) + `packages/fastapi-common`. lock = 루트 `uv.lock` 하나, 멤버는 editable.
- **명령 = poethepoet** (`[tool.poe.tasks]`), 이름은 nestjs-template 의 pnpm 스크립트와 같다 (`check-types` · `lint` · `test` · `test:e2e` · `task:new` · `ship:check` …). 실행 = `uv run poe <task>`.
- **task · ADR · ship:check · 커밋 감사 도구 = nestjs-template 의 무의존 Node 스크립트를 그대로 쓴다** (`scripts/agent-work.mjs`, `.github/scripts/*.mjs`). 바꾼 곳은 언어별 경로 판정(`isDeployPath` · `isTestPath`)과 release 버전 파일뿐 ([0003](0003-release-version-file.md)).

## Alternatives

| 대안 | 기각 이유 |
| --- | --- |
| 단일 패키지 | 런타임을 다른 앱(worker)에서 쓰려면 복사 |
| 작업 도구를 Python 으로 이식 | CI 감사(`commit-audit.mjs`)가 같은 `ship-gate.mjs` 를 쓴다 — 검증기가 두 벌이 되어 템플릿 간 규칙이 갈린다 |
| Makefile / just | 인자 전달이 어색하고 (`make task-new a=… b=…`), 설치 없이 도는 poe 가 pyproject 하나로 끝난다 |
| Pants / Bazel | 템플릿 규모에 비해 설정 표면이 크다 |

## Consequences

- **긍정**: 패키지 수정이 빌드 없이 반영. 두 템플릿의 작업 체계 · CI 감사가 같은 코드.
- **부정**: task 명령에 Node(≥22)가 필요하다 (앱 런타임 · 이미지에는 불필요).
- **후속**: nestjs-template 의 `.github/scripts` · `scripts/agent-work.mjs` 를 고치면 여기도 맞춘다 (언어별 경로 함수 제외).
