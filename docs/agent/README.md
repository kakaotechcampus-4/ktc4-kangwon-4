# Agent 문서

> 소유: AI · 기준일: 2026-09-19

Agent(=폐업 계획을 만드는 AI 부분) 관련 문서를 모아둔 폴더입니다.
팀 공통 문서(`../architecture.md`, `../hero-scenario.md`, `../schema/`, `../tech-stack.md`)는
`docs/` 바로 아래에 그대로 있습니다.

## 무엇부터 보면 되나

| 알고 싶은 것 | 문서 |
|---|---|
| **뭐가 아직 안 정해졌나** | [`open-decisions.md`](./open-decisions.md) |
| BE에 뭘 요청해야 하나 | [`be-requests.md`](./be-requests.md) |
| 절차 정보를 어디서 읽나 | [`procedure-knowledge.md`](./procedure-knowledge.md) |
| 한 번 실행에 얼마나 쓰나 | [`runtime-limits.md`](./runtime-limits.md) |
| 어떻게 실행하나, 환경변수는 | [`standalone-runtime.md`](./standalone-runtime.md) |
| 각 Agent·Tool의 정확한 입출력 | [`tool-io-schema.md`](./tool-io-schema.md) |
| 공식 데이터 출처와 수집 계획 | [`official-data-sources.md`](./official-data-sources.md) |
| BE 연동 계약(검토 중) | [`be-integration-requirements.md`](./be-integration-requirements.md) |
| 누가 무엇을 호출하나 | [`../architecture.md`](../architecture.md) |

## 지켜지는 규칙

- **미정 항목은 `open-decisions.md` 한 곳에만 씁니다.** 다른 문서에 "TBD"라고만 적지 않습니다.
- **숫자는 한 곳에만 씁니다.** 호출 수·시간 상한은 `runtime-limits.md`, 환경변수는
  `standalone-runtime.md`가 단일 출처입니다.
- 구현 사실은 **코드와 테스트가 문서보다 우선**합니다. 목표 구조를 현재 상태처럼 적지 않습니다.

## API 계약은 어디 있나

`docs/interface-spec.md`는 **삭제했습니다.** 내용 없이 "이 파일은 API 명세가 아닙니다"라고만
적힌 안내 파일이었습니다. 찾던 내용은 여기 있습니다.

- 외부 HTTP·DTO 제안과 아직 정할 항목: [`be-integration-requirements.md`](./be-integration-requirements.md)
- 그중 결정 대기 항목: [`open-decisions.md`](./open-decisions.md)
- Agent 내부 입출력: [`tool-io-schema.md`](./tool-io-schema.md)

승인된 API 계약은 아직 **0개**입니다. 구현 기준은 공동 승인 뒤 생기는 OpenAPI와 실제 route입니다.
