# Security & Secrets

env · 로그 · 인증 · 외부 SDK 를 다룰 때.

## Env

- 로컬 `apps/api/.env.<APP_ENV>` (gitignore, 키 목록 = `apps/api/.env.example`). 컨테이너는 런타임 주입 — 이미지에 secret 을 굽지 않는다. CI 는 Actions secret.
- 새 env = `Settings` 필드 + `.env.example` 키. secret 은 `SecretStr`. `ANTHROPIC_API_KEY` 는 `Settings` 로 읽어 SDK 에 넘긴다 (SDK 가 `os.environ` 을 직접 읽게 두지 않는다 — `.env.*` 가 반영되지 않는다).
- 스키마가 강제한다: production 은 `ALLOWED_ORIGINS` 명시(`*` 거부), 배포 환경(dev · qa · production)은 `DOCS_PASSWORD` 기본값 거부. production 5xx 응답은 내부 메시지를 가린다.

## 로그 (PII)

로그 / trace attributes 에 넣지 않는다: 이메일 · 전화 · 이름 · 주소 · 주민 / 사업자번호 · 토큰 · 요청 body 전체 · **prompt · 모델 출력 · 도구 입력 / 출력 본문**. 에이전트 이벤트 로그는 `observe.log_fields` 가 고른 필드(타입 · id · 이름 · usage · 소요 시간)만 남긴다. 요청 로그 = method · path · status · duration. 본문을 찍는 라이브러리 로거는 `configure_logging` 의 `QUIET_LOGGERS` 에 넣는다 (DEBUG 에서도 WARNING 이상만).

## 에이전트

- 모델에 넘기는 도구 오류 문자열은 사용자에게 보일 수 있다 — 내부 주소 · 자격증명을 예외 메시지에 넣지 않는다.
- `BackendError.message` 는 클라이언트에 그대로 간다 — 안내 문구만. 원인은 로그.
- Agent SDK 백엔드는 내장 도구(Bash · 파일 · 웹)를 끄고, 사용자 입력을 그대로(`verbatim_prompts`) 보낸다 — 끄면 입력의 `@/경로` 가 서버 파일을 읽고 `/명령` 이 실행된다. 바꾸려면 ADR 을 남긴다.

## 금지

- `.env*` (example 제외) 커밋. secret 값을 커밋 메시지 / task / 사양에 기록 (key 이름 · 위치만).
- URL 에 자격증명 하드코딩 · TLS 검증 끄기.
