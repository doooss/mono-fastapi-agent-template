# ADR-0007 — DB = SQLAlchemy 2 async + Alembic, 기본 SQLite

- **Status**: Accepted
- **Date**: 2026-11-21
- **Refs**: 261121_001_template-bootstrap
- **Supersedes**: —

## Context

세션 · 실행 기록 · 이벤트 리플레이를 저장해야 한다. 템플릿은 설치 없이 돌고(SQLite), 운영은 Postgres 로 옮길 수 있어야 한다.

## Decision

- SQLAlchemy 2 async (`aiosqlite` 기본) + 선언형 모델. 공통 = `Base`(이름 규칙 고정) · `IdMixin`(uuid hex) · `TimestampMixin` · `UTCDateTime` (SQLite 에서도 UTC aware 로 읽힘).
- 스키마 = Alembic 리비전 (`apps/api/migrations`, async env, SQLite 는 batch 모드). 커스텀 타입은 리비전에 `sa.DateTime(timezone=True)` 로 렌더 — 리비전이 앱 코드를 import 하지 않는다.
- `DB_MIGRATE_ON_START` (기본 production 외 on, 이미지 on) — 단일 인스턴스 SQLite 를 설정 없이 띄우기 위한 것. 다중 인스턴스 운영은 끄고 배포 단계에서 돌린다.

## Alternatives

| 대안 | 기각 이유 |
| --- | --- |
| SQLModel | pydantic 모델과 ORM 모델을 섞어 경계 검증이 흐려진다 |
| `create_all` (마이그레이션 없음) | Postgres 운영에서 스키마 변경을 못 따라간다 |
| Tortoise · Piccolo | 생태계 · 문서 · Alembic 급 마이그레이션 도구가 약하다 |

## Consequences

- **긍정**: SQLite ↔ Postgres 전환 = URL + 드라이버(`asyncpg`). 부분 유니크 인덱스(세션당 running 하나)도 두 DB 모두 지원.
- **부정**: 모델 변경마다 리비전 생성 · 검토 단계.
- **후속**: Postgres 전환 시 `asyncpg` 추가, `DB_MIGRATE_ON_START=false`, 배포 파이프라인에 `alembic upgrade head`.
