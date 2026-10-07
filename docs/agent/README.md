# Agent 범위

Agent는 폐업 Case의 확인된 사실과 근거로 **Blocker 1개·Next Action 1개** 판단.
현재 MVP의 정상 판단에는 근거 있는 Blocker가 항상 1개 있다.
사용자가 현실에서 실행한 결과를 입력하면 같은 Case를 다시 판단한다.
모든 정상 판단은 독립 Review를 거치며 Case 저장은 BE가 담당한다.

원상복구 범위·철거 필요 여부의 미확인은 Case의 후속 진척을 막는 조건이며, 이를 해소할
임대인 확인 행동은 실행 가능하다. 확인 행동을 할 수 있다는 이유만으로 이 Blocker를 제거하지 않는다.
일반 절차는 공식 안내에 따른 진행 상태와 준비사항 확인을 Blocker로 제시하며,
확인된 사실과 후보에 없는 차단 조건을 만들어내지 않는다.

지원사업은 MVP 실행에서 제외한다. 지원 Agent를 호출하지 않고 지원 행동·추가 질문·변경 후보를 생성하지 않는다.
기존 지원사업 코드·자료·입력 DTO는 유지한다. 폐업 절차의 선택 순서는 [Supervisor 우선순위](./supervisor.md#업무-순서-코드와-review에서-적용)를 따른다.

필드·타입·enum·NULL·기본값·관계·상태 전이는 실제 DTO·BE 모델·검증 코드가 기준이다.
[schema_table.md](../schema/schema_table.md)는 설계 배경으로 참고하며 코드와 다르면 실제 코드를 확인한다.
MVP 단순화를 이유로 제약을 완화하지 않는다.
낙관적 락은 쓰지 않는다 — Agent는 `CASE.case_version`과 이를 참조하는 버전 컬럼을 구현하지 않고,
각 결과가 BE에서 받은 같은 입력 묶음을 사용했는지는 `snapshot_id`로 확인한다.
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
Blocker·Next Action·검수 기록을 저장한다. BE 연결 작업과 후속 저장 범위는
[#56](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/56)·
[#57](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/57)에서 추적한다.

### 비슷한 필드의 역할

`CaseSnapshot`은 BE가 DB에서 읽은 Case 사실·절차 진행·근거를 Agent에 넘기는 입력 묶음이다.
DB 전체 복사본이나 별도로 저장한 snapshot 행을 뜻하지 않는다. 기존 `snapshot_id`는 어떤 입력
묶음인지, `run_id`는 어느 판단 실행인지를 식별한다. 같은 입력으로 다시 실행해도 `run_id`는
달라지며, Review 검사는 다른 실행의 결과가 섞이는 것을 거부한다.

| 필드 | 용도 |
|---|---|
| `snapshot_id` / `based_on_snapshot_id` | BE가 조립한 입력 묶음의 ID / 하위 결과가 참조하는 같은 ID. |
| `run_id` / `call_id` / `review_call_id` | Graph 실행 / 개별 구성요소 호출 / PASS를 반환한 Review 호출의 ID. |
| `trace_id` | 호출자가 선택적으로 주는 외부 추적 ID. `InvocationMeta`로 전달하며, 판단 저장 시에는 `save_reviewed_plan(trace_id=...)`에도 별도로 전달한다. |
| `input_event_id` / `client_event_id` | 서버에 저장된 입력 이벤트의 ID / 클라이언트가 부여한 이벤트 ID. `client_event_id` 전달만으로 중복 요청 방지가 보장되지는 않는다. |
| `CaseFact.updated_at` / `ProcedureProgress.updated_at` | 개별 사실의 변경 시각 / Case별 절차 진행 행의 변경 시각. 사실의 시각을 모르면 `None`을 유지하며 Case 행의 변경 시각으로 대신하지 않는다. |
| `submitted_at` / `captured_at` / `confirmed_at` | 입력 이력 시각 / snapshot 조립 시각 / 사용자 충돌 확인 시각. 서로 대신 채우는 값이 아니다. |

Trigger와 그 안의 `RedactedInput`에는 같은 의미의 `submitted_at`이 있으며,
`build_planning_input`은 저장된 입력 시각을 두 곳에 함께 넣는다.
입력 검증 조건은 [`schemas.py`](../../backend/app/agent/schemas.py), DB 값의 변환과 저장 범위는
[`case_snapshot.py`](../../backend/app/be/services/case_snapshot.py)·
[`decision_record.py`](../../backend/app/be/services/decision_record.py)를 따른다.

[`app.common.agent_data`](../../backend/app/common/agent_data.py)의 `build_known_procedure_steps`는
BE가 조회한 `ProcedureStep`·`StepDependency`·`StepEligibility` 행을 변환한다.
시간대 없는 DB 시각에는 호출자가 전달한 `db_timezone`을 적용한다. 공식 절차 자료와 지원 자료는
각각 `load_reviewed_procedure_store`·`load_reviewed_support_catalog`로 검증한다.
BE 모델에 없는 검수·조건·근거 필드를 만들어 채우지는 않는다.

### DB 검수 자료 공급

`build_reviewed_procedure_store(snapshots_by_step, known_procedure_steps=registry,
procedure_bindings=bindings)`는 DB에서 조회한 JSON 값을 기존 자료 객체로 변환한다.
`snapshots_by_step`은 **실제 DB 절차 코드 → 해당 절차의 검수 자료 묶음**이다.
자료 묶음은 기존 `ReviewedProcedureSnapshot`의 버전·생성 시각·언어와 문서 목록을 유지한다.
변환 함수는 파일·SQL을 읽지 않으며, 빈 자료·미검수·버전 혼합·중복 문서·잘못된 절차 대응을 거절한다.
만료된 검수 시각은 그대로 유지하며, 기존 Tool이 조회 기준일에 유효성을 검사한다.
`content_hash`는 수집한 원문 본문의 해시이므로 발췌문 해시로 다시 만들지 않는다.

BE 연결 순서는 **DB 자료 조회 → store 변환 → 같은 store로 Case Evidence 적재·commit
→ CaseSnapshot 생성 → 같은 store로 Agent 호출**이다. 기존
`import_reviewed_procedures()`와 BE의 Evidence CRUD·snapshot·판단 저장을 재사용한다.
Agent runtime은 빈 store를 JSON 파일로 채우지 않는다. 실제 자료 공급에는 BE 연결이 필요하다.

BE 요청: `procedure_step.reviewed_source_snapshot` JSON 컬럼(제안명) 추가와 승인 자료 이관,
실제 절차·Case 연결 및 위 호출 순서 반영. 기존 두 규칙 테이블은 스키마를 유지하며
선후 관계·적용 조건 데이터는 따로 검수해야 한다. 현재 BE 모델에는 이 컬럼이 없다.
운영 절차의 ID·코드·표시 이름을 테스트용 값으로 대신하지 않는다.

`python -m scripts.import_reviewed_procedures --case-id <ID>`는 BE 컬럼 반영 후
DB 원본을 해당 Case의 Evidence로 적재한다. 코드가 다르면
`--binding LOGICAL_CODE=DB_STEP_CODE`를 반복해 확정한 대응을 전달한다.
기존 `--source` 파일 옵션은 제거했다. 이 명령은 공통 절차 행을 생성하지 않으며,
최초 승인 JSON의 절차 표 이관은 BE 작업이다. 상세 요청은
[BE 요청사항](https://app.notion.com/p/3ef3c6661b7d80c9a697d4f39dce1841)의 JSON을 따른다.

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
(`procedure_store`)을 받는다. 절차 검수 목록이 비어 있으면 빈 채로 두며 동봉 JSON으로
채우지 않는다. 절차 원문과 근거 ID는 BE가 조회한 `CaseSnapshot.evidence_records`에서 가져오며,
DB 근거가 없으면 JSON 본문으로 대신하지 않고 빈 결과를 반환한다.
환경변수는 [`.env.example`](../../.env.example)를 따르고, 공용 runtime은 요청마다
`run_planning(AgentGraphInput)`으로 실행한 뒤 애플리케이션 종료 시 `aclose()`로 정리한다.

### 검수 절차 자료 저장·조회

공식 안내문을 수집·발췌한 뒤 개발자가 내용을 검수·승인한 자료를 사용한다.
승인된 JSON은 최초 이관 원본이다. 운영에서는 BE가 절차 테이블의 검수 snapshot을 조회하고,
해당 자료를 Case별 Evidence로 적재한 뒤 Agent에 전달한다.

최초 이관할 승인 자료는
[`reviewed-procedures.ko-KR.json`](../../backend/app/common/reviewed-procedures.ko-KR.json)에 있다.
runtime은 이 파일을 자동으로 읽지 않는다. BE 모델·DB 컬럼과 자료 이관을 반영한 뒤
기존 Case에 자료를 넣을 때는 backend 디렉토리에서 다음 명령을 실행한다.
`123`은 실제 존재하는 Case ID로 바꾼다.

```bash
.venv/bin/python -m scripts.import_reviewed_procedures --case-id 123
```

[`import_reviewed_procedures`](../../backend/app/common/agent_data.py)는 기존 BE의
`create_evidence()`로 Case별 발췌·출처·버전·해시·시각·상태를 저장한다. CLI가 전체 자료를
한 번에 commit하며 실패하면 rollback한다. 같은 ID와 내용의 재실행은 건너뛰고,
같은 ID에 다른 내용이 있으면 덮어쓰지 않는다. 새 버전은 새 근거로 남는다.
검수 시각·유효기간·검색어·절차 연결 등 검수 메타데이터는 BE가 조회한 절차 snapshot에
유지한다. Case Evidence는 발췌와 출처를 판단의 근거로 보관한다.

BE의 기존 `get_evidence_by_case_id()` → `build_case_snapshot()` 조회 결과를 Graph가 Tool에
전달한다. Tool은 승인 목록과 출처·버전·해시·발췌가 일치하는 DB 근거만 사용하며,
DB의 `evidence_id`를 그대로 반환한다. Agent는 전달받은 자료를 다시 DB에서 조회하지 않는다.

판단에 공식 근거를 공급하려면 BE가 자료 적재를 마친 뒤 snapshot을 조립하고,
실제 절차의 대응표와 함께 Agent에 전달해야 한다. 적재 함수의 commit·rollback은 호출자가 맡는다.

자료가 있지만 절차 대응이 0개이고 실행 가능한 행동 후보도 없으면 Supervisor는
`AGENT_PROCEDURE_BINDINGS_MISSING`으로 종료한다. 복구 안내는 `CONTACT_SUPPORT`이며,
사용자에게 입력 필드를 요구하거나 Supervisor·Review LLM 호출을 반복하지 않는다.
실제 사용자 정보 부족은 Info가 판단을 막는다고 표시한 미확인 조건 하나를 질문한다.

실제 절차·Case 연결, 자료 자동 적재의 진행 상황과 BE 요청·검증 기준은
[#56](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/56)에서 관리한다.

권한을 확인한 Case snapshot 제공, 검수된 변경 후보의 저장·재조회는 호출자의 책임이다.
`CONFLICT_CONFIRMED`에는 서버가 보관한 원래 충돌 후보를 전달하며, 클라이언트가 보내온
임의 후보를 그대로 신뢰하지 않는다. Agent의 `REVIEWED_PLAN`은 DB 저장 완료를 뜻하지 않는다.

### 충돌 확인

[PM의 PR #48 결정](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/48#issuecomment-5945630407)은
`CONFLICT`일 때 확인 화면을 두고, `UPDATED`는 다시 묻지 않는 것이다.
Agent는 확정값과 다른 새 입력을 `CONFLICT`로 반환하고, 확인 입력 뒤 재계획한다.
확인 시 원래 후보의 snapshot ID와 대상 필드의 현재 상태·값을 검사하며,
사용자가 선택하기 전에는 충돌하는 값을 Case에 반영하지 않는다.

`conflict_ref`는 후보를 찾는 참조, `conflict_digest`는 내용 변경을 확인하는 해시이며
서로 대체하지 않는다. 호출자는 소유권·만료·중복 사용을 검증한 뒤 서버에서 복원한 원래 후보를
`build_conflict_input()`에 전달해야 한다. 후보 보관·복원과 사용자 확인 연결, 실패 상태 구분의 진행 상황은
[#57](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/57)에서 관리한다.

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
- **근거 조회:** 실제 절차·지원사업 식별자와 개발자가 내용을 검수·승인한 자료만 사용한다.
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
코드의 증거가 아니며, 아래는 `392294c` 기준 측정이다.

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

위 검증은 당시 Agent 직접 호출의 결과이며, 서버 전체 연결의 통과 증거는 아니다.
이후 BE 연결 작업과 서비스 전체 검증 결과는
[#56](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/56)·
[#57](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/57)에서 추적한다.

### 2026-10-07 폐업 우선순위 검증

`feature/agent-procedure-db-source`에서 임대인 확인 우선, 선행·진행 중 절차 정렬,
지원 분석 호출 제외와 결과 입력의 사실 근거 검증을 보완했다.
전체 테스트 330개(격리 MySQL 포함)와 변경 파일 Ruff가 통과했다.

실제 호출은 격리 MySQL에 검수 자료 4건과 Case 근거를 저장·재조회한 뒤 실행했다.
BE 미구현 컬럼 `reviewed_source_snapshot`은 테스트 DB에만 추가했다. 운영 DB 반영이나
결과 mutations 저장·재조회까지 완료했다는 증거는 아니다.
모델은 `gpt-5.6-sol`·`xhigh`, 판단 캐시는 비활성화했고 지원 분석 호출은 없었다.

| 입력 | 실제 결과 |
|---|---|
| 동일한 최초 판단 2회 | 137초·106초, 모두 Review PASS. Blocker·Next Action이 같고 임대인 확인을 선택 |
| 원상복구 범위 전체·철거 필요 확인 결과 | 263초, Review PASS. 두 사실의 변경 후보와 식품영업 폐업신고 준비사항 확인 행동 반환. Info HTTP 503 한 번 후 재시도 성공 |
| 원상복구 작업·철거 불필요를 다른 표현으로 입력 — 수정 전 | 329초, Info 3회 후 `STRUCTURED_OUTPUT_FAILED`. Supervisor·Review에 도달하지 않음 |
| 같은 결과 입력 — 사실 근거 검증 보완 후 2회 | 185초·353초, 모두 Review PASS. 원상복구 범위·작업·철거의 `NOT_REQUIRED` 후보 3건과 식품영업 폐업신고 준비사항 확인 행동 반환. 근거가 불충분한 절차 완료 후보는 각각 1회·2회 거절한 뒤 재시도 성공 |
| 같은 결과 입력 — 절차 진행 안내까지 보완한 최종 코드 | 157초, Review PASS. 같은 사실 후보 3건과 식품영업 폐업신고 준비사항 확인 행동 반환. Info·Supervisor·Review 각 1회, 모두 HTTP 200이며 재시도 없음 |

위 실패를 재현한 뒤 기존 `info_agent/agent.py`의 근거 표현 목록을 보완했다.
`원상복구 범위는 없고`, `원상복구 작업은 필요하지 않습니다`, `철거도 필요하지 않습니다`를
각 필드의 `NOT_REQUIRED` 근거로 인정한다. 한 필드의 표현으로 다른 필드나 작업 완료를 추정하지
않으며, 조건문·질문·가정·이중 부정과 짧게 인용해 부정을 숨기는 입력은 회귀 테스트로 차단했다.
절차 진행 후보의 인용문에는 절차를 식별하는 말과 실행 상태가 함께 있어야 한다는 기존 검증
조건도 최초 지시와 재시도 안내에 명시했다. 거절된 진행 후보 때문에 유효한 사실 후보나 절차
분석까지 삭제하지 않도록 안내한다.

결과 입력 2회의 행동 코드·대상·사실 변경 후보는 같았지만, Info의 `RELEVANT` /
`POSSIBLY_RELEVANT` 분류가 달라 Blocker 설명과 확인 질문은 달랐다. 같은 검증 상태·후보의
우선순위를 고정한 것이며 자유 입력부터 최종 문구까지 완전히 동일함을 보장하지 않는다.

### 2026-10-07 열린 PR 통합 검증

Agent `75af1c5`와 당시 `develop` `73b9f5d`를 기준으로 별도 임시 작업 트리에서 확인했다.
#63(`8ea1414`)·#67을 함께 병합한 상태에서 백엔드 테스트 330개가 통과했다.
FE 화면 동작과 운영 DB 저장·재조회까지 검증한 결과는 아니다.

#65(`07aaf75`)를 추가하면 `app/agent/runtime.py`와 `app/common/agent_data.py`에서 충돌한다.
DB 자료 변환 함수는 유지하고 저장 함수의 BE 이관을 반영해 충돌을 풀어도,
`test_agent_service.py`·`test_reviewed_procedure_db.py`·`test_reviewed_procedure_import.py`가
이동·삭제된 이름을 import해 테스트 수집 오류 3건이 발생했다.

TODO: #65가 반영된 develop을 받은 뒤 `scripts/import_reviewed_procedures.py`와 적재 테스트의
저장 함수 참조를 `app.be.services.reviewed_procedure`로 바꾼다. 삭제된 `EmptyProcedureStore`
참조는 기존 빈 `InMemoryReviewedProcedureStore`로 대체하고, Case 생성 시 공식 근거 자동 적재에
맞게 합성 테스트 준비와 검증을 조정한다. 합본 테스트를 다시 통과하기 전에는 #65와의 호환 완료로
보지 않는다. 새 BE 서비스가 없는 현재 develop에 미래 import 경로만 먼저 적용하지 않는다.
