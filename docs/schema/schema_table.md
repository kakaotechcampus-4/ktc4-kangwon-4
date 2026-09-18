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
| member_id | BIGINT | FK | NOT NULL | 1 | |
| business_type | VARCHAR | | NOT NULL | `"카페"` | |
| franchise_status | BOOLEAN | | NOT NULL, DEFAULT false | `false` | |
| employee_count | INT | | NULLABLE | `2` | |
| case_status | ENUM | | NOT NULL, DEFAULT `IN_PROGRESS` | `IN_PROGRESS` | `IN_PROGRESS` / `COMPLETED` |
| lease_status | ENUM | | NOT NULL | `LEASED_PAID` | `LEASED_PAID`/`LEASED_FREE`/`OWNED` |
| restoration_status | ENUM | | NOT NULL | `NOT_STARTED` | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` / `NOT_REQUIRED` — 기본값 없음, 클라이언트/에이전트가 `restoration_scope` 확정 여부에 맞춰 명시적으로 넣어야 함 (필요 없으면 `NOT_REQUIRED`, 필요하면 `NOT_STARTED`) |
| restoration_scope | ENUM | | NOT NULL, DEFAULT `UNKNOWN` | `FULL` | `UNKNOWN`/`PARTIAL` / `FULL` / `NOT_REQUIRED` |
| restoration_scope_detail | VARCHAR | | NULLABLE | `"바닥재·전기배선까지 철거 필요"` | nullable, 구체적인 원상복구 범위 자연어 기록 |
| demolition_required | ENUM | | NOT NULL, DEFAULT `UNKNOWN` | `REQUIRED` | `UNKNOWN`/`REQUIRED` / `NOT_REQUIRED` |
| planned_closure_date | DATE | | NULLABLE | `2026-12-31` | nullable |
| completed_at | DATETIME | | NULLABLE | `NULL` | nullable |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-01 10:24:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-10 09:11:00` | |

---

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

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| raw_input | TEXT | | NOT NULL | `"임대인이랑 얘기 끝났어요, 다음 달까지 나가기로 했어요"` | 입력 원문 (사용자 발화 또는 배치가 에이전트에 전달한 지시문) |
| source | ENUM | | NOT NULL | `USER_INPUT` | `USER_INPUT` / `SYSTEM_BATCH` |
| next_action | VARCHAR | | NULLABLE | `"부가가치세 확정신고를 진행하세요"` | nullable, 판단이 발생한 경우에만 |
| priority_blocker_id | BIGINT | FK | NULLABLE | `NULL` | nullable, 이 next_action이 해결하려는 blocker |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 09:10:00` | |

### BLOCKER

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| created_from_case_history_id | BIGINT | FK | NOT NULL | 5 | 이 blocker를 생성시킨 판단 로그 |
| resolved_from_case_history_id | BIGINT | FK | NULLABLE | `NULL` | nullable, 이 blocker를 해소시킨 판단 로그 |
| description | VARCHAR | | NOT NULL | `"원상복구 범위가 아직 확정되지 않았습니다"` | |
| status | ENUM | | NOT NULL, DEFAULT `ACTIVE` | `ACTIVE` | `ACTIVE` / `RESOLVED` |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 09:10:05` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-10 09:10:05` | |
| resolved_at | DATETIME | | NULLABLE | `NULL` | nullable |

---

## 3. 절차 마스터 데이터 (현재 임시 단계입니다. 추후 더 고도화 필요성이 강함.)

특정 Case와 무관하게, "폐업 절차에는 어떤 단계들이 있고 서로 어떤 순서/조건으로 연결되는지"를
정의하는 공통 데이터입니다. 모든 Case가 이 마스터 데이터를 공유해서 참조합니다.

```
PROCEDURE_STEP ◄──┬── STEP_DEPENDENCY   (단계 간 순서 규칙)
                   └── STEP_ELIGIBILITY  (단계 적용 조건 규칙)
```

### PROCEDURE_STEP

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| step_code | VARCHAR | UK | NOT NULL, UNIQUE | `"BUSINESS_CLOSURE_REPORT"` | 절차 구분 코드 |
| responsible_agency | VARCHAR | | NULLABLE | `"세무서/홈택스"` | 담당 기관 |
| deadline_rule | VARCHAR | | NULLABLE | `"D+0"` | 기한 규칙 |
| required_documents | JSON | | NULLABLE | `[{"name":"휴업(폐업)신고서","mandatory":true}]` | 필요 서류 목록 |
| requires_professional | BOOLEAN | | NOT NULL, DEFAULT false | `false` | 전문가 필요 여부 |
| professional_type | VARCHAR | | NULLABLE | `"세무사"` | 전문가 종류 |
| caution_note | TEXT | | NULLABLE | `"미신고 시 가산세 부과"` | 주의사항·벌칙 |
| applicable_business_type | ENUM | | NOT NULL, DEFAULT `ALL` | `ALL` | `ALL`=공통 절차 / 특정 업종명=해당 업종 전용 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |

### STEP_DEPENDENCY

어떤 단계가 어떤 단계보다 먼저 끝나야 하는지 (선후관계).

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| procedure_step_id | BIGINT | FK | NOT NULL | 5 | 실행하려는 단계 |
| prerequisite_procedure_step_id | BIGINT | FK | NOT NULL | 3 | 먼저 끝나야 하는 단계 |
| dependency_type | VARCHAR | | NOT NULL | `"SEQUENTIAL"` | 기본값 없음, 생성 시 명시적으로 채워야 함 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |

### STEP_ELIGIBILITY

어떤 조건의 Case에서 이 단계가 적용되는지 (한 단계에 조건이 여러 개면 전부 AND로 해석).

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| procedure_step_id | BIGINT | FK | NOT NULL | 7 | |
| condition_key | VARCHAR | | NOT NULL | `"has_employee"` | |
| condition_value | VARCHAR | | NOT NULL | `"true"` | |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |

---

## 4. Case별 절차 진행상황

위 마스터 데이터(3번)를 실제 Case 하나에 적용했을 때, "지금 어디까지 진행됐는지"와
"그 상태가 어떻게 변해왔는지"를 기록합니다. PROGRESS는 현재 스냅샷, HISTORY는 변경 이력입니다.

```
CASE ──1:N──► CASE_PROCEDURE_STEP           (현재 상태, 단계당 1 row)
CASE ──1:N──► CASE_PROCEDURE_STEP_HISTORY   (상태 변경마다 새 row 누적)
                        │
                        └── case_history_id로 "이 변화가 어떤 판단 때문에 일어났는지" 역추적 가능
```

### CASE_PROCEDURE_STEP

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| procedure_step_id | BIGINT | FK | NOT NULL | 1 | |
| status | ENUM | | NOT NULL, DEFAULT `NOT_STARTED` | `IN_PROGRESS` | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` (현재 상태) |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-01 10:30:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-10 09:11:00` | |

**제약조건**
- UNIQUE (`case_id`, `procedure_step_id`) — Case 하나당 절차 하나에 대해 진행상태 row는 1개만 존재해야 함

### CASE_PROCEDURE_STEP_HISTORY

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| procedure_step_id | BIGINT | FK | NOT NULL | 1 | NOT NULL — 상태가 바뀐 절차 하나 |
| case_history_id | BIGINT | FK | NULLABLE | 5 | nullable, 이 변화를 유발한 판단 로그 |
| previous_status | ENUM | | NOT NULL | `NOT_STARTED` | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` |
| new_status | ENUM | | NOT NULL | `IN_PROGRESS` | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 09:11:00` | |

---

## 5. 지원사업

희망리턴패키지 등 지원사업의 원본 메타데이터 정보와, Case별 신청 현황을 관리합니다.
자격조건 등 세부 내용은 이 테이블에 구조화 컬럼으로 담지 않고, `uuid`로 매핑된
LLM Wiki(Obsidian) 노트에서 관리합니다 — 판정은 LLM+Wiki가 담당하는 구조입니다.

```
SUPPORT_ITEM ──1:N──► SUPPORT_ITEM_APPLICATION ◄──N:1── CASE
       │
       └── uuid로 Wiki 노트와 매핑 (자격조건/금액 등 서술형 정보는 Wiki에 있음)
```

### SUPPORT_ITEM

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| uuid | VARCHAR | UK | NOT NULL, UNIQUE | `"550e8400-e29b-41d4-a716-446655440000"` | 배치 작업 시 생성, Wiki와 매핑 용도 |
| program_name | VARCHAR | | NOT NULL | `"희망리턴패키지 - 점포철거비"` | 표시용 이름 (식별자 아님, 식별자는 id) |
| application_start_date | DATE | | NULLABLE | `2026-01-01` | |
| application_end_date | DATE | | NULLABLE | `2026-12-31` | |
| source_file_location | VARCHAR | | NULLABLE | `"s3://katecamp-docs/2026/hope-return.pdf"` | S3 원본 파일 위치 (확정) |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-08-01 00:00:00` | |

### SUPPORT_ITEM_APPLICATION

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| support_item_id | BIGINT | FK | NOT NULL | 3 | |
| application_status | ENUM | | NOT NULL, DEFAULT `NOT_CHECKED` | `ELIGIBLE` | `NOT_CHECKED` / `ELIGIBLE` / `NOT_ELIGIBLE` / `APPLIED` / `SUPPLEMENT_REQUIRED` / `RESUBMITTED` / `APPROVED` / `REJECTED` |
| applied_at | DATETIME | | NULLABLE | `NULL` | nullable |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-05 11:00:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-05 11:00:00` | |