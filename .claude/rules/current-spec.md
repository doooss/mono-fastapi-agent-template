# Current Spec (현재 사양)

출고 게이트 5단계. **지금 코드가 하는 일**을 개체(모듈) 단위로 남긴다. 위치 → [docs/specs/](../../docs/specs/README.md).

## 원칙

- **현재만.** 이력 · 변경 로그 섹션 금지 — 이력은 git · task · ADR.
- **코드에서 읽어 쓴다.** 실제 시그니처 / 요청 · 응답 모델 / 에러 / 의존성. 추측 금지.
- **덮어쓴다.** 코드와 같은 커밋에서 최종 상태로 다시 쓴다.
- **변경 기준.** 작업에서 바뀐 코드의 사양(frontmatter `code`)을 같은 커밋에서 최신으로 — 빠지면 CI warning (`Spec: pending | none` 이면 생략).
- **예외 · 한계까지.** 리뷰에서 확정된 경계 동작은 `## 예외 케이스`, 미구현 · no-op · 버그는 `## 알려진 한계`.

## 개체

| 종류 | 경로 | 단위 | 템플릿 |
| --- | --- | --- | --- |
| module | `docs/specs/modules/<module>.md` | `apps/*/src/*/modules/<module>` 1개 (API 표면 · 흐름 · 규칙) | [_templates/module.md](../../docs/specs/_templates/module.md) |
| flow | `docs/specs/flows/<flow>.md` | 모듈 2개 이상을 가로지르는 흐름 | [_templates/flow.md](../../docs/specs/_templates/flow.md) |
| package | `docs/specs/packages/<pkg>.md` | 공유 패키지의 공개 API (`packages/*`) | module 템플릿 준용 |

새 개체 = 템플릿 복사 → [docs/specs/README.md](../../docs/specs/README.md) 인덱스에 한 줄. 응답 래퍼 · 에러 포맷 같은 공통 규약은 README `## 공통 규약` 에 한 번만.

```yaml
---
entity: module            # module | flow | package
name: health
code: [apps/api/src/api/modules/health]
updated: 2026-11-21       # 마지막 갱신일
refs: 261121_001_health   # 마지막으로 갱신한 task id
---
```

module 문서 섹션: `## 표면 (API)` (Method · Path · Auth · Request · Response · Errors) / `## 흐름` / `## 규칙 · 불변조건` (`R1` …) / `## 예외 케이스` / `## 의존` / `## 근거` (코드 경로). 해당 없으면 "없음" 한 줄.
