# Code Style

모든 코드 변경에 적용.

1. **요청된 변경만.** 같은 파일의 무관한 리팩터 · 스타일 정리를 끼워 넣지 않는다 (`lint:fix` 제외).
2. **lint + type clean.** `uv run poe lint` (ruff check + format) · `uv run poe check-types` (mypy `--strict`) 통과 = CI 와 동일. `# type: ignore` · `# noqa` 는 원인을 못 고칠 때만, 코드와 사유를 붙인다.
3. **경계에서 검증.** HTTP 입력 = pydantic 모델 (`extra="forbid"`), env = `BaseAppSettings`, 외부 응답 = SDK 타입 또는 pydantic. `Any` 로 경계를 통과시키지 않는다.
4. **로그.** `logging.getLogger(__name__)` + `extra={...}` 구조화 필드. `print` 금지. 본문 · 토큰 · 개인정보 금지 ([security.md](security.md)).
5. **주석.** 비자명한 "왜" 만 한 줄. 코드 · 주석 · 로그에 이모지 금지.

## 이름 · import

- 모듈 snake_case, 클래스 PascalCase. 응답 envelope 필드(`statusCode` 등)만 camelCase — NestJS 템플릿과 같은 JSON.
- import = 패키지 이름(`agent_core`, `fastapi_common`, `api.…`) 절대 경로. 패키지 간 상대 경로 · `src/` 경로 import 금지.
