# Agent 문서

> 소유: AI · 기준일: 2026-09-20

Agent(=폐업 계획을 만드는 AI 부분) 관련 문서를 모아둔 폴더입니다.
팀 공통 문서(`../architecture.md`, `../hero-scenario.md`, `../schema/`, `../tech-stack.md`)는
`docs/` 바로 아래에 그대로 있습니다.

## 무엇부터 보면 되나

| 알고 싶은 것 | 문서 |
|---|---|
| **작업을 이어받을 때 먼저 읽을 문서** | [`handoff.md`](./handoff.md) |
| **AI 티켓 중 무엇을 마쳤고 무엇이 남았나** | [`implementation-status.md`](./implementation-status.md) |
| **실제 API 호출·MySQL 조회로 확인한 것은 무엇인가** | [`live-verification.md`](./live-verification.md) |
| **공식 폐업 절차·기관·출처는 무엇인가** | [`official-closure-procedure.md`](./official-closure-procedure.md) |
| **뭐가 아직 안 정해졌나** | [`open-decisions.md`](./open-decisions.md) |
| BE에 뭘 요청해야 하나 | [`be-requests.md`](./be-requests.md) |
| 절차 정보를 어디서 읽나 | [`procedure-knowledge.md`](./procedure-knowledge.md) |
| 지원사업 정보를 어디서 읽나 | [`support-knowledge.md`](./support-knowledge.md) |
| 지원사업 Wiki를 ID·UUID로 연결하는 방법 | [`support-wiki.md`](./support-wiki.md) |
| 프로젝트 Obsidian Vault 열기·공고 검수 | [`obsidian/README.md`](./obsidian/README.md) |
| 실제 미검수 공고 색인·검색 및 A8 남은 범위 | [`support-retrieval.md`](./support-retrieval.md) |
| 한 번 실행에 얼마나 쓰나 | [`runtime-limits.md`](./runtime-limits.md) |
| 어떻게 실행하나, 환경변수는 | [`standalone-runtime.md`](./standalone-runtime.md) |
| 각 Agent·Tool의 정확한 입출력 | [`tool-io-schema.md`](./tool-io-schema.md) |
| 공식 데이터 출처와 수집 계획 | [`official-data-sources.md`](./official-data-sources.md) |
| BE 연동 계약(검토 중) | [`be-integration-requirements.md`](./be-integration-requirements.md) |
| 누가 무엇을 호출하나 | [`../architecture.md`](../architecture.md) |

## 지켜지는 규칙

- **데이터 기준은 [`../schema/schema_table.md`](../schema/schema_table.md)입니다.** 테이블·컬럼·타입·키·
  nullable·기본값·enum·관계는 코드나 과거 회의 메모가 이 문서를 덮어쓰지 않습니다.
  필요한 변경은 근거와 영향 범위를 [`be-requests.md`](./be-requests.md)에 건의하고 협의합니다.
- **미정 항목은 `open-decisions.md` 한 곳에만 씁니다.** 다른 문서에 "TBD"라고만 적지 않습니다.
- **숫자는 한 곳에만 씁니다.** 호출 수·시간 상한은 `runtime-limits.md`, 환경변수는
  `standalone-runtime.md`가 단일 출처입니다.
- 현재 구현 여부는 코드로, 실제 동작은 출처가 기록된 실측으로 확인합니다. 더미 금지 이전의 테스트
  통과를 현재 실제 서비스 검증으로 옮겨 적지 않습니다. **스키마와 다른 구현이 발견되면 불일치이지 새 기준이 아닙니다.**
  목표 구조를 현재 상태처럼 적지 않습니다.

## API 계약은 어디 있나

`docs/interface-spec.md`는 **삭제했습니다.** 내용 없이 "이 파일은 API 명세가 아닙니다"라고만
적힌 안내 파일이었습니다. 찾던 내용은 여기 있습니다.

- 외부 HTTP·DTO 제안과 아직 정할 항목: [`be-integration-requirements.md`](./be-integration-requirements.md)
- 그중 결정 대기 항목: [`open-decisions.md`](./open-decisions.md)
- Agent 내부 입출력: [`tool-io-schema.md`](./tool-io-schema.md)

승인된 Agent 연동 API 계약은 아직 **0개**입니다. OpenAPI와 실제 route도 위 스키마를 준수하는
공동 계약에 맞춰야 합니다. 내부 DTO와 실제 테이블 저장 형식이 같다는 뜻은 아닙니다.
