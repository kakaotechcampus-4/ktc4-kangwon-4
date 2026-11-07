# 스키마 (테이블 정의)

전체 구조는 6개 도메인으로 나뉩니다. (Agent팀 ERD 기준 반영)

```
[1. 사용자/케이스]         서비스의 기본 단위 (누가, 어떤 폐업 건을)
        │
        ├──[2. 판단 로그 & 블로커]      에이전트가 뭘 판단했고, 지금 뭐가 막혔는지
        │
        ├──[3. 절차 마스터 데이터]      폐업 절차 전체 목록과 순서/조건 규칙 (공통, Case 무관)
        │        │
        │        └──[4. Case별 절차 진행상황]   위 마스터를 Case마다 실제로 어디까지 했는지
        │
        ├──[5. 지원사업]               희망리턴패키지 등 지원사업 매칭·신청 현황
        │
        └──[6. 근거·충돌·판단기록]      Agent 판단의 근거, 값 충돌, 판단·리뷰 결과
```

> 서류함(올린 서류 목록·점검 결과)은 DB가 아니라 서류 폴더(`AGENT_DOCUMENT_DIR/<Case UUID>/case_documents.json`) 파일에 저장합니다(#159). 그래서 ERD에 서류함 테이블은 없습니다.

> 제약조건(NOT NULL·DEFAULT·UNIQUE)은 운영 DB를 만드는 `backend/sql/001_schema.sql` 기준으로 맞췄습니다.
> DEFAULT가 없는 필드는 DB에 기본값이 없고, 저장할 때 코드가 값을 채웁니다.

---

## 1. 사용자/케이스

서비스에 로그인한 사용자와, 그 사용자가 진행 중인 폐업 건(Case) 하나를 표현합니다.
Case 하나가 이 서비스의 핵심 작업 단위이고, 나머지 모든 테이블은 결국 Case를 중심으로 붙습니다.

```
MEMBERS ──1:1──► CASE ──1:N──► CASE_FIELD_HISTORY
                              (CASE 필드 단위 변경 감사 추적)
```

### MEMBERS

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| oauth_id | VARCHAR | UK | NOT NULL, UNIQUE | `"kakao_3928471029"` | 카카오 회원번호 |
| nickname | VARCHAR | | NOT NULL | `"승준카페"` | 카카오 닉네임 |
| refresh_token | VARCHAR | | NULLABLE | `"eyJhbGciOiJIUzI1NiIs..."` | |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-01 10:23:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-05 14:02:00` | |

### CASE

사용자 한 명이 진행하는 폐업 건 하나를 의미함.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| member_id | BIGINT | FK, UK | NOT NULL, UNIQUE | 1 | 회원 한 명당 Case 하나 |
| store_name | VARCHAR(50) | | NULLABLE | `"강원 커피"` | 화면 표시용 가게 이름. AI 판단에 쓰지 않음 |
| business_type | VARCHAR | | NOT NULL | `"CAFE"` | 가입 때는 업종 코드 `CAFE`(개인·프랜차이즈 카페)/`RESTAURANT`(다른 음식점)만 받음. 가입 뒤 AI가 바꾸면 다른 글자일 수 있음 |
| franchise_status | BOOLEAN | | NOT NULL | `false` | |
| employee_count | INT | | NULLABLE | `2` | |
| had_employees | BOOLEAN | | NULLABLE | `true` | 직원을 고용한 적이 있는지. "지금"이 아니라 "있었던 적"이다 — 지금 0명이어도 퇴직금 정산이 남아 있을 수 있다. `NULL`은 "안 물어봄"이고 AI에 모름으로 넘어간다 |
| pension_enrolled | BOOLEAN | | NULLABLE | `true` | 이 사업장의 국민연금 가입 이력. 이미 탈퇴했어도 `true` |
| health_insurance_enrolled | BOOLEAN | | NULLABLE | `true` | 이 사업장의 건강보험 가입 이력. 이미 탈퇴했어도 `true` |
| employment_insurance_enrolled | BOOLEAN | | NULLABLE | `true` | 이 사업장의 고용보험 가입 이력. 이미 종료했어도 `true` |
| industrial_accident_insurance_enrolled | BOOLEAN | | NULLABLE | `true` | 이 사업장의 산재보험 가입 이력. 이미 종료했어도 `true`. 보험 네 칸은 같이 받아야 한다 — 넷 중 하나라도 `true`면 보험 신고 절차가 "해당", 넷 다 `false`여야 "해당 없음", 섞이면 "모름"이다 |
| has_business_loan | BOOLEAN | | NULLABLE | `false` | 사업 대출이 남아 있는지. 가입 때 사장님이 입력. `null`이면 안 물어봄 |
| has_service_contracts | BOOLEAN | | NULLABLE | `true` | 배달앱·카드단말기 등 해지할 서비스 계약이 있는지. 가입 때 사장님이 입력. `null`이면 안 물어봄 |
| case_status | ENUM | | NOT NULL, DEFAULT `IN_PROGRESS` | `IN_PROGRESS` | `IN_PROGRESS` / `COMPLETED`. 사장님이 부가세 폐업 확정신고(체크 항목 `vat_submission`)를 체크하면 `COMPLETED`, 풀면 `IN_PROGRESS`. `COMPLETED`면 결과 제출·충돌 결정을 받지 않는다(409) |
| lease_status | ENUM | | NOT NULL | `LEASED_PAID` | `LEASED_PAID`/`LEASED_FREE`/`OWNED` |
| restoration_clause | ENUM | | NOT NULL, DEFAULT `UNKNOWN` | `EXISTS` | `EXISTS`/`NOT_EXISTS`/`UNKNOWN` — 임대차계약서에 원상복구 조항이 있는지. 가입 때 사장님이 입력. AI가 채우는 `restoration_*`(진행·범위)와 다른 값 |
| restoration_status | ENUM | | NOT NULL, DEFAULT `UNKNOWN` | `UNKNOWN` | `UNKNOWN`/`NOT_STARTED`/`IN_PROGRESS`/`COMPLETED`/`NOT_REQUIRED` — Case 생성 직후 `UNKNOWN`으로 시작, `restoration_scope` 확정 후 나머지 값으로 전환 |
| restoration_scope | ENUM | | NOT NULL, DEFAULT `UNKNOWN` | `FULL` | `UNKNOWN`/`PARTIAL` / `FULL` / `NOT_REQUIRED` |
| restoration_scope_detail | VARCHAR | | NULLABLE | `"바닥재·전기배선까지 철거 필요"` | nullable, 구체적인 원상복구 범위 자연어 기록 |
| demolition_required | ENUM | | NOT NULL, DEFAULT `UNKNOWN` | `REQUIRED` | `UNKNOWN`/`REQUIRED` / `NOT_REQUIRED` |
| support_approved | BOOLEAN | | NULLABLE | `true` | 사장님이 알려 준 점포철거비 **1차 적격심사** 결과. `true` 통과 / `false` 탈락 / `null` 아직 모름. AI가 판단한 지원 자격이 아니고, 뒤의 정산 검토·비용 지급과도 다름 |
| support_approved_at | DATETIME | | NULLABLE | `2026-10-22 15:00:00` | 심사 결과를 마지막으로 알려 준 시각(KST). 기록 탭의 "승인 결과를 알려주셨어요" 시각 |
| planned_closure_date | DATE | | NULLABLE | `2026-12-31` | nullable |
| planned_closure_month | VARCHAR(7) | | NULLABLE | `2026-12` | 날짜를 못 정했을 때의 예상 달. `planned_closure_date`와 같이 오면 422로 거절한다. 가게 등록 때만 받고 AI 대화로는 저장하지 않는다 |
| completed_at | DATETIME | | NULLABLE | `NULL` | 폐업 정리를 마친 시각(KST). 진행 중이면 NULL |
| closure_date | DATE | | NULLABLE | `2026-10-31` | 통합 폐업 신고 화면에서 확인한 **실제 폐업일**. 가입 때 예상일(`planned_closure_date`)과 별개. AI 판단에 쓰지 않음 |
| closure_reason | ENUM | | NULLABLE | `BUSINESS_SLUMP` | 폐업 사유. `BUSINESS_SLUMP`(사업 부진) / `PERSONAL`(개인 사정) / `OTHER`(기타) |
| road_address | VARCHAR(200) | | NULLABLE | `"서울 마포구 망원로 52 (망원동)"` | 가게 도로명 주소(주소 찾기로 고름). AI에 넘기지 않음 |
| address_detail | VARCHAR(100) | | NULLABLE | `"1층"` | 상세 주소. 없을 수 있음 |
| deposit_return_result | ENUM | | NULLABLE | `PARTIAL` | 보증금 반환 결과. `FULL`(다 받음) / `PARTIAL`(일부 빼고 받음) / `NONE`(아직 못 받음). 리본은 기록만 하고 판단하지 않음 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-01 10:24:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-10 09:11:00` | |

### CASE_FIELD_HISTORY

CASE의 필드 단위 변경 이력 (감사 추적용). `CASE_HISTORY`(발화·이벤트 원본)와 별개로, "필드 값이 무엇에서 무엇으로 바뀌었는지"만 정밀 추적.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| case_history_id | BIGINT | FK | NULLABLE | 7 | 이 변경이 나온 제출(CASE_HISTORY). 이 값이 있어야 "이번 판단에서 뭐가 바뀌었나"를 골라낼 수 있다 |
| canonical_field | VARCHAR | | NOT NULL | `"restoration_scope"` | 변경된 필드명 |
| source_evidence_refs | JSON | | NULLABLE | `["input:9f3e7d"]` | 이 변경의 근거 evidence_id 목록. 다음 판단 스냅샷에서 이 필드의 근거로 되돌려 준다 |
| before_value | VARCHAR | | NULLABLE | `"UNKNOWN"` | 변경 전 값 |
| after_value | VARCHAR | | NULLABLE | `"FULL"` | 변경 후 값. 비움으로 정정한 경우 NULL |
| source | VARCHAR | | NOT NULL ⚠️ 값 목록 P0 미정 | `"USER_INPUT"` | 변경 출처 |
| reason | VARCHAR | | NULLABLE | `"사용자가 원상복구 범위 확정함"` | 변경 사유 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 09:11:00` | |

---

### CASE_CHECKLIST

사장님이 직접 체크한 로드맵 항목의 **지금 상태**. 줄이 있으면 체크됨, 체크를 풀면 줄을 지운다. 체크하고 푼 이력은 `CASE_CHECKLIST_HISTORY`에 따로 남는다. 체크할 수 있는 항목은 AI 로드맵(`app/agent/roadmap.py`)의 `CHECKLIST_IDS`다. 공식 절차 진행 상태는 `CASE_PROCEDURE_STEP`이 따로 갖는다.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL, UNIQUE(case_id, task_id) | 1 | |
| task_id | VARCHAR(50) | | NOT NULL | `"dispose_stock"` | 체크한 항목 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-10-30 10:00:00` | 체크한 시각 |

### CASE_CHECKLIST_HISTORY

로드맵 항목을 체크하고 푼 이력. 상태가 실제로 바뀔 때만 한 줄씩 쌓고 지우지 않는다(같은 요청을 두 번 보내면 쌓이지 않는다). 기록 탭이 읽는다.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| task_id | VARCHAR(50) | | NOT NULL | `"dispose_stock"` | 체크하거나 푼 항목 |
| completed | BOOLEAN | | NOT NULL | `true` | `true` 체크함 / `false` 체크를 풂 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-10-30 10:00:00` | 체크하거나 푼 시각 |

### CASE_DOCUMENT_HISTORY

서류를 올리고 점검한 이력. 한 줄씩 쌓고 지우지 않는다. 기록 탭이 읽는다. 서류 목록 자체는 서류 폴더의 JSON 파일(#159)에 있는데, 거기에는 올린 시각이 없고 서류를 빼면 줄이 사라져서 기록용으로 따로 남긴다. 빼기·확인은 남기지 않는다.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| action | ENUM | | NOT NULL | `UPLOADED` | `UPLOADED` 서류를 올림 / `CHECKED` 정산 서류 점검을 통과함(`COMPLETE`일 때만) |
| document_kind | VARCHAR(30) | | NULLABLE | `"TRANSFER"` | 올린 순간의 서류 종류(문서 Tool의 종류 코드). 나중에 종류를 고쳐도 바꾸지 않는다. 점검이면 NULL |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-11-04 10:00:00` | 올리거나 점검한 시각 |

## 2. 판단 로그 & 블로커

에이전트가 사용자 발화나 배치 작업을 처리하면서 내린 판단을 기록하고,
그 판단으로 인해 "지금 막혀서 못 넘어가는 것(Blocker)"이 생기면 별도로 추적합니다.
CASE_HISTORY와 BLOCKER는 서로를 생성/해소 관계로 참조합니다.

```
CASE_HISTORY ──created_from──► BLOCKER
   ▲                              │
   └────── resolved_from ─────────┘
   (다음 로그가 이전 blocker를 해소시킴)

CASE_HISTORY.priority_blocker_id ──► BLOCKER
   (이 판단이 어떤 blocker를 해결하려는 시도인지)
```

### CASE_HISTORY

CASE에 대한 발화·이벤트 원본 이력.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| raw_input | TEXT | | NULLABLE | `"임대인이랑 얘기 끝났어요, 다음 달까지 나가기로 했어요"` | 입력 원문. `USER_INPUT`·`CASE_CREATED`는 사장님이 쓴 문장이 항상 들어가고, `SYSTEM_BATCH`는 배치가 에이전트에 전달한 지시문이 들어갈 수 있다. `DOCUMENT_SUBMITTED`는 서류에서 꺼낸 값을 한 줄씩 적은 글(이름·날짜는 넣지 않음)이 들어간다. 문장 없이 고른 값만 있는 `CONFLICT_DECISION`만 NULL |
| restoration_answer | JSON | | NULLABLE | `{"restoration_scope": "PARTIAL", "demolition_required": "REQUIRED"}` | 원상복구 범위를 묻는 다음 행동(`CONFIRM_RESTORATION_SCOPE`)에 선택형으로 답한 값. 한 번 제출할 때 글(`raw_input`)과 둘 중 하나만 들어온다 |
| conflict_snapshot | JSON | | NULLABLE | `{"snapshot_id": "…", "facts": […]}` | 충돌이 났을 때의 Case 상태 전체. 사장님이 고른 뒤 Agent에 **그대로** 돌려줘야 한다 — Agent가 받은 것이 자기가 준 것과 같은지 대조하고 다르면 거절한다. 다시 만들어 넘기면 안 된다. 충돌을 낸 판단에만 값이 있다 |
| retained_info_result | JSON | | NULLABLE | `{"meta": {…}, "output": {…}, "input": {…}}` | 같은 글에서 충돌이 **아니었던** 사실·진행 보고. 확인 뒤 재판단에 그대로 돌려줘야 반영된다 — Agent는 원문을 다시 읽지 않으므로 빠뜨리면 사장님이 함께 말한 내용이 사라진다. 충돌을 낸 판단에만 값이 있다 |
| source | ENUM | | NOT NULL | `USER_INPUT` | `USER_INPUT` / `SYSTEM_BATCH` / `CASE_CREATED` / `CONFLICT_DECISION` / `DOCUMENT_SUBMITTED` — `CASE_CREATED`는 Case 생성 직후 첫 Blocker/Next Action 판단, `CONFLICT_DECISION`은 충돌 확인(`POST /cases/results/decision`)에서 고른 결정에 대한 판단, `DOCUMENT_SUBMITTED`는 서류를 올리거나 확인해 원상복구 조항이 새로 생기거나 바뀌었을 때의 판단 |
| judgment_status | ENUM | | NOT NULL | `PENDING` | 판단 진행 상태. 입력을 받으면 `PENDING`으로 시작해 판단이 끝나면 갱신된다 — `PENDING` / `DONE` / `NEEDS_MORE_INFO` / `CONFLICT` / `FAILED` |
| next_action | TEXT | | NULLABLE | `"부가가치세 확정신고를 진행하세요"` | 다음 액션 제안, 판단이 발생한 경우에만 채워짐 (AI 문장은 길이 제한이 없어 TEXT) |
| next_action_code | VARCHAR(100) | | NULLABLE | `"CONFIRM_RESTORATION_SCOPE"` | 다음 행동의 종류 코드. 결과 알려주기 화면이 선택형으로 받을지 글로 받을지 가르는 데 쓴다. 다음 행동이 없으면 NULL |
| next_action_reason | TEXT | | NULLABLE | `"신고 기한이 폐업일로부터 25일이기 때문입니다"` | 다음 행동을 해야 하는 이유 |
| next_action_questions_to_ask | JSON | | NULLABLE | `["원상복구 범위가 어디까지인지 확인해 주세요"]` | 사용자가 임대인·기관에 물어볼 질문 목록. 다음 행동이 없으면 NULL |
| next_action_evidence_refs | JSON | | NULLABLE | `["procedure:reviewed:NTS_CLOSURE"]` | 다음 행동의 근거 evidence_id 목록. 다음 행동이 없으면 NULL |
| questions_for_user | JSON | | NULLABLE | `["확인한 원상복구 범위가 있으면 알려주세요."]` | 행동을 정하기 전 서비스가 사용자에게 되묻는 질문 목록. 없으면 NULL. `next_action_questions_to_ask`(사용자가 임대인·기관에 물어볼 말)와 다른 값이다 |
| roadmap_task_ids | JSON | | NULLABLE | `["intake", "dispose_stock", "before_photo"]` | 이 판단 직후 로드맵에서 해야 할 일인 항목(해당 없음·확인 필요가 아닌 것)의 `task_id` 목록. 직전 판단과 비교해 결과 화면의 "새로 생긴 할 일"(`GET /cases/results/status`의 `new_tasks`)을 만든다. 검수를 통과한 판단만 채우고, 충돌·실패로 끝났거나 계산에 실패하면 NULL |
| failure_code | VARCHAR | | NULLABLE | `"LOOP_LIMIT_REACHED"` | Agent가 돌려준 실패 종류. Agent가 값을 늘려도 따라 고치지 않도록 ENUM이 아닌 VARCHAR. 실패가 아니거나 Agent가 결과를 내기 전에 끊겼으면 NULL |
| recovery_action_code | ENUM | | NULLABLE | `RETRY` | 판단이 실패했을 때 화면이 안내할 다음 행동 — `RETRY` / `RESUBMIT_INPUT` / `CONTACT_SUPPORT` / `NONE`. 실패가 아니면 NULL |
| requested_field_paths | JSON | | NULLABLE | `["restoration_scope"]` | 판단을 멈추게 한 CASE 필드 목록. 실패가 아니면 NULL |
| retryable | BOOLEAN | | NULLABLE | `true` | 재시도하면 성공할 가능성이 있는지. 실패가 아니면 NULL |
| judged_at | DATETIME | | NULLABLE | `2026-10-17 14:02:11` | 판단이 끝난 시각. 판단 중(`PENDING`)이면 NULL. 기록 탭의 "리본이 한 일" 시각 |
| priority_blocker_id | BIGINT | FK | NULLABLE | `NULL` | 이 시점에 최우선인 블로커 참조 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 09:10:00` | |

### BLOCKER

CASE 진행을 막는 이슈. CASE_HISTORY에서 생성/해소된다.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| candidate_id | TEXT | | NULLABLE | `NULL` | AI가 붙인 블로커 후보 식별자. 다음 판단 때 아직 남아 있는 블로커를 AI에 알려 주는 데 쓴다(`active_blocker_candidate_ids`). 이 필드가 생기기 전 판단에는 없어서 NULL로 두고 임의로 만들지 않는다 |
| created_from_case_history_id | BIGINT | FK | NOT NULL | 5 | 이 blocker를 생성시킨 판단 로그 |
| resolved_from_case_history_id | BIGINT | FK | NULLABLE | `NULL` | 이 blocker를 해소시킨 판단 로그 |
| description | TEXT | | NOT NULL | `"원상복구 범위가 아직 확정되지 않았습니다"` | 블로커 내용 본문 — 사용자에게 보여줄 핵심 필드 (AI 문장은 길이 제한이 없어 TEXT) |
| blocker_evidence_refs | JSON | | NULLABLE | `["case_1_creation_form"]` | 이 블로커 판단의 근거 evidence_id 목록 |
| status | ENUM | | NOT NULL, DEFAULT `ACTIVE` | `ACTIVE` | `ACTIVE` / `RESOLVED` |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 09:10:05` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-10 09:10:05` | |
| resolved_at | DATETIME | | NULLABLE | `NULL` | 해소 시각  |

---

## 3. 절차 마스터 데이터

특정 Case와 무관하게, "폐업 절차에는 어떤 단계들이 있고 서로 어떤 순서/조건으로 연결되는지"를
정의하는 공통 데이터입니다. 모든 Case가 이 마스터 데이터를 공유해서 참조합니다.

```
PROCEDURE_STEP ◄──┬── STEP_DEPENDENCY   (단계 간 순서 규칙)
      │            └── STEP_ELIGIBILITY  (단계 적용 조건 규칙)
      │
      └── replaced_by_procedure_step_id (자기참조, 절차 대체 이력)
```

### PROCEDURE_STEP

폐업 절차의 마스터 데이터 (특정 CASE에 종속되지 않는 공통 절차 정의).

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| step_code | VARCHAR | UK | NOT NULL, UNIQUE | `"BUSINESS_CLOSURE_REPORT"` | 절차 고유 코드 |
| step_name | VARCHAR | | NOT NULL | `"사업자등록 폐업신고"` | 화면 표시용 이름 |
| utterance_aliases | JSON | | NULLABLE | `["폐업신고", "사업자 정리"]` | 발화 매칭용 별칭 목록 |
| registry_version | **VARCHAR** | | NOT NULL | `"v2"` | 절차 레지스트리 버전 |
| deprecated_at | DATETIME | | NULLABLE | `NULL` | 폐기 시각 (nullable) |
| replaced_by_procedure_step_id | BIGINT | FK(자기참조) | NULLABLE | `NULL` | 이 절차를 대체하는 절차 (nullable) |
| responsible_agency | VARCHAR | | NULLABLE | `"세무서/홈택스"` | 담당 기관 |
| deadline_rule | VARCHAR | | NULLABLE | `"D+0"` | 기한 규칙 |
| required_documents | JSON | | NULLABLE | `[{"name":"휴업(폐업)신고서","mandatory":true}]` | 필요 서류 목록 |
| requires_professional | BOOLEAN | | NOT NULL | `false` | 전문가 필요 여부 |
| professional_type | VARCHAR | | NULLABLE | `"세무사"` | 필요한 전문가 유형 |
| caution_note | TEXT | | NULLABLE | `"미신고 시 가산세 부과"` | 주의사항 |
| applicable_business_type | ENUM | | NOT NULL, DEFAULT `ALL` | `ALL` | `ALL`=공통 절차 / `CAFE`=카페 전용 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |

### STEP_DEPENDENCY

절차 간 선후 관계.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| procedure_step_id | BIGINT | FK | NOT NULL | 5 | 실행 대상 절차 |
| prerequisite_procedure_step_id | BIGINT | FK | NOT NULL | 3 | 선행되어야 하는 절차 |
| dependency_type | VARCHAR | | NOT NULL | `"SEQUENTIAL"` | 의존 관계 유형, 기본값 없음(생성 시 명시적으로 채워야 함) |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |

### STEP_ELIGIBILITY

절차 적용 조건.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| procedure_step_id | BIGINT | FK | NOT NULL | 7 | 대상 절차 |
| condition_key | VARCHAR | | NOT NULL | `"has_employee"` | 조건 키 |
| condition_value | VARCHAR | | NOT NULL | `"true"` | 조건 값 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |

---

## 4. Case별 절차 진행상황

위 마스터 데이터(3번)를 실제 Case 하나에 적용했을 때, "지금 어디까지 진행됐는지"와
"그 상태가 어떻게 변해왔는지"를 기록합니다. PROGRESS는 현재 스냅샷, HISTORY는 변경 이력입니다.

```
CASE ──1:N──► CASE_PROCEDURE_STEP                    (현재 상태, 단계당 1 row)
CASE_PROCEDURE_STEP ──1:N──► CASE_PROCEDURE_STEP_HISTORY   (상태 변경마다 새 row 누적)
                        │
                        └── case_history_id로 "이 변화가 어떤 판단 때문에 일어났는지" 역추적 가능
```

### CASE_PROCEDURE_STEP

특정 CASE에 적용된 절차의 현재 상태.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | 대상 케이스 |
| procedure_step_id | BIGINT | FK | NOT NULL | 1 | 적용된 절차 |
| status | ENUM | | NOT NULL, DEFAULT `NOT_STARTED` | `IN_PROGRESS` | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` |
| requirements_confirmed | BOOLEAN | | NOT NULL, DEFAULT `false` | `true` | 이 절차의 신고 방법과 준비사항을 확인했는지 |
| submitted | BOOLEAN | | NOT NULL, DEFAULT `false` | `false` | 담당 기관에 신고를 제출했는지. 처리 완료(`status = COMPLETED`)와 구분한다 |
| evidence_refs | JSON | | NULLABLE | `["input:case_history:7:0:12:a3f2d8"]` | 이 진행 상태의 근거 evidence_id 목록. `COMPLETED`인 절차는 근거가 있어야 Agent 스냅샷에 담을 수 있다 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-01 10:30:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-10 09:11:00` | |

**제약조건**
- UNIQUE (`case_id`, `procedure_step_id`) — Case 하나당 절차 하나에 대해 진행상태 row는 1개만 존재해야 함

### CASE_PROCEDURE_STEP_HISTORY

CASE_PROCEDURE_STEP 상태 변화 이력. `EVIDENCE_LINEAGE`가 `EVIDENCE.id`만 참조하고 `case_id`를
다시 갖지 않는 것과 같은 이유로, 여기서도 `case_id`/`procedure_step_id`를 따로 두지 않고
변화 대상인 `CASE_PROCEDURE_STEP` row의 PK 하나만 참조한다.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_procedure_step_id | BIGINT | FK | NOT NULL | 1 | 상태가 바뀐 `CASE_PROCEDURE_STEP` row — `case_id`/`procedure_step_id`는 이 FK로 조인해서 얻는다 |
| case_history_id | BIGINT | FK | NULLABLE | 5 | 이 변화를 유발한 케이스 이력 (nullable) |
| previous_status | ENUM | | NOT NULL | `NOT_STARTED` | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` (변경 전 상태) |
| new_status | ENUM | | NOT NULL | `IN_PROGRESS` | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` (변경 후 상태) |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 09:11:00` | |

---

## 5. 지원사업

희망리턴패키지 등 지원사업의 원본 메타데이터, Case와의 자격 매칭 결과, 실제 신청 진행상황을 관리합니다.
자격조건 등 세부 내용은 이 테이블에 구조화 컬럼으로 담지 않고, `uuid`로 매핑된
LLM Wiki(Obsidian) 노트에서 관리합니다 — 판정은 LLM+Wiki가 담당하는 구조입니다.

```
CASE ──1:N──► SUPPORT_MATCH ◄──N:1── SUPPORT_ITEM
   │          (자격 매칭 결과)
   │
   └──1:N──► SUPPORT_ITEM_APPLICATION ◄──N:1── SUPPORT_ITEM
              (실제 신청 진행상태)

   ※ SUPPORT_MATCH와 SUPPORT_ITEM_APPLICATION은 순차 관계가 아니라,
      둘 다 CASE↔SUPPORT_ITEM을 각자의 목적(매칭 결과 / 신청 진행)으로 독립 연결함

SUPPORT_ITEM.uuid ──► Wiki 노트와 매핑 (자격조건/금액 등 서술형 정보는 Wiki에 있음)
```

### SUPPORT_ITEM

외부(기업마당 등)에서 수집한 지원사업 공고 마스터.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| uuid | VARCHAR | UK | NOT NULL, UNIQUE | `"550e8400-e29b-41d4-a716-446655440000"` | Wiki 매핑용 고유 식별자 |
| external_notice_id | VARCHAR | | NULLABLE | `"20260915-001"` | 기업마당 공고 ID |
| catalog_version | VARCHAR | | NULLABLE | `"v3"` | 카탈로그 버전 |
| program_name | VARCHAR | | NOT NULL | `"희망리턴패키지 - 점포철거비"` | 지원사업명 (식별자 아님, 식별자는 id) |
| application_start_date | DATE | | NULLABLE | `2026-01-01` | 신청 기간 시작 |
| application_end_date | DATE | | NULLABLE | `2026-12-31` | 신청 기간 종료 |
| source_file_location | VARCHAR | | NULLABLE | `"s3://katecamp-docs/2026/hope-return.pdf"` | S3 원본 파일 위치  |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |

### SUPPORT_MATCH

CASE와 SUPPORT_ITEM 간 자격 비교 결과.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | 대상 케이스 |
| support_item_id | BIGINT | FK | NOT NULL | 3 | 비교 대상 지원사업 |
| match_status | ENUM | | NOT NULL | `NEEDS_CONFIRMATION` | `POSSIBLY_RELEVANT`(가능성 있음) / `NEEDS_CONFIRMATION`(확인 필요) / `NOT_RELEVANT`(관련없음) / `STALE`(정보 오래됨) / `UNVERIFIABLE`(검증 불가) |
| catalog_version | VARCHAR | | NULLABLE | `"v3"` | 매칭 시점의 카탈로그 버전 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 10:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-10 10:00:00` | |

### SUPPORT_ITEM_APPLICATION

실제 신청 진행 상태.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | 신청한 케이스 |
| support_item_id | BIGINT | FK | NOT NULL | 3 | 신청 대상 지원사업 |
| application_status | ENUM | | NOT NULL, DEFAULT `NOT_STARTED` | `APPLIED` | `NOT_STARTED`(미신청) / `APPLIED`(신청함) / `SUPPLEMENT_REQUIRED`(보완요청) / `RESUBMITTED`(재제출) / `APPROVED`(승인) / `REJECTED`(거절) |
| applied_at | DATETIME | | NULLABLE | `NULL` | 신청 시각  |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-05 11:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-05 11:00:00` | |

---

## 6. 근거·충돌·판단기록

Agent 판단의 근거 출처, CASE 필드 값 충돌 확인, Agent의 판단·리뷰 결과를 기록하는 도메인입니다.

```
OFFICIAL_DOCUMENT (공식 자료 본문 한 벌, Case 무관)
   │
   ▼
EVIDENCE ◄──┬── EVIDENCE_LINEAGE (근거 간 파생관계, N:M, EVIDENCE.id 참조)
            │
CASE ──────┴── CONFLICT_REFERENCE (필드값 충돌 1회성 참조)
   │
   └── DECISION_RECORD (Agent 판단·리뷰 결과, 어느 입력에 대한 판단인지 CASE_HISTORY.id도 참조)
```

### EVIDENCE

Agent 판단의 근거가 되는 출처 기록.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | 내부 식별자 |
| evidence_id | VARCHAR | UK | NOT NULL, UNIQUE | `"ev_9f8a2c"` | opaque 근거 ID — `id`와 별개의 비즈니스 키, 외부/타 도메인이 참조할 때 사용 |
| case_id | BIGINT | FK | NOT NULL | 1 | 소유 케이스. 다른 Case의 근거와 섞이지 않게 나눈다 |
| source_type | ENUM | | NOT NULL | `OFFICIAL_DOCUMENT` | `USER_INPUT` / `EXPERT_CONFIRMATION` / `REVIEWED_WIKI` / `OFFICIAL_DOCUMENT` / `OFFICIAL_API` / `CALCULATION_RESULT` / `SYSTEM_RECORD` |
| source_ref | VARCHAR | | NOT NULL | `"희망리턴패키지 공고문 §3"` | 출처 참조 |
| source_version | VARCHAR | | NULLABLE | `"2026-08판"` | 출처 버전 (nullable) |
| locator | VARCHAR | | NULLABLE | `"3페이지 2단락"` | 출처 내 위치 |
| excerpt | TEXT | | NULLABLE | `"임차 매장만 지원 대상..."` | 발췌 내용. 공식 자료면 비어 있고 본문은 `OFFICIAL_DOCUMENT`에 있다 |
| official_document_id | BIGINT | FK | NULLABLE | 1 | 공식 자료일 때 본문이 있는 `OFFICIAL_DOCUMENT.id`. 사장님 입력 등 그 밖의 근거는 NULL |
| published_at | DATETIME | | NULLABLE | `NULL` | 원본 게시 시각 (nullable) |
| retrieved_at | DATETIME | | NOT NULL | `2026-09-10 10:00:00` | 수집 시각 |
| freshness_status | ENUM | | NOT NULL | `CURRENT` | `CURRENT` / `STALE` / `UNKNOWN` |
| content_hash | VARCHAR | | NULLABLE | `"a1b2c3..."` | 내용 해시 (nullable, 변경 감지용) |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 10:00:00` | (updated_at 없음 — ERD 확정) |

### OFFICIAL_DOCUMENT

공식 자료(국세청 안내문, 지원사업 공고 등) 본문. 같은 문서를 Case마다 `EVIDENCE`에 복사하지 않고 여기 한 벌만 두며, `EVIDENCE.official_document_id`가 가리킨다. 문서 한 건의 한 버전마다 한 줄이고, 한 번 적으면 고치지 않는다. 버전이 바뀌면 새 줄을 넣어서, 예전 Case는 예전 줄을 계속 가리킨다(그 Case가 무엇을 보고 판단했는지 남김).

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | 내부 식별자 |
| source_ref | VARCHAR(500) | UK(복합) | NOT NULL | `"https://www.nts.go.kr/..."` | 출처 참조(원문 URL) |
| source_version | VARCHAR(100) | UK(복합) | NOT NULL | `"2026-08판"` | 출처 버전. `(source_ref, source_version)`이 같은 줄은 하나만 둔다 |
| excerpt | TEXT | | NOT NULL | `"폐업신고는 사업장 관할 세무서에..."` | 본문 |
| content_hash | VARCHAR(64) | | NOT NULL | `"a1b2c3..."` | 본문 해시. Case 쪽 값과 대조한다 |
| published_at | DATETIME | | NULLABLE | `NULL` | 원본 게시 시각 |
| retrieved_at | DATETIME | | NOT NULL | `2026-09-10 10:00:00` | 수집 시각 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 10:00:00` | |

### EVIDENCE_LINEAGE

EVIDENCE 간 파생 관계를 나타내는 N:M 접합 테이블. 다른 모든 테이블과 동일하게 surrogate `id`를
PK로 쓰고, 중복 파생 관계 방지는 `(evidence_id, parent_evidence_id)` UNIQUE 제약으로 강제한다.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | 내부 식별자 |
| evidence_id | **BIGINT** | FK, UK(복합) | NOT NULL | `1` | 파생된 근거 (child) — **`EVIDENCE.id` 참조 (evidence_id 아님)** |
| parent_evidence_id | **BIGINT** | FK, UK(복합) | NOT NULL | `2` | 원본 근거 (parent) — **`EVIDENCE.id` 참조** |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 10:00:00` | |

### CONFLICT_REFERENCE

CASE 필드 값 충돌을 확인하기 위한 1회성 참조.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | 내부 식별자 |
| conflict_ref | VARCHAR | UK | NOT NULL, UNIQUE | `"cf_7d8e9f"` | opaque 참조값 — `id`와 별개의 비즈니스 키 |
| case_id | BIGINT | FK | NOT NULL | 1 | 대상 케이스 |
| case_history_id | BIGINT | FK | NOT NULL | 7 | 이 충돌을 일으킨 제출(CASE_HISTORY) — `/confirm`이 "이번에 하신 말씀"을 보여줄 때 쓴다 |
| canonical_field | VARCHAR | | NOT NULL | `"restoration_scope"` | 충돌이 발생한 필드 |
| committed_value | VARCHAR | | NULLABLE | `"UNKNOWN"` | 기존 값 |
| proposed_value | VARCHAR | | NOT NULL | `"FULL"` | 새로 제안된 값 |
| conflict_digest | VARCHAR | | NULLABLE | `"d4e5f6..."` | 충돌 내용 다이제스트 |
| candidate_payload | JSON | | NULLABLE | `{"field_path": "employee_count", "committed_value": 2, ...}` | Agent가 보낸 충돌 후보 원본 전체. 위 칸들은 화면용이라 글자로 바꿔 숫자·참거짓·빈 값을 되돌릴 수 없는데, 확인할 때 Agent가 내용 다이제스트를 대조해 다르면 거절한다 |
| status | ENUM | | NOT NULL | `"PENDING"` | 결정 상태. `PENDING`=아직 결정 안 됨, `CONFIRMED`=새 값 채택, `REJECTED`=기존 값 유지 |
| decided_at | DATETIME | | NULLABLE | `NULL` | 결정된 시각. 결정 전엔 NULL |
| resolved_by_case_history_id | BIGINT | FK | NULLABLE | 9 | 이 충돌을 닫은 결정(CASE_HISTORY) — 위 `case_history_id`(충돌을 일으킨 제출)와 짝이다. 기존 원문 복원도 이 관계로 제출을 추적했으나, 현재 화면 응답에서는 원문을 복원하지 않는다 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 10:00:00` | |

### DECISION_RECORD

Agent의 판단·리뷰 결과 기록.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | 대상 케이스 |
| case_history_id | BIGINT | FK | NOT NULL | 1 | 이 판단을 일으킨 입력 이력 (어느 입력에 대한 판단인지) |
| run_id | VARCHAR | | NOT NULL | `"run_20260910_01"` | 실행 단위 ID |
| snapshot_id | VARCHAR(36) | | NOT NULL | `"b73ccadf-c2d7-46dc-b679-e85d7abfb159"` | 판단에 사용한 Case 상태 스냅샷 ID(UUID) |
| trace_id | VARCHAR | | NULLABLE | `NULL` | 추적 ID (nullable) |
| review_subject_id | VARCHAR | | NOT NULL | `"blocker_5"` | 리뷰 대상 ID |
| review_attempt | INT | | NOT NULL | `1` | 리뷰 시도 횟수 |
| subject_digest | VARCHAR | | NULLABLE | `"g7h8i9..."` | 리뷰 대상 다이제스트 |
| verdict | **VARCHAR** | | NOT NULL | `"PASS"` | 판정 결과 — **ENUM 아니라 VARCHAR (ERD 확정)**, 문서상 `PASS`만 규정됨 |
| decision_type | **VARCHAR** | | NOT NULL | `"ACTION"` | **ENUM 아니라 VARCHAR (ERD 확정)** — `ACTION`(블로커+다음액션 제시) / `NEEDS_MORE_INFO`(추가 질문만 제시) |
| summary | TEXT | | NULLABLE | `"원상복구 범위 미확정, 사용자 확인 필요"` | 판단 요약 |
| human_confirmation_required | BOOLEAN | | NOT NULL | `false` | 사람 확인 필요 여부 |
| reviewed_at | DATETIME | | NOT NULL | `2026-09-10 10:05:00` | 리뷰 완료 시각 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 10:00:00` | (updated_at 없음 — ERD 확정) |