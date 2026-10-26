# Agent 범위

Agent는 폐업 Case의 확인된 사실과 근거로 **전체 Blocker와 우선 한 가지·다음 행동 또는 확인 질문**을 판단한다.
추적 대상이 모두 완료되면 세금 후속 안내와 함께 `COMPLETED`를 반환한다.
`ACTION`·`NEEDS_MORE_INFO`에는 전체 유효 Blocker 목록과 그중 우선 1개가 있다.
`COMPLETED`에는 Blocker·다음 행동·확인 질문이 없다.
사용자가 현실에서 실행한 결과를 입력하면 같은 Case를 다시 판단한다.
모든 정상 판단은 독립 Review를 거치며 Case 저장은 BE가 담당한다.

현재 UI 연동 범위는 상황 진단·오늘 할 일·원상복구 결과 입력이다.
홈에는 판단마다 지금 할 일 한 개를 제공하며 날짜별 할 일 목록은 만들지 않는다.
진행률 %·D-day 숫자·사용자의 서류 보유 여부는 Agent가 생성하지 않는다.
전체 종료는 적용 대상 절차의 진행 기록과 근거로 판단한다.

사용자의 자연어 진행 보고를 LLM이 구조화하고, 원문 인용·상태 전이·Review를 통과한 변경만 반환한다.
모호한 보고는 확인 전 보류하며, 신고 제출·접수와 기관 처리 완료를 구분한다.
명시적 상태 선택도 지원하며, 같은 절차의 자연어 보고와 다르면 명시적 선택을 우선한다.

원상복구 범위·철거 필요 여부의 미확인은 Case의 후속 진척을 막는 조건이며, 이를 해소할
임대인 확인 행동은 실행 가능하다. 확인 행동을 할 수 있다는 이유만으로 이 Blocker를 제거하지 않는다.
일반 절차는 공식 안내에 따른 진행 상태와 준비사항 확인을 Blocker로 제시하며,
확인된 사실과 후보에 없는 차단 조건을 만들어내지 않는다.
요건 미확인·실행 전·제출 후 처리 대기를 구분하고, 제출한 신고를 미제출 상태로 설명하지 않는다.
Supervisor는 유효한 행동·질문 후보에서 우선 항목을 고르며 질문 후보가 있다는 이유만으로 `NEEDS_MORE_INFO`를 강제하지 않는다.

지원사업은 MVP 실행에서 제외한다. 지원 Agent를 호출하지 않고 지원 행동·추가 질문·변경 후보를 생성하지 않는다.
미사용 지원 실행기는 제거하고 BE 호환에 필요한 자료형만 유지한다. 폐업 절차의 선택은 [Supervisor](./supervisor.md)를 따른다.

필드·타입·enum·NULL·기본값·관계·상태 전이는 실제 DTO·BE 모델·검증 코드가 기준이다.
[schema_table.md](../schema/schema_table.md)는 설계 배경으로 참고하며 코드와 다르면 실제 코드를 확인한다.
MVP 단순화를 이유로 제약을 완화하지 않는다.
낙관적 락은 쓰지 않는다 — Agent는 `CASE.case_version`과 이를 참조하는 버전 컬럼을 구현하지 않고,
각 결과가 BE에서 받은 같은 입력 묶음을 사용했는지는 `snapshot_id`로 확인한다.
일괄 충돌 확인에서는 원래 snapshot ID와 당시 사실·절차 진행·근거 전체를 현재 입력과 대조한다.
조회 시각·목록 순서만 다른 것은 상태 변경으로 보지 않는다.

**규칙은 문서가 아니라 코드에 둔다.** 각 문서는 해당 구성요소의 사실만 담고 코드를 가리킨다.
문서와 코드가 다르면 코드가 맞다.

| 구성요소 | 문서 | 코드 |
|---|---|---|
| 최종 판단(Blocker·Next Action) | [supervisor.md](./supervisor.md) | `supervisor/agent.py` |
| 사실 추출·충돌 감지 | [info-agent.md](./info-agent.md) | `info_agent/agent.py` |
| 절차 조회·실행 가능 판정 | [procedure-tool.md](./procedure-tool.md) | `procedure_tool/` |
| 지원사업 호환 자료형(MVP 실행 제외) | [support-agent.md](./support-agent.md) | `support_agent/models.py` |
| 독립 검수 | [review-tool.md](./review-tool.md) | `review_tool/tool.py` |
| 유해 조력·근거·개인정보·상태 차단 | [guardrails.md](./guardrails.md) | `content_safety.py`, `claim_safety.py`, `guardrails.py`, `projection.py`, `enrichment.py` |

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
`SAFE_FAILURE` / `CRISIS_SUPPORT` 중 하나다. 복수 Blocker·일괄 충돌·`COMPLETED`의 계약은
[`schemas.py`](../../backend/app/agent/schemas.py)와 아래 연동 경계를 따른다.

BE에 제공하는 공용 호출 함수는 [`app.common.agent_service.run_case_planning`](../../backend/app/common/agent_service.py)이다.
저장된 업종·복구 상세의 모델용 복사본은 [BE의 `redact()`](../../backend/app/be/services/redaction.py)로 가린다.
같은 규칙을 재사용하므로 #109가 선행해야 한다. 원 Case·충돌 선택값·검수 해시는 바꾸지 않으며 공식 원문은 가리지 않는다.
`build_planning_input`은 저장된 입력 이벤트의 ID·시각·비식별 문장과 Case snapshot으로
`CASE_CREATED` 또는 `RESULT_SUBMITTED` 입력을 조립한다. `build_conflict_input`은 기존 단일 채택과
원본 후보·전체 선택·기준 snapshot·원 보고를 받는 일괄 확인을 모두 지원한다.
일괄 입력은 `build_conflict_input(conflicts=..., selections=..., conflict_snapshot=..., pending_input=...)`으로 조립한다.
새 `CONFLICT`의 `pending_input`도 함께 보관·복원한다. 원래 보고를 생략하면 확인 입력이 거절된다.

현재 FE 결과 입력은 자유서술을 유지한다. `RedactedInput.procedure_reports`의
`ProcedureProgressReport`는 선택 입력이며, 선택 UI·코드값 전송 방식은 FE·BE와 추가 합의 후 연결한다.
다음은 신고서를 제출했지만 기관 처리 완료는 확인하지 않은 선택값의 모양이다. 절차 ID·코드는 실제 등록값을 사용한다.

```json
{
  "procedure_step": {"procedure_step_id": 1, "step_code": "FILE_FOOD_SERVICE_CLOSURE"},
  "status": "IN_PROGRESS",
  "requirements_confirmed": true,
  "submitted": true
}
```

`status`는 `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED`다. `COMPLETED`는 사용자가 해당 절차 전체의
처리 완료를 확인했다고 선택한 값이며, 직원·보험 집계 절차는 대상 전원·가입기관 전체를 뜻한다.
이 경로를 연결할 때 BE는 선택값을 원 이벤트·절차 참조와 함께 Agent DTO로 전달하고
Review가 승인한 변경만 저장한다. 선택값을 보내지 않아도 기존 자연어 보고를 처리한다.

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

### 절차 데이터 공급

자료 적재·조회는 BE가 맡으며, Agent는 전달받은 절차 목록·검수 자료·Case 근거를 사용한다.
기존 자료 적재 경로는 **승인 JSON → BE Evidence 저장 → DB snapshot 조회 → Agent 전달**이다.

실제 등록 데이터는 [cafe.py](../../backend/app/agent/procedure_tool/cafe.py)의
`build_cafe_procedure_steps(step_ids)`와 `build_cafe_reviewed_snapshot()`으로 만든다.
DB가 발급한 8개 절차 ID를 넣고 `model_dump(mode="json")`으로 전달할 수 있다.
검수 자료는 공식 원문과 대조한 고정 버전이며 Agent 요청 중 수집하지 않는다.

BE는 이 DTO 데이터를 저장·조회하고 기존 `load_reviewed_procedure_store`에 공급한다.
테이블 이름이나 아직 없는 컬럼을 Agent 계약의 근거로 삼지 않는다.
공식자료 공유 저장과 Case별 참조, 실제 절차·선후 관계·적용 조건 등록도 BE가 담당한다.

`procedure_bindings`의 키는 AI의 기존 절차 의미 코드, 값은 BE의 실제 `ProcedureStepRef`다.
예를 들어 `"FILE_FOOD_SERVICE_CLOSURE"`에 BE에서 조회한 식품영업 폐업 절차의 ID·코드를 연결한다.
행동 대상·진행 상태·근거 조회에는 BE 코드가 그대로 남는다. `TEMP_*` 이름이나 절차명으로
의미를 추정하지 않으며, 다른 절차에 같은 ID·코드를 중복 연결하거나 미등록 대상을 연결하면 거부한다.
`run_case_planning`의 대응표 인자는 필수다. 값으로 `None`을 넘기면 등록된 DB 코드가 AI 의미
코드와 정확히 같은 항목을 연결하고, `{}`를 넘기면 아무 절차도 연결하지 않는다.
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

### Agent 테스트

backend 디렉토리에서 모의 회귀 검사를 실행한다. 합성 snapshot과 모의 모델을 사용하며 실제 LLM이나 MySQL을 호출하지 않는다.

```bash
PYTHONPATH=. python -m pytest tests --ignore=tests/test_reviewed_procedure_db.py -q
```

`test_reviewed_procedure_db.py`는 testcontainers로 격리 MySQL을 생성하는 별도 통합 검사다.
[Agent CI](../../.github/workflows/agent-ci.yml)는 `develop` 대상 PR에서 위 모의 회귀 검사만 실행한다.
실제 모델 평가는 별도 스크립트로 실행하며 모의 검사 통과로 대신하지 않는다.
자료 로더의 무결성·저장·새 세션 재조회·실패 시 rollback과 Agent 입력/상태/검수 제약을 구분해 검사한다.

### 검수 절차 자료 저장·조회

공식 안내문을 수집·발췌한 뒤 사람이 공식 원문과 대조해 검수·승인한 자료를 사용한다.
BE의 자료 적재 함수는 승인 JSON을 읽어 공식 문서를 Case별 Evidence로 적재한다.
이후 DB에서 조립한 Case snapshot과 승인 목록을 Agent에 전달한다.

승인 자료는
[`reviewed-procedures.ko-KR.json`](../../backend/app/common/reviewed-procedures.ko-KR.json)에 있다.
runtime은 이 파일을 자동으로 읽지 않는다. 자료 버전 변경 후 기존 Case에 재적재할 때는
backend 디렉토리에서 다음 명령을 실행한다. 제안 DB 컬럼 추가 없이 현재 BE 구조에서 실행된다.
`123`은 실제 존재하는 Case ID로 바꾼다.

```bash
.venv/bin/python -m scripts.import_reviewed_procedures --case-id 123
```

별도 승인 JSON을 사용할 때는 `--source <파일 경로>`를 지정한다. 재적재는 문서 근거를 저장하는
작업이므로 절차 대응표를 받지 않으며 공통 절차 행도 생성하지 않는다.

[`import_reviewed_procedures`](../../backend/app/be/services/reviewed_procedure.py)는 기존 BE의
`create_evidence()`로 Case별 발췌·출처·버전·해시·시각·상태를 저장한다. CLI가 전체 자료를
한 번에 commit하며 실패하면 rollback한다. 같은 ID와 내용의 재실행은 건너뛰고,
같은 ID에 다른 내용이 있으면 덮어쓰지 않는다. 새 버전은 새 근거로 남는다.
검수 시각·유효기간·검색어·절차 연결 등 검수 메타데이터는 BE가 읽어 전달한 승인 목록에
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
모든 항목의 선택을 모아 한 번 재판단하고 Review를 거친다. 채택한 항목만 변경 후보로 만들며,
전부 기존 값 유지도 변경 0개로 재판단한다. 거절한 원문을 새 결과 입력으로 다시 추출하지 않는다.
`ACTION`·`NEEDS_MORE_INFO` 모두 채택한 충돌의 정확한 값을 빠짐없이 변경 후보에 포함해야 한다.
검수할 수 없으면 전체 실패로 반환한다. BE는 검수 성공 후 변경 저장과 충돌 해결을 함께 반영하고,
실패하면 둘 다 반영하지 않는다. 같은 충돌 확인 실행에서는 새 `CONFLICT`를 반환하지 않는다.
원래 snapshot ID와 당시 사실·절차 진행·근거 전체를 현재 상태와 대조하고,
사용자가 거절한 항목도 원본 무결성·현재 상태를 검증한다. 기준 내용이 달라졌으면 기존 확인을 거부한다.
조회 시각·목록 순서만 다른 것은 상태 변경으로 보지 않는다. 실제 저장 직전 재검사는 BE 책임이다.

`conflict_ref`는 후보를 찾는 참조, `conflict_digest`는 내용 변경을 확인하는 해시이며
서로 대체하지 않는다. 호출자는 소유권·결정 상태·중복 처리를 검증한 뒤 서버에서 복원한 원래 후보를
`build_conflict_input(conflicts=..., selections=..., conflict_snapshot=..., pending_input=...)`에 전달한다.
이 함수는 기존 단일 채택도 지원한다. 현재 열린 [BE PR #108](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/108)에는
결정 접수 API가 구현돼 있으며, 만료 기한 없이 `status`·`decided_at`으로 결정 상태를 관리한다.
Agent 호출·당시 원본 복원·판단 성공 후 최종 저장 연결은 후속 작업이다.
후보 보관·복원과 사용자 확인 연결, 실패 상태 구분의 진행 상황은
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
- **근거 조회:** 실제 절차·지원사업 식별자와 공식 원문 대조를 거쳐 검수·승인한 자료만 사용한다.
- **한 판단 지점:** Supervisor가 Blocker와 Next Action을 결정한다. 하위 Agent·Tool은 분석과 근거만 반환한다.
- **필수 Review:** 모든 정상 판단을 독립 검수한다.
- **재계획:** 같은 Case의 행동 결과를 반영한 후보와 새 판단을 만든다.
- **충돌 확인:** 확정값과 새 입력이 다르면 사용자 선택 전 반영하지 않는다.
- **안전 실패:** 근거 부족·Review 실패를 성공으로 바꾸지 않고 검수 전 초안을 내보내지 않는다.

## 제외 기능

- 폐업 로드맵·서류 보관함·사용자 서류 점검·누락 보완 및 재점검·제출 준비 파일 다운로드·작업 이력 화면
- Chroma·임베딩·S3·Wiki miss RAG와 새 지식 관리 화면
- 공식 문서 자동 수집·갱신·첨부파일 파싱·배치
- 일반화된 자율 Tool 선택 계획과 Agent 구성 확장
- 비용·반송률 대시보드, 관측된 결함과 무관한 성능·정규식 고도화
- 카페 외 업종·지원사업 범위 확대, 세금 신고 완료 추적

Review·충돌 보호·근거·개인정보 검증은 축소하지 않는다.
폐업 결정·최적 폐업일·법률/세무/자격의 최종 판단·신청/계약/외부 연락 실행은
[팀 공통 제외 범위](../../CLAUDE.md)를 따른다.

## 검증 기준

모의 테스트는 입력·상태·근거·검수 제약과 호출 순서를 검사한다. 실제 모델의 의미 판단과
BE 저장·재조회는 별도로 검증한다. 모의 테스트나 `--validate-only` 통과를 서비스 완료로 표시하지 않는다.

실제 모델 평가는 `scripts/evaluate_planning.py`의 `--suite core`와 `--suite safety`를 수동 실행한다.
core는 정상 처리·절차 상태 선택·충돌 선택·전체 완료·안전 요청을 포함한 23종이며,
각 사례를 3회 실행해 69회 모두 기대 판정을 만족해야 한다. safety는 안전 검사 13종이다.

```bash
python -m scripts.evaluate_planning --suite core --repeats 3 \
  --procedure-snapshot <검수 DTO 직렬화본> --output <새 임시 경로>
```

평가는 코드·프롬프트·데이터셋 digest, 실제 모델/effort, 자료 버전, 호출·판정·시간을 기록한다.
실패·중단은 보존하고 기대 판정이 틀리거나 실행 중 코드가 바뀌면 실패로 종료한다.
원문·응답 전문·인증정보는 기록하지 않는다. 모의 테스트 수나 단일 성공으로 실제 모델 반복 검증을 대체하지 않는다.

DB 근거 조회를 평가하려면
[`evaluate_planning.py`](../../backend/scripts/evaluate_planning.py)에 BE가 조회한 공식 근거를
포함한 `--graph-input <AgentGraphInput JSON 경로>`를 전달한다. 기본 `--case`·`--dataset` 입력에는
`--procedure-snapshot`으로 지정한 검수 파일의 문서를 공식 근거로 붙인다.
`--graph-input`으로 준 입력에는 붙이지 않는다.
`--case`·`--result-input`과 동시 사용 불가. 합성 입력·호출 기록은 Git 추적에서 제외.
같은 판단인지는 Blocker 설명과 Next Action 전체(행동 코드·대상·제목·이유·확인 질문)를
digest로 비교한다. 공식 근거는 DB ID를 유지하지만 파생 근거는 실행마다 ID가 달라질 수 있어
판단 문구 비교에서는 근거 ID를 제외한다. DB 근거 보존 여부는 별도로 검증한다.
실행마다 새 runtime을 만들고 판단 재사용을 꺼서, 반복이 실제로 다시 호출하도록 한다.

기존 API 평가는 `scripts/evaluate_case_api.py`가 격리 MySQL에서 Case 생성→조회→새 DB 세션 읽기를
확인한다. 실제 모델·Docker가 필요하다. 새 결과 제출·충돌 확인·완료 저장 API까지 검증하는 도구는 아니다.

연동 진행 상황과 미완료 작업은 README에 중복 기록하지 않고
[#56](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/56)·
[#57](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/57)과
[현재 AI 이슈](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues?q=is%3Aissue%20is%3Aopen%20AI)에서 추적한다.
연결 여부는 실제 BE 라우터·서비스와 Agent 호출 코드로 확인한다.
Agent 함수가 구현됐다는 이유로 저장·재조회까지 완료됐다고 표시하지 않는다.

실패 응답은 [`SafeFailureOutcome`](../../backend/app/agent/schemas.py)을 따른다.
`RETRY`는 재시도 가능·빈 요청 필드, `RESUBMIT_INPUT`은 재시도 불가·입력할 필드 목록,
`CONTACT_SUPPORT`와 `NONE`은 재시도 불가·빈 요청 필드다. 오래된 충돌 확인의
`STALE_CONFLICT_CONFIRMATION`만 `RESUBMIT_INPUT`의 빈 필드를 허용한다.
필드별 안내문을 만드는 사용처 없는 내부 함수는 유지하지 않으며, 요청 필드 자체의 계약은 보존한다.
