# Agent 범위

Agent는 폐업 Case의 확인된 사실과 근거로 **Blocker 1개·Next Action 1개** 판단.
현재 MVP의 정상 판단에는 근거 있는 Blocker가 항상 1개 있다.
사용자가 현실에서 실행한 결과를 입력하면 같은 Case를 다시 판단한다.
모든 정상 판단은 독립 Review를 거치며 Case 저장은 BE가 담당한다.

**데이터의 절대 기준은 [schema_table.md](../schema/schema_table.md)다.**
필드·타입·enum·NULL·기본값·관계·상태 전이는 이 기준을 따르고,
Agent가 다르면 Agent를 고친다. MVP 단순화를 이유로 제약을 완화하지 않는다.
낙관적 락은 쓰지 않는다 — Agent는 `CASE.case_version`과 이를 참조하는 버전 컬럼을 구현하지 않고,
같은 Case인지는 `snapshot_id`와 필드의 기존값으로 확인한다.

**규칙은 문서가 아니라 코드에 둔다.** 각 문서는 해당 구성요소의 사실만 담고 코드를 가리킨다.
문서와 코드가 다르면 코드가 맞다.

| 구성요소 | 문서 | 코드 |
|---|---|---|
| 최종 판단(Blocker·Next Action) | [supervisor.md](./supervisor.md) | `supervisor/agent.py` |
| 사실 추출·충돌 감지 | [info-agent.md](./info-agent.md) | `info_agent/agent.py` |
| 절차 조회·실행 가능 판정 | [procedure-tool.md](./procedure-tool.md) | `procedure_tool/` |
| 지원조건 비교 | [support-agent.md](./support-agent.md) | `support_agent/agent.py` |
| 독립 검수 | [review-tool.md](./review-tool.md) | `review_tool/tool.py` |
| 근거·개인정보·상태 차단 | [guardrails.md](./guardrails.md) | `claim_safety.py`, `guardrails.py`, `projection.py`, `enrichment.py` |

입출력 타입·enum·불변식은 [`schemas.py`](../../backend/app/agent/schemas.py)(검증자가 계약이다),
호출 순서·재작업·실패 경로는 [`graph.py`](../../backend/app/agent/graph.py),
호출·시간 한도는 [`runtime.py`](../../backend/app/agent/runtime.py)·[`llm.py`](../../backend/app/agent/llm.py)가 기준이다.

Agent는 SQL·ORM으로 DB를 직접 읽거나 쓰지 않는다 — 저장·재조회는 이 저장소의 Agent 범위 밖이다.
판단 방향은 [팀 원칙](../../CLAUDE.md), 사용자 흐름은 [Hero Scenario](../hero-scenario.md),
호출 구조는 [architecture.md](./architecture.md)를 따른다.

## 실행 경계

[`build_runtime`](../../backend/app/agent/runtime.py)은 호출자가 준비한 실제 절차 목록
(`known_procedure_steps`), 검수 지원 자료(`support_catalog`), 메모리에 적재한 절차 자료
(`procedure_store`)를 받는다. 자료가 없으면 빈 결과를 유지하며 임의 사업·조건으로 채우지 않는다.
환경변수는 [`.env.example`](../../.env.example)를 따르고, 공용 runtime은 요청마다
`run_planning(AgentGraphInput)`으로 실행한 뒤 애플리케이션 종료 시 `aclose()`로 정리한다.

권한을 확인한 Case snapshot 제공, 검수된 변경 후보의 저장·재조회는 호출자의 책임이다.
`CONFLICT_CONFIRMED`에는 서버가 보관한 원래 충돌 후보를 전달하며, 클라이언트가 보내온
임의 후보를 그대로 신뢰하지 않는다. Agent의 `REVIEWED_PLAN`은 DB 저장 완료를 뜻하지 않는다.

### DB 칸에 맞추기

Agent가 만드는 값은 BE가 그대로 DB에 넣는다. 그래서 칸의 길이·형식을
[`schemas.py`](../../backend/app/agent/schemas.py)의 타입에 그대로 박아두었다.
넘치는 값은 MySQL이 자르기 전에 Agent에서 먼저 막히고, 실행은 재시도 경로를 탄다.

- `EVIDENCE.content_hash`는 VARCHAR(64)라 출력·저장 값은 64자 hex로 유지한다.
  BE 입력의 `sha256:` 접두사는 타입 검증 시 제거하고 길이·문자를 검증한다.
  무결성 확인용 `subject_digest`·`conflict_digest`는 VARCHAR(255) 칸에
  들어가므로 접두사를 유지한다.
- `SUPPORT_ITEM`·`SUPPORT_MATCH`의 `catalog_version`은 VARCHAR(50)이다.
- `CASE.business_type`에는 사용자가 쓴 말(`"카페"`)이 들어가고
  `PROCEDURE_STEP.applicable_business_type`에는 코드(`"CAFE"`)가 들어간다. 그대로 비교하면
  업종 전용 절차가 전부 걸러지므로 `procedure_tool/rules.py`의 `business_type_code`로
  바꾼 뒤 비교한다.
- `restoration_status`·`restoration_scope`·`demolition_required`의 `UNKNOWN`은 Agent에서
  `status=UNKNOWN`·`value=null`로 표현한다. BE는 저장할 때 `UNKNOWN` 문자열로 바꾸고,
  snapshot을 만들 때 다시 `status=UNKNOWN`·`value=null`로 되돌린다.

## 포함 기능

- **사실 추출:** 허용된 Case 필드의 변경 후보와 입력 근거를 만든다. Agent가 Case를 직접 수정하지 않는다.
- **근거 조회:** 실제 절차·지원사업 식별자와 사람이 검수한 자료만 사용한다.
- **한 판단 지점:** Supervisor가 Blocker와 Next Action을 결정한다. 하위 Agent·Tool은 분석과 근거만 반환한다.
- **필수 Review:** 모든 정상 판단을 독립 검수한다.
- **재계획:** 같은 Case의 행동 결과를 반영한 후보와 새 판단을 만든다.
- **충돌 확인:** 확정값과 새 입력이 다르면 사용자 선택 전 반영하지 않는다.
- **안전 실패:** 근거 부족·Review 실패를 성공으로 바꾸지 않고 검수 전 초안을 내보내지 않는다.

## 제외 기능

- Chroma·임베딩·S3·Wiki miss RAG와 새 지식 관리 화면
- 공식 문서 자동 수집·갱신·첨부파일 파싱·배치
- 일반화된 자율 Tool 선택 계획과 Agent 구성 확장
- 비용·반송률 대시보드, 관측된 결함과 무관한 성능·정규식 고도화
- 전체 폐업 완료 자동 판정, 업종·지원사업 범위 확대

Review·충돌 보호·근거·개인정보 검증은 축소하지 않는다.
폐업 결정·최적 폐업일·법률/세무/자격의 최종 판단·신청/계약/외부 연락 실행은
[팀 공통 제외 범위](../../CLAUDE.md)를 따른다.

## 완료 기준

`AgentRuntime.run_planning`의 입력부터 출력까지 실제 Graph·Info·Support·Supervisor·Review 경로로 검증한다.

| 확인 항목 | 통과 기준 | 2026-09-28 실행 |
|---|---|---|
| 최초 판단 | Blocker 1개와 실행할 Next Action 1개를 만들고 Review를 통과한다 | 입력 4종 × 3회 중 7회 검수 통과. 통과한 7회의 Blocker·Next Action이 모두 같았다. 실패 5회는 모두 Info 호출 실패이고 판단 내용의 불일치는 없었다 |
| 핵심 재계획 | 행동 결과를 읽기 상태에 적용해 새 Next Action을 검수하고 근거가 연결된 후보와 함께 반환한다 | 결과 입력 문장 2종 × 3회가 모두 통과했고, 같은 문장의 세 번은 Blocker·Next Action·변경 후보가 같았다. 두 문장 모두 최초 판단과 다른 행동이 나왔고, 문장이 말한 값만 바뀌었다 |
| 충돌 | `NOT_REQUIRED`와 `REQUIRED`가 충돌하면 후보·근거를 반환하고 멈춘다. 유효한 확인 뒤 재계획·Review를 수행한다 | 실제 호출로 확인하지 않았다 |
| 추가 질문 | 판단에 필요한 값이 없으면 미확인을 유지하고 이해할 수 있는 확인 질문을 낸다 | 최초 판단 4종 모두 미확인 필드를 유지했다 |
| 지원 근거 | 검수 Wiki의 조건만 사용한다. 조회만으로 신청 이력이 생기지 않는다 | 검수한 지원사업 1건으로 처음 실제 호출했다. 같은 자료를 최초 판단에 넣어도 행동이 바뀌지 않는 것을 따로 확인했다 |
| 실패·오래된 입력 | 한도 소진은 미검수 초안 없는 `SAFE_FAILURE`로 끝낸다. snapshot·현재값이 다른 충돌 확인은 거부한다 | 실패 5회 모두 미검수 초안 없이 `SAFE_FAILURE`로 끝났다. 오래된 충돌 확인 거부는 실제 호출로 확인하지 않았다 |

첫 행동과 현실 결과 이후 행동의 **차이**를 확인한다.
실행 횟수·코드 존재·외부 API의 HTTP 200으로 대신하지 않는다.
서비스 전체의 완료 증거는 같은 Case의 최초 판단 → 결과 입력 → 재계획 → 저장·재조회이며,
Agent 응답 자체는 저장 성공이 아니다.
합성 입력·실행 기록은 Git 추적에서 제외한다.

반복 평가에서는 입력·근거·Review 설정을 고정하고, 행동 코드·대상과 실제 확인 항목을
함께 비교한다. Supervisor 단독 비교, 전체 Graph 실행, 판단 재사용은 구분해서 검증한다.

위 실행은 [`evaluate_planning.py`](../../backend/scripts/evaluate_planning.py)로 재현한다.
같은 판단인지는 Blocker 설명과 Next Action 전체(행동 코드·대상·제목·이유·확인 질문)를
digest로 비교한다. 근거 ID는 실행마다 새로 발급되므로 비교에서 제외한다.
실행마다 새 runtime을 만들고 판단 재사용을 꺼서, 반복이 실제로 다시 호출하도록 한다.

이 기록으로 말할 수 없는 것: 네 입력 모두 원상복구·철거가 미확인이라 규칙 적용 후 후보가
하나뿐이었다. 여러 후보 사이의 선택이 일관적인지는 증명하지 않는다.
모델은 표본 수준의 재현성을 보장하지 않으므로 이 결과는 측정이지 보장이 아니다.
