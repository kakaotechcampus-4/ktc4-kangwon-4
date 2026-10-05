# Agent 범위

Agent는 폐업 Case의 확인된 사실과 근거로 **Blocker 1개·Next Action 1개** 판단.
현재 MVP의 정상 판단에는 근거 있는 Blocker가 항상 1개 있다.
사용자가 현실에서 실행한 결과를 입력하면 같은 Case를 다시 판단한다.
모든 정상 판단은 독립 Review를 거치며 Case 저장은 BE가 담당한다.

원상복구 범위·철거 필요 여부의 미확인은 Case의 후속 진척을 막는 조건이며, 이를 해소할
임대인 확인 행동은 실행 가능하다. 확인 행동을 할 수 있다는 이유만으로 이 Blocker를 제거하지 않는다.
일반 절차는 공식 안내에 따른 진행 상태와 준비사항 확인을 Blocker로 제시하며,
확인된 사실과 후보에 없는 차단 조건을 만들어내지 않는다.

지원사업은 MVP 구현·정상 동작 검증 범위에서 제외. 기존 지원사업 코드와 자료는 유지.

필드·타입·enum·NULL·기본값·관계·상태 전이는 실제 DTO·BE 모델·검증 코드가 기준이다.
[schema_table.md](../schema/schema_table.md)는 설계 배경으로 참고하며 코드와 다르면 실제 코드를 확인한다.
MVP 단순화를 이유로 제약을 완화하지 않는다.
낙관적 락은 쓰지 않는다 — Agent는 `CASE.case_version`과 이를 참조하는 버전 컬럼을 구현하지 않고,
각 결과가 같은 Case 조회 상태를 기준으로 했는지는 `snapshot_id`로 확인한다.
충돌 확인에서는 대상 필드의 기존 상태·값도 대조한다.

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

BE가 가져다 쓰는 입출력 DTO는 [`app.common.agent_dto`](../../backend/app/common/agent_dto.py)에서
공개한다. 기존 검증 모델을 그대로 사용하며 입력은 `AgentGraphInput`, 출력은
`AgentGraphOutput`이다. 출력의 `outcome_type`은 `REVIEWED_PLAN` / `CONFLICT` /
`SAFE_FAILURE` 중 하나다. 필드 구성과 BE의 처리 책임은 해당 모듈 설명을 따른다.

BE에 제공하는 공용 호출 함수는 [`app.common.agent_service.run_case_planning`](../../backend/app/common/agent_service.py)이다.
`build_planning_input`은 저장된 입력 이벤트의 ID·시각·비식별 문장과 Case snapshot으로
`CASE_CREATED` 또는 `RESULT_SUBMITTED` 입력을 조립한다. `build_conflict_input`은 BE가
보관한 원래 충돌 후보와 확인 시각으로 `CONFLICT_CONFIRMED` 입력을 조립한다.

```python
request = build_planning_input(
    trigger_type="CASE_CREATED", case_snapshot=snapshot, user_input=redacted_input,
)
outcome = await run_case_planning(
    request, known_procedure_steps=registry, procedure_bindings=bindings,
    procedure_store=reviewed_store, support_catalog=reviewed_catalog,
)
```

이 함수는 실제 runtime 생성·호출·종료까지 처리하며 판단 재사용은 하지 않는다.
반환된 `AgentGraphOutput`은 아직 저장되지 않은 결과다. BE의
[`case_snapshot.py`](../../backend/app/be/services/case_snapshot.py)가 저장된 Case로 snapshot을 만들고,
[`decision_record.py`](../../backend/app/be/services/decision_record.py)가 검수된 판단을 저장한다.
Blocker·Next Action·검수 기록을 저장하며, 판단 중 생성한 근거 본문·Case 변경 후보 저장은 아직 남아 있다.

### 비슷한 필드의 역할과 현재 연결

| 필드 | 실제 용도·현재 연결 |
|---|---|
| `snapshot_id` / `based_on_snapshot_id` | BE가 조회마다 발급한 Case 조회 상태 ID / 하위 결과가 참조하는 같은 ID. `DecisionRecord.snapshot_id`에 ID는 저장하지만 snapshot 본문은 저장하지 않는다. |
| `run_id` / `call_id` / `review_call_id` | Graph 실행 / 개별 구성요소 호출 / PASS를 반환한 Review 호출의 ID. `DecisionRecord`에는 `run_id`가 저장되며 `review_call_id` 전용 컬럼은 없다. |
| `trace_id` | 호출자가 선택적으로 주는 외부 추적 ID. `InvocationMeta`에는 전달하지만 현재 BE 첫 판단은 지정하지 않으며 `TraceEvent`에도 연결되지 않는다. 저장하려면 기존 `save_reviewed_plan(trace_id=...)`에 별도로 전달한다. |
| `input_event_id` / `client_event_id` | 현재 BE는 저장된 이력에서 `case_history:{id}`를 만들어 전자에 넣고, 후자는 `None`으로 보낸다. `client_event_id`를 받는 것만으로 중복 요청 방지가 구현되지는 않는다. |
| `CaseFact.updated_at` / `ProcedureProgress.updated_at` | 개별 사실의 변경 시각 / Case별 절차 진행 행의 변경 시각. 현재 BE는 사실의 시각을 `None`으로, 절차 시각은 `CaseProcedureStep.updated_at`으로 채운다. |
| `submitted_at` / `captured_at` / `confirmed_at` | 입력 이력 시각 / snapshot 조립 시각 / 사용자 충돌 확인 시각. 서로 대신 채우는 값이 아니다. |

Trigger와 그 안의 `RedactedInput`에는 같은 의미의 `submitted_at`이 있다. 현재 입력 조립 함수는
같은 값을 넣지만 DTO는 두 입력 ID의 일치만 검사하며, 두 시각의 일치까지 검사하지는 않는다.
검수 기록도 출력 전체가 아니다. `DecisionRecord`는 실행·snapshot·검수 대상 ID, digest·판정·검수 시각
등을 선택해 저장하며 `ReviewSubject` 본문이나 하위 호출 결과 전체를 저장하지 않는다.
현재 [`case_snapshot.py`](../../backend/app/be/services/case_snapshot.py)와
[`decision_record.py`](../../backend/app/be/services/decision_record.py)의 연결 상태를 기준으로 한 설명이다.

[`app.common.agent_data`](../../backend/app/common/agent_data.py)의 `build_known_procedure_steps`는
BE가 조회한 `ProcedureStep`·`StepDependency`·`StepEligibility` 행을 변환한다.
시간대 없는 DB 시각에는 호출자가 전달한 `db_timezone`을 적용한다. 공식 절차 자료와 지원 자료는
각각 `load_reviewed_procedure_store`·`load_reviewed_support_catalog`로 검증한다.
현재 BE 모델에 없는 검수·조건·근거 필드를 만들어 채우지는 않는다.

`procedure_bindings`의 키는 AI의 기존 절차 의미 코드, 값은 BE의 실제 `ProcedureStepRef`다.
예를 들어 `"FILE_FOOD_SERVICE_CLOSURE"`에 BE에서 조회한 식품영업 폐업 절차의 ID·코드를 연결한다.
행동 대상·진행 상태·근거 조회에는 BE 코드가 그대로 남는다. `TEMP_*` 이름이나 절차명으로
의미를 추정하지 않으며, 다른 절차에 같은 ID·코드를 중복 연결하거나 미등록 대상을 연결하면 거부한다.
새 호출 함수에는 명시적 매핑이 필수이고 `{}`는 매핑 없음이다. 기존 `build_runtime` 호출에서만
매핑 생략 시 이미 등록된 코드가 AI 의미 코드와 정확히 같은 항목을 사용한다.
runtime은 검증한 대응표를 절차조회 Tool에도 전달한다. Tool은 반환 문서의 `step_codes`만
실제 DB 코드로 바꾸며, 대응이 없는 코드로는 행동 대상을 연결하지 않는다.
승인 JSON과 DB Evidence의 원문·해시·근거 ID는 바꾸지 않는다.

[`build_runtime`](../../backend/app/agent/runtime.py)은 호출자가 준비한 실제 절차 목록
(`known_procedure_steps`), 검수 지원 자료(`support_catalog`), 절차 검수 목록
(`procedure_store`)을 받는다. 절차 검수 목록이 비어 있으면 동봉 JSON을 검수·검색 메타정보로
읽는다. 절차 원문과 근거 ID는 BE가 조회한 `CaseSnapshot.evidence_records`에서 가져오며,
DB 근거가 없으면 JSON 본문으로 대신하지 않고 빈 결과를 반환한다.
환경변수는 [`.env.example`](../../.env.example)를 따르고, 공용 runtime은 요청마다
`run_planning(AgentGraphInput)`으로 실행한 뒤 애플리케이션 종료 시 `aclose()`로 정리한다.

### 검수 절차 자료 저장·조회

아래 적재·조회 동작에는 [코드 PR #53](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/53)과
[검수 데이터 PR #54](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/54)의
`app/common/reviewed-procedures.ko-KR.json`이 함께 필요하다.
빈 절차 검수 목록으로 runtime을 만들 때 JSON이 없거나 잘못됐으면 생성 단계에서 실패한다.
따라서 #54를 먼저 반영하거나 #53과 같은 배포에 포함한다.
기존 Case에 자료를 넣을 때는 backend 디렉토리에서 다음 명령을 실행한다.
`123`은 실제 존재하는 Case ID로 바꾼다.

```bash
.venv/bin/python -m scripts.import_reviewed_procedures --case-id 123
```

[`import_reviewed_procedures`](../../backend/app/common/agent_data.py)는 기존 BE의
`create_evidence()`로 Case별 발췌·출처·버전·해시·시각·상태를 저장한다. CLI가 전체 자료를
한 번에 commit하며 실패하면 rollback한다. 같은 ID와 내용의 재실행은 건너뛰고,
같은 ID에 다른 내용이 있으면 덮어쓰지 않는다. 새 버전은 새 근거로 남는다.
검수자·검수 시각·유효기간·검색어·절차 연결은 승인 JSON에 유지한다.

BE의 기존 `get_evidence_by_case_id()` → `build_case_snapshot()` 조회 결과를 Graph가 Tool에
전달한다. Tool은 승인 목록과 출처·버전·해시·발췌가 일치하는 DB 근거만 사용하며,
DB의 `evidence_id`를 그대로 반환한다. Agent는 전달받은 자료를 다시 DB에서 조회하지 않는다.

현재 새 Case 생성 경로는 이 적재 함수를 호출하지 않는다. 자동 공급에는 BE에서
Case 생성 트랜잭션 안에 적재 함수를 호출하고, 첫 snapshot 생성 전에 저장을 마쳐야 한다.
`TEMP_*` 절차와 AI 의미 코드의 대응도 아직 필요하므로 수동 적재 성공을 서비스 전체 연결로 보지 않는다.

자료가 있지만 절차 대응이 0개이고 실행 가능한 행동 후보도 없으면 Supervisor는
`AGENT_PROCEDURE_BINDINGS_MISSING`으로 종료한다. 복구 안내는 `CONTACT_SUPPORT`이며,
사용자에게 입력 필드를 요구하거나 Supervisor·Review LLM 호출을 반복하지 않는다.
실제 사용자 정보 부족은 Info가 판단을 막는다고 표시한 미확인 조건 하나를 질문한다.

자료 공급에 남은 BE 요청은 실제 절차 ID·코드와 Case 연결 확정, 신규 Case 자동 자료 적재다.
전달된 대응표를 적용하는 Agent 코드는 구현했으며, 실제 운영 대응값은 아직 미확정이다.
TODO: 확정된 실제 대응값을 전달하고,
신규 Case 생성 → 실제 LLM 검수 → 판단 저장 → 새 세션 조회를 확인한다.

권한을 확인한 Case snapshot 제공, 검수된 변경 후보의 저장·재조회는 호출자의 책임이다.
`CONFLICT_CONFIRMED`에는 서버가 보관한 원래 충돌 후보를 전달하며, 클라이언트가 보내온
임의 후보를 그대로 신뢰하지 않는다. Agent의 `REVIEWED_PLAN`은 DB 저장 완료를 뜻하지 않는다.

### 충돌 확인의 구현 상태

[PM의 PR #48 결정](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/48#issuecomment-5945630407)은
`CONFLICT`일 때 확인 화면을 두고, `UPDATED`는 다시 묻지 않는 것이다.
Agent에는 확정값과 다른 새 입력을 `CONFLICT`로 반환하고, 확인 입력 뒤 재계획하는 경로가 있다.
현재 BE의 `first_judgment.py`는 `CONFLICT`도 `FAILED`로 처리하므로 사용자 확인 연결은 남아 있다.
`case_snapshot.py`는 매번 새 UUID를 발급하며, 충돌 후보·snapshot의 보관 및 재사용 방식은
BE·AI가 함께 확정해야 한다. 기존 Agent는 원래 후보의 snapshot ID와 대상 필드의 현재 상태·값을
검사한다. 이 검사 조건을 설명한 것이며, BE 보관 정책이나 서비스 연결을 구현한 것은 아니다.

DB에는 이미 `ConflictReference`의 참조·기존값·제안값·digest·만료/사용 시각과
`CaseFieldHistory`의 필드별 변경 전후 값·생성 시각이 있다. 현재 판단 서비스는 이 모델들의
저장·조회 경로를 연결하지 않았다. `conflict_ref`는 후보를 찾는 참조, `conflict_digest`는 내용
변경을 확인하는 해시이며 서로 대체하지 않는다. 기존 모델만으로 Agent의 원래 충돌 후보 전체를
복원하는 코드도 없으므로, 기존 구조를 활용할 보관·복원 방식을 먼저 합의해야 한다.
`CaseFieldHistory.created_at`을 사실의 변경 시각으로 사용할 수 있는지도 이 연결에서 확인한다.

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

`AgentRuntime.run_planning`의 입력부터 출력까지 실제 Graph·Info·Supervisor·Review 경로로 검증한다.
현재 MVP 검증에서는 지원 자료를 빈 목록으로 전달하며 지원사업 정상 동작은 통과 조건에서 제외한다.
Agent 동작 검증에는 실제 LLM 호출 필수. 모의 응답 테스트나 `--validate-only`만으로 완료 처리 금지.
응답 재사용 비활성화와 호출별 모델·`schema_name`·HTTP 상태·최종 Review 결과 확인.

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

위 기록은 당시 입력 방식의 결과다. 현재 DB 근거 조회를 평가하려면
[`evaluate_planning.py`](../../backend/scripts/evaluate_planning.py)에 BE가 조회한 공식 근거를
포함한 `--graph-input <AgentGraphInput JSON 경로>`를 전달한다. 기본 `--case` 입력은
공식 DB 근거가 없으므로 검수 파일만 지정해도 공식 문서를 반환하지 않는다.
`--case`·`--result-input`과 동시 사용 불가. 합성 입력·호출 기록은 Git 추적에서 제외.
같은 판단인지는 Blocker 설명과 Next Action 전체(행동 코드·대상·제목·이유·확인 질문)를
digest로 비교한다. 공식 근거는 DB ID를 유지하지만 파생 근거는 실행마다 ID가 달라질 수 있어
판단 문구 비교에서는 근거 ID를 제외한다. DB 근거 보존 여부는 별도로 검증한다.
실행마다 새 runtime을 만들고 판단 재사용을 꺼서, 반복이 실제로 다시 호출하도록 한다.

이 기록으로 말할 수 없는 것: 네 입력 모두 원상복구·철거가 미확인이라 규칙 적용 후 후보가
하나뿐이었다. 여러 후보 사이의 선택이 일관적인지는 증명하지 않는다.
모델은 표본 수준의 재현성을 보장하지 않으므로 이 결과는 측정이지 보장이 아니다.

### 2026-09-29 로컬 BE 연결 검증

AI 코드 `a7c78d8`, BE 브랜치 `d5e050a` 기준. 카카오 로그인·지원사업 정상 동작은 검증 범위에서 제외.
합성 Case snapshot과 격리 MySQL의 절차 행을 새 `run_case_planning` 함수에 전달해 실제 LLM 호출.
최종 실행 16회 모두 `gpt-5.6-sol`·`xhigh`, HTTP 200. 모의 LLM 응답·판단 재사용 없음.

| 흐름 | 최종 실행 결과 |
|---|---|
| 최초 판단 | 원상복구 확인 Blocker·Next Action 생성, Review PASS |
| 신고 요건 확인 | 당시 `blocker=null`로 검증. 현재 MVP 계약은 Blocker 필수이며 해당 출력은 사용하지 않음 |
| 결과 입력 | 원상복구·철거 불필요 변경 후보 3개와 새 행동 생성, Review PASS |
| 확정값과 충돌 | `CONFLICT` 반환, 자동 변경 없이 확인 후보 보존 |
| 충돌 확인 | `CONFIRMED_CONFLICT` 출처의 변경 후보·새 행동 생성, Review PASS |
| 공식 근거 부족 | `NEEDS_MORE_INFO`·확인 질문 반환, Next Action 없음, Review PASS |

실제 HTTP `POST /cases`·`GET /cases`는 200, 저장된 Case의 재조회 일치, 중복 생성은 409 확인.
**서버 → AI → 판단 저장 → 재조회 연결은 이 검증에서 미완료.** 검증에 사용한 BE(`d5e050a`)에는
입력 근거·snapshot 생성, Agent 호출, 판단 저장 함수가 없으며 POST/GET은 Case 열만 반환. HTTP 호출 뒤 입력 이력·근거·판단 기록은
각각 0건. 위 AI 함수 직접 호출 검증은 서버 전체 연결의 통과 증거가 아님.

### 392294c 재검증 (2026-10-01)

위 2026-09-29 기록의 기준 `a7c78d8`은 **이 브랜치 이력에 없다.** 브랜치를 둘로 나눠 다시 쓰는
과정에서 빠졌고 이후 `app/agent`·`app/common`에서 9파일이 바뀌었다. 그래서 위 표는 이 브랜치
코드의 증거가 아니며, 아래가 현재 코드 기준 측정이다.

합성 Case snapshot과 검수된 절차·지원 스냅샷을 `run_case_planning`에 전달해 실제 LLM 호출.
세 역할 모두 `gpt-5.6-sol`, 판단 재사용 꺼짐. 11회 실행, 제공자 호출 35회.

| 흐름 | 최종 실행 결과 | 소요 |
|---|---|---|
| 최초 판단 (입력 4종) | `ACTION`, 원상복구 확인 Blocker·Next Action, Review PASS | 102~144초 |
| 신고 요건 확인 | `ACTION`, 식품영업 폐업신고 확인 Blocker·Next Action, Review PASS | 150초 |
| 결과 입력 (철거) | `ACTION`, 지원 요건 확인 Blocker·Next Action, Review PASS | 139초 |
| 결과 입력 (범위·철거) | 당시 한도(150/300초)로 2회 모두 `SAFE_FAILURE`, 180/420초에서는 `ACTION`·PASS | 300초 / 143초 |
| 확정값과 충돌 | `CONFLICT`, 자동 변경 없이 확인 후보 보존 | 103초 |
| 충돌 확인 | `REVIEWED_PLAN`, 확인된 값의 변경 후보와 새 행동 | 169초 |

2026-09-29 기록에서 `blocker=null`로 남아 있던 "신고 요건 확인"은, Blocker 필수 계약과 절차
확인 후보 일반화가 함께 적용되면서 근거 있는 Blocker가 나온다.

이 기록으로 말할 수 없는 것: 흐름마다 1회씩만 돌렸으므로 반복 일관성은 측정하지 않았다.

이 측정에서 호출 지연은 이랬다. Info 제공자가 503을 돌려줄 때 **120초**를 쓰고(4회 모두
120.2초로 상류 고정 타임아웃으로 보인다), 성공한 Info 호출은 최대 **102초**였다.
Supervisor·Review는 5~8초다. 당시 한도 `AGENT_LLM_TIMEOUT_SECONDS=150`·
`AGENT_RUN_DEADLINE_SECONDS=300`은 503을 한 번도 견디지 못해, 503 두 번 뒤 3회차가
한도에 걸려 `SAFE_FAILURE`로 끝났다. 2회 모두 같은 방식으로 실패했다.

이 실측에 따라 `.env.example`을 **180/420초**로 올렸다. 근거는 503 두 번 뒤 성공하는
경로가 120+120+105초이고 검수가 16초를 더 쓰기 때문이다. 호출 한도를 180초로 둔 것은
성공 호출 최대치(102초)와 150초가 너무 가까워서다. 코드 상한은 600초라 둘 다 유효하다.
세 번 모두 503이면 여전히 `SAFE_FAILURE`로 끝나는데, 그건 제공자 장애라 맞는 동작이다.

위 검증 당시에는 서버 연결과 절차 행 생성이 미완료였다. BE는 PR #47에서
`POST /cases` 뒤 백그라운드 최초 판단과 저장, `GET /cases`의 판단 결과 조회가 연결되어 있다.
BE의 [`first_judgment.py`](../../backend/app/be/services/first_judgment.py)는
`run_case_planning` 대신 `AgentRuntime.run_planning`을 직접 호출한다.
[`case.py`](../../backend/app/be/services/case.py)는 임시 `TEMP_*` 절차 3개를 생성한다.
다만 `TEMP_*`는 AI 절차 의미 코드와 연결되지 않고, BE는 절차 검수 목록에 빈 store를 넘긴다.
#53의 Agent는 이 경우 동봉 JSON을 검수 메타정보로 읽지만, 새 Case에 공식 근거를 저장하는
호출은 아직 없어 자동으로 공식 문서가 공급되지는 않는다.
코드 확인 결과이며, 서버 전체 실행 검증은 아니다.
