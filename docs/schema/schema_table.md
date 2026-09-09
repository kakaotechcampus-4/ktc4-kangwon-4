# 스키마 (테이블 정의)

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
MEMBERS ──1:N──► CASE
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

### CASE

사용자 한 명이 진행하는 폐업 건 하나를 의미함.

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| member_id | BIGINT | FK | |
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
CASE ──1:N──► CASE_CLOSURE_PROCEDURE_STEP_PROGRESS   (현재 상태, 단계당 1 row)
CASE ──1:N──► CASE_CLOSURE_PROCEDURE_STEP_HISTORY    (상태 변경마다 새 row 누적)
                        │
                        └── case_log_id로 "이 변화가 어떤 판단 때문에 일어났는지" 역추적 가능
```

### CASE_CLOSURE_PROCEDURE_STEP_PROGRESS

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| closure_procedure_step_id | BIGINT | FK | |
| status | ENUM | | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` (현재 상태) |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

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
SUPPORT_PROGRAM ──1:N──► SUPPORT_PROGRAM_APPLICATION ◄──N:1── CASE
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