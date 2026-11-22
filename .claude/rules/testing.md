# Testing

**테스트는 버그를 잡을 수 있을 때만 쓴다. 과도한 테스트는 지운다.** pytest + pytest-asyncio (`asyncio_mode = auto`).

## 쓴다

| 층 | 대상 | 위치 · 실행 |
| --- | --- | --- |
| unit | 분기 있는 순수 로직 — 이벤트 번역 · 도구 실행 · 집계 · 변환 · 검증 | `packages/*/tests/test_*.py` · `uv run poe test` |
| e2e | HTTP 계약 — 라우트 · 검증 · 응답 / 에러 포맷 · SSE · 실제 DB(SQLite 파일 + Alembic) | `apps/*/tests/test_*.py` + `pytestmark = pytest.mark.e2e` · `uv run poe test:e2e` |

- 에이전트가 들어간 경로는 `agent_core.testing.ScriptedBackend` 로 돌린다 — 실제 백엔드와 같은 `RunContext` 경로(emit · execute_tool)를 탄다.
- 백엔드 번역기는 실제 SDK 타입(`BetaMessage.model_validate` 등) 또는 원본 이벤트 모양으로 입력한다.

## 쓰지 않는다

- **DB mock** — `AsyncSession` · repository 를 mock 으로 대체. mock 이 mock 값을 돌려주는 걸 확인할 뿐이다.
- **실제 모델 호출** — CI 에 키가 없다. SDK 클라이언트를 mock 해 응답 모양을 흉내 내는 테스트도 쓰지 않는다 (번역기를 떼어 테스트한다).
- prompt 문구 단언 · 프레임워크 동작 재확인 (FastAPI 가 422 를 내는지, pydantic 이 범위를 거르는지).
- 같은 경로를 입력만 바꿔 반복하는 케이스, 큰 응답 snapshot.

## 규칙

- 버그 수정 · 리뷰에서 수용한 finding → 재현할 수 있으면 실패하는 테스트 먼저.
- 시간 · 랜덤 · 네트워크는 고정. 테스트 이름 = 문장 (`test_backend_failure_ends_with_run_failed`).
