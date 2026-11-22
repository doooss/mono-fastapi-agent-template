# ADR-0008 — 실행 = 요청에 묶인 SSE + 이벤트 기록

- **Status**: Accepted
- **Date**: 2026-11-21
- **Refs**: 261121_001_template-bootstrap
- **Supersedes**: —

## Context

에이전트 실행은 수십 초 ~ 수 분이다. 운영 서비스(cmong-agents)는 실행을 백그라운드 작업으로 돌리고 Redis Stream 으로 어느 인스턴스든 이벤트를 다시 읽게 했지만, 그 구조는 Redis · 락 · heartbeat · 고아 정리가 같이 들어온다.

## Decision

- `POST /v1/agents/{name}/runs` 가 실행을 시작하고 **그 응답이 SSE 스트림**이다. 클라이언트 연결이 끊기면 실행을 취소한다 (Managed 는 서버 세션에 `user.interrupt`).
- 끝나면(완료 · 실패 · 취소) `agent_runs` 에 요약, `agent_run_events` 에 `text.delta` 를 뺀 이벤트를 기록한다 → `GET /v1/runs/{id}/events` 로 리플레이.
- 세션당 실행 하나는 DB 부분 유니크 인덱스로 막는다 (인스턴스 무관).

## Alternatives

| 대안 | 기각 이유 |
| --- | --- |
| 백그라운드 실행 + Redis Stream 재접속 | 템플릿 기본 의존성(Redis)과 상태 관리가 늘어난다. 필요해지면 `Runner.stream` 소비자를 백그라운드로 옮기면 된다 |
| 이벤트를 매 건 즉시 기록 | 실행당 쓰기 수십 ~ 수백 건. 리플레이 용도에는 끝에 한 번이면 충분 |

## Consequences

- **긍정**: 인프라 = 앱 + DB. 실행 수명이 HTTP 요청과 같아 고아 실행이 없다.
- **부정**: 연결이 끊기면 실행도 끝난다 (모바일 · 긴 실행에 불리). 실행 중 이벤트는 그 연결만 본다. 프로세스가 죽으면 그 run 은 `running` 으로 남는다.
- **후속**: 재접속이 필요하면 백그라운드 실행 + 이벤트 버스 ADR 로 대체.
