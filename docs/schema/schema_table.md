# 스키마 (테이블 정의)

> 상태: **논리 DB 설계 제안**입니다. 아래 `CASES` rename, `version`, `CASE_FIELD_HISTORY`, composite UNIQUE를 포함한 실제 migration은 아직 BE가 구현·검증하지 않았습니다. 표의 enum도 canonical Agent/API enum 합의 전 초안이므로 그대로 운영 DDL로 복사하지 않습니다. 구현 책임과 승인 기준은 [`../be-agent-integration-requirements.md`](../be-agent-integration-requirements.md)를 따릅니다.

전체 구조는 5개 도메인으로 나뉩니다.

```
[1. 사용자/케이스]         서비스의 기본 단위 (누가, 어떤 폐업 건을)
        │
        ├──[2. 판단 로그 & 블로커]      에이전트가 뭘 판단했고, 지금 뭐가 막혔는지
        │
        ├──[3. 절차 마스터 데이터]      폐업 절차 전체 목록과 순서/조건 규칙 (공통, Case 무관)
        │        │
        │        └──[4. Case별 절차 진행상황]   위 마스터를 Case마다 실제로 어디까지 했는지
        │
        └──[5. 지원사업]               희망리턴패키지 등 지원사업 신청 현황
```

---

## 1. 사용자/케이스

서비스에 로그인한 사용자와, 그 사용자가 진행 중인 폐업 건(Case) 하나를 표현합니다.
Case 하나가 이 서비스의 핵심 작업 단위이고, 나머지 모든 테이블은 결국 Case를 중심으로 붙습니다.

```
MEMBERS ──1:N──► CASES
```

### MEMBERS

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| oauth_id | VARCHAR | UK | 카카오 회원번호 |
| nickname | VARCHAR | | 카카오 닉네임 |
| refresh_token | VARCHAR | | |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

### CASES

사용자 한 명이 진행하는 폐업 건 하나를 의미함.

물리 테이블명은 MySQL 예약어인 `CASE`와 충돌하지 않도록 **`CASES`**를 사용합니다. 문서에서 대문자 `CASES`는 테이블을, 일반 표기인 Case는 서비스의 업무 단위를 뜻합니다.

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| member_id | BIGINT | FK | |
| version | BIGINT | | NOT NULL, default `1`; 상태 변경 성공 시 1 증가하며 `expectedVersion` 비교에 사용 |
| business_type | VARCHAR | | |
| franchise_status | BOOLEAN | | |
| employee_count | INT | | |
| case_status | ENUM | | `IN_PROGRESS` / `COMPLETED` |
| lease_status | ENUM | | `LEASED` / `OWNED` |
| restoration_status | ENUM | | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` / `NOT_REQUIRED` |
| restoration_scope | ENUM | | `PARTIAL` / `FULL` / `NOT_REQUIRED` |
| restoration_scope_detail | VARCHAR | | nullable, 구체적인 원상복구 범위 자연어 기록 |
| demolition_required | ENUM | | `REQUIRED` / `NOT_REQUIRED` |
| planned_closure_date | DATE | | nullable |
| completed_at | DATETIME | | nullable |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

`CASES`라는 이름과 `version`은 이 문서에서 채택한 논리 제안입니다. BE 완료 판정은 실제 migration 뒤 (1) 기존 Case 데이터 보존, (2) 모든 FK/repository가 `CASES(id)` 사용, (3) 신규 `CASE` table 부재, (4) apply/rollback 테스트 통과로 합니다.

### CASE_FIELD_HISTORY

`CASES`의 업무 상태 컬럼이 언제, 무엇에서 무엇으로, 어떤 근거로 바뀌었는지를 남기는 append-only 감사 이력입니다. 한 요청에서 여러 필드가 바뀌면 필드마다 한 row를 추가합니다. `CASES` 갱신, `version` 증가, 관련 `CASE_FIELD_HISTORY` 삽입은 반드시 하나의 DB 트랜잭션으로 처리합니다.

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | 변경된 `CASES.id` |
| case_log_id | BIGINT | FK | nullable, 변경을 유발한 입력·판단 로그 |
| case_version | BIGINT | | 변경이 반영된 뒤의 `CASES.version` |
| field_name | VARCHAR | | 변경된 허용 컬럼명; 임의 JSON 경로 금지 |
| previous_value | JSON | | nullable, 변경 전 typed 값을 JSON scalar로 보존 |
| new_value | JSON | | nullable, 변경 후 typed 값을 JSON scalar로 보존 |
| change_source | ENUM | | `USER_CONFIRMED` / `REVIEWED_AGENT` / `SYSTEM_BATCH` / `ADMIN` |
| change_reason | VARCHAR | | 사람이 이해할 수 있는 변경 이유 또는 정책 코드 |
| changed_by_member_id | BIGINT | FK | nullable, 사용자·관리자 변경일 때 actor |
| created_at | DATETIME | | 변경 시각; row 수정 시각이 아니라 불변 생성 시각 |

다음 제약을 DB와 서비스 계층이 함께 보장해야 합니다.

- `(case_id, case_version, field_name)`에 `UNIQUE`를 두어 같은 버전의 같은 필드를 중복 기록하지 않습니다.
- 서비스 계정에는 `CASE_FIELD_HISTORY`의 `UPDATE`/`DELETE` 권한을 주지 않아 이력을 불변으로 유지합니다.
- `previous_value`와 `new_value`가 같은 변경은 기록하지 않고, 민감한 사용자 원문은 이 테이블에 복제하지 않습니다. 원문 근거는 `case_log_id`로 역추적합니다.
- `REVIEWED_AGENT`는 Review와 Output Guardrail을 통과해 실제 저장된 변경에만 사용합니다. Agent 후보만으로 이력을 만들지 않습니다.

`CASES.version` 갱신은 `UPDATE ... WHERE id = :case_id AND version = :expected_version`와 같은 원자적 CAS로 수행합니다. 영향 row가 0개이면 stale write이므로 업무 field, `CASE_FIELD_HISTORY`, decision/history를 하나도 commit하지 않습니다. 성공할 때만 version을 1 증가시키고 실제로 바뀐 field마다 before/after·source·reason row를 같은 transaction에 append합니다. enum의 최종 값, JSON scalar 직렬화와 실제 DDL은 BE·AI 공동 확정 후 migration으로 고정합니다.

---

## 2. 판단 로그 & 블로커

에이전트가 사용자 발화나 배치 작업을 처리하면서 내린 판단을 기록하고,
그 판단으로 인해 "지금 막혀서 못 넘어가는 것(Blocker)"이 생기면 별도로 추적합니다.
CASE_LOG와 BLOCKER는 서로를 생성/해소 관계로 참조합니다.

```
CASE_LOG ──created_from──► BLOCKER
   ▲                          │
   └────── resolved_from ─────┘
   (다음 로그가 이전 blocker를 해소시킴)

CASE_LOG.priority_blocker_id ──► BLOCKER
   (이 판단이 어떤 blocker를 해결하려는 시도인지)
```

### CASE_LOG

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| raw_input | TEXT | | 입력 원문 (사용자 발화 또는 배치가 에이전트에 전달한 지시문) |
| source | ENUM | | `USER_INPUT` / `SYSTEM_BATCH` |
| next_action | VARCHAR | | nullable, 판단이 발생한 경우에만 |
| priority_blocker_id | BIGINT | FK | nullable, 이 next_action이 해결하려는 blocker |
| created_at | DATETIME | | |

### BLOCKER

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| created_from_case_log_id | BIGINT | FK | 이 blocker를 생성시킨 판단 로그 |
| resolved_from_case_log_id | BIGINT | FK | nullable, 이 blocker를 해소시킨 판단 로그 |
| description | VARCHAR | | |
| status | ENUM | | `ACTIVE` / `RESOLVED` |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |
| resolved_at | DATETIME | | nullable |

---

## 3. 절차 마스터 데이터(현재 임시 단계입니다. 추후 더 고도화 필요성이 강함.)

특정 Case와 무관하게, "폐업 절차에는 어떤 단계들이 있고 서로 어떤 순서/조건으로 연결되는지"를
정의하는 공통 데이터입니다. 모든 Case가 이 마스터 데이터를 공유해서 참조합니다.

```
CLOSURE_PROCEDURE_STEP ◄──┬── CLOSURE_PROCEDURE_STEP_DEPENDENCY  (단계 간 순서 규칙)
                           └── CLOSURE_PROCEDURE_STEP_ELIGIBILITY (단계 적용 조건 규칙)
```

### CLOSURE_PROCEDURE_STEP

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| step_name | VARCHAR | UK | |
| requires_professional | BOOLEAN | | |
| professional_type | VARCHAR | | |
| is_active | BOOLEAN | | |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

### CLOSURE_PROCEDURE_STEP_DEPENDENCY

어떤 단계가 어떤 단계보다 먼저 끝나야 하는지 (선후관계).

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| closure_procedure_step_id | BIGINT | FK | 실행하려는 단계 |
| prerequisite_closure_procedure_step_id | BIGINT | FK | 먼저 끝나야 하는 단계 |
| dependency_type | VARCHAR | | |
| description | VARCHAR | | |
| created_at | DATETIME | | |

### CLOSURE_PROCEDURE_STEP_ELIGIBILITY

어떤 조건의 Case에서 이 단계가 적용되는지 (한 단계에 조건이 여러 개면 전부 AND로 해석).

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| closure_procedure_step_id | BIGINT | FK | |
| condition_key | VARCHAR | | |
| condition_value | VARCHAR | | |
| created_at | DATETIME | | |

---

## 4. Case별 절차 진행상황

위 마스터 데이터(3번)를 실제 Case 하나에 적용했을 때, "지금 어디까지 진행됐는지"와
"그 상태가 어떻게 변해왔는지"를 기록합니다. PROGRESS는 현재 스냅샷, HISTORY는 변경 이력입니다.

```
CASES ──1:N──► CASE_CLOSURE_PROCEDURE_STEP_PROGRESS   (현재 상태, 단계당 1 row)
CASES ──1:N──► CASE_CLOSURE_PROCEDURE_STEP_HISTORY    (상태 변경마다 새 row 누적)
                        │
                        └── case_log_id로 "이 변화가 어떤 판단 때문에 일어났는지" 역추적 가능
```

### CASE_CLOSURE_PROCEDURE_STEP_PROGRESS

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK, UK(1) | `CASES.id`; `closure_procedure_step_id`와 복합 UNIQUE |
| closure_procedure_step_id | BIGINT | FK, UK(1) | `case_id`와 복합 UNIQUE |
| status | ENUM | | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` (현재 상태) |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

`UNIQUE (case_id, closure_procedure_step_id)`가 Case별·단계별 현재 row를 **최대 하나**로 강제합니다. UNIQUE만으로 row의 존재까지 강제할 수는 없습니다. **적용 단계마다 정확히 하나**라는 서비스 불변식은 BE가 versioned canonical registry/eligibility로 대상 집합을 먼저 고정하고, Case 생성 또는 registry 적용 transaction에서 대상마다 한 row를 insert한 뒤 대상 수와 저장 row 수를 대조해야 완성됩니다. 일부 insert가 실패하면 Case/progress 초기화 전체를 rollback합니다. 절차조회 Tool의 인터넷 결과는 canonical ID나 적용 단계 집합을 만들지 않습니다.

이후 상태 변경은 새 PROGRESS row를 추가하지 않고 기존 row를 갱신하며, 같은 transaction에서 HISTORY row를 append합니다. 동시 갱신은 `CASES.version` 원자적 compare-and-set과 필요한 progress row lock으로 직렬화합니다. 승인 테스트는 동시 생성·retry·중복 insert·부분 실패를 포함하고, 적용 대상마다 정확히 1 row이며 비적용 단계 row가 없음을 확인해야 합니다.

### CASE_CLOSURE_PROCEDURE_STEP_HISTORY

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| closure_procedure_step_id | BIGINT | FK | NOT NULL — 상태가 바뀐 절차 하나 |
| case_log_id | BIGINT | FK | nullable, 이 변화를 유발한 판단 로그 |
| previous_status | ENUM | | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` |
| new_status | ENUM | | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` |
| changed_at | DATETIME | | |

---

## 5. 지원사업

희망리턴패키지 등 지원사업의 원본 메타데이터 정보와, Case별 신청 현황을 관리합니다.
자격조건 등 세부 내용은 이 테이블에 구조화 컬럼으로 담지 않고, `uuid`로 매핑된
LLM Wiki(Obsidian) 노트에서 관리합니다 — 판정은 LLM+Wiki가 담당하는 구조입니다.

```
SUPPORT_PROGRAM ──1:N──► SUPPORT_PROGRAM_APPLICATION ◄──N:1── CASES
       │
       └── uuid로 Wiki 노트와 매핑 (자격조건/금액 등 서술형 정보는 Wiki에 있음)
```

### SUPPORT_PROGRAM

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| uuid | VARCHAR | UK | 배치 작업 시 생성, Wiki와 매핑 용도 |
| program_name | VARCHAR | | 표시용 이름 (식별자 아님, 식별자는 id) |
| application_start_date | DATE | | |
| application_end_date | DATE | | |
| source_file_location | VARCHAR | | S3 원본 파일 위치 |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

### SUPPORT_PROGRAM_APPLICATION

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| support_program_id | BIGINT | FK | |
| application_status | ENUM | | `NOT_CHECKED` / `ELIGIBLE` / `NOT_ELIGIBLE` / `APPLIED` / `SUPPLEMENT_REQUIRED` / `RESUBMITTED` / `APPROVED` / `REJECTED` |
| applied_at | DATETIME | | nullable |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |
