---
entity: module
name: health
code: [apps/api/src/api/modules/health]
updated: 2026-11-21
refs: 261121_001_template-bootstrap
---

# health

> DB 연결 확인 + 앱 버전.

## 표면 (API)

| Method | Path | Auth | Request | Response (`data`) | Errors |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/health` | — | — | `{status: "ok", db: "up", version}` | 503 `SERVICE_UNAVAILABLE` (DB ping 실패, `systemMessage` = `db: <예외 타입>`) |

## 흐름

1. `Database.ping()` (`SELECT 1`).
2. 성공 → 200, `version` = `apps/api/VERSION` (없으면 `0.0.0`).

## 규칙 · 불변조건

- **R1** — 모델 백엔드(Anthropic)는 확인하지 않는다 — 외부 장애로 인스턴스가 교체되지 않게.

## 예외 케이스

| 케이스 | 동작 | 근거 |
| --- | --- | --- |
| DB 정상 | 200 + 성공 래퍼 | `test_http.py::test_health_reports_db_in_the_success_envelope` |

## 알려진 한계

없음.

## 의존

- 주입: `app.state.db`
- 외부: DB

## 근거

- `apps/api/src/api/modules/health/router.py`
