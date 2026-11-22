# ADR-0003 — CI 기본 on · 릴리스 / 배포 opt-in · 버전 = `apps/*/VERSION`

- **Status**: Accepted
- **Date**: 2026-11-21
- **Refs**: 261121_001_template-bootstrap
- **Supersedes**: —

## Context

nestjs-template 의 릴리스 흐름(canary · stable · hotfix + GHCR 배포)은 release 커밋이 `apps/*/package.json#version` 을 기록한다.
uv 는 워크스페이스 멤버의 `version` 을 `uv.lock` 에 적는다 — release 커밋이 `pyproject.toml` 버전을 바꾸면 lock 이 어긋나 이미지의 `uv sync --locked` 가 실패한다.

## Decision

- CI(커밋 감사 + 검증 + 스크립트 테스트)는 설정 없이 on. 릴리스(`RELEASE_ENABLED`) · Docker 배포(`DEPLOY_ENABLED`)는 저장소 변수로 켠다 — nestjs-template 과 같은 워크플로우.
- **release 커밋은 `apps/*/VERSION` (텍스트 한 줄)만 기록**한다. `pyproject.toml` `version` 은 `0.0.0` 고정. 앱은 `VERSION` 을 OpenAPI · `/v1/health` 에 쓴다. 커밋 감사의 release skip 도 `apps/*/VERSION` 만 바뀐 커밋으로 판정.
- CI · Dockerfile 의 uv 버전 = `uv.lock` 을 쓴 버전으로 고정 (`--locked` 재현성).

## Alternatives

| 대안 | 기각 이유 |
| --- | --- |
| release 커밋에서 `pyproject.toml` + `uv lock` | release 잡에 uv 설치 · 재해석이 들어가고, 의존성이 그 순간 바뀔 수 있다 |
| 동적 버전(`hatch-vcs` 등) | 빌드 백엔드 교체 + 이미지 빌드에 git 메타데이터 필요 |
| 버전 기록 없음 (태그만) | 실행 중인 이미지가 자기 버전을 모른다 |

## Consequences

- **긍정**: lock 은 의존성 변경 때만 바뀐다. 릴리스 스크립트는 Node 만으로 돈다.
- **부정**: 패키지 메타데이터 버전(`importlib.metadata`)은 항상 `0.0.0` — 버전은 `VERSION` 으로만 읽는다.
- **후속**: uv 를 올릴 때 CI `setup-uv` 와 Dockerfile 의 uv 이미지를 같이 올린다.
