---
entity: module
name: <module>
code: [apps/api/src/api/modules/<module>]
updated: YYYY-MM-DD
refs: <task-id>
---

# <module>

> 한 줄 역할.

## 표면 (API)

`Response` = 공통 성공 래퍼의 `data` ([공통 규약](../README.md#공통-규약)).

| Method | Path | Auth | Request | Response (`data`) | Errors |
| --- | --- | --- | --- | --- | --- |
| GET | `/v1/<path>` | — | query `page`, `limit` | `Page[Item]` | 400 검증 |

## 흐름

1. 요청 → router (pydantic 검증)
2. service → DB (SQLAlchemy)
3. 응답

<!-- 복잡하면 mermaid sequenceDiagram -->

## 규칙 · 불변조건

- **R1** — WHEN <조건> THEN <결과>.

## 예외 케이스

| 케이스 | 동작 | 근거 (테스트 / 코드) |
| --- | --- | --- |

## 알려진 한계

없음.

## 의존

- 주입: 
- export: 
- 외부: 

## 근거

- `apps/api/src/api/modules/<module>/router.py`
