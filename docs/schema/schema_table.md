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

> ⚠️ 6번 도메인은 Agent팀 ERD에 컬럼·타입·PK/FK/UK는 명시되어 있으나, NOT NULL/DEFAULT 등
> 제약조건까지는 ERD에 안 나와 있어 기존 테이블 패턴을 참고해 추정했습니다 (표시: "⚠️ 추정").
> 컬럼명·타입·키는 ERD 원본 기준으로 확정된 값입니다.

---

## 1. 사용자/케이스

서비스에 로그인한 사용자와, 그 사용자가 진행 중인 폐업 건(Case) 하나를 표현합니다.
Case 하나가 이 서비스의 핵심 작업 단위이고, 나머지 모든 테이블은 결국 Case를 중심으로 붙습니다.

```
MEMBERS ──1:N──► CASE ──1:N──► CASE_FIELD_HISTORY
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
| member_id | BIGINT | FK | NOT NULL | 1 | |
| case_version | **BIGINT** | | NOT NULL, DEFAULT 1 ⚠️ 추정 (타입은 ERD 확정) | `3` | 낙관적 동시성 제어용 버전, 동시 수정 충돌 방지 |
| business_type | VARCHAR | | NOT NULL | `"카페"` | |
| franchise_status | BOOLEAN | | NOT NULL, DEFAULT false | `false` | |
| employee_count | INT | | NULLABLE | `2` | |
| case_status | ENUM | | NOT NULL, DEFAULT `IN_PROGRESS` | `IN_PROGRESS` | `IN_PROGRESS` / `COMPLETED` |
| lease_status | ENUM | | NOT NULL | `LEASED_PAID` | `LEASED_PAID`/`LEASED_FREE`/`OWNED` |
| restoration_status | ENUM | | NOT NULL, DEFAULT `UNKNOWN` | `UNKNOWN` | `UNKNOWN`/`NOT_STARTED`/`IN_PROGRESS`/`COMPLETED`/`NOT_REQUIRED` — Case 생성 직후 `UNKNOWN`으로 시작, `restoration_scope` 확정 후 나머지 값으로 전환 |
| restoration_scope | ENUM | | NOT NULL, DEFAULT `UNKNOWN` | `FULL` | `UNKNOWN`/`PARTIAL` / `FULL` / `NOT_REQUIRED` |
| restoration_scope_detail | VARCHAR | | NULLABLE | `"바닥재·전기배선까지 철거 필요"` | nullable, 구체적인 원상복구 범위 자연어 기록 |
| demolition_required | ENUM | | NOT NULL, DEFAULT `UNKNOWN` | `REQUIRED` | `UNKNOWN`/`REQUIRED` / `NOT_REQUIRED` |
| planned_closure_date | DATE | | NULLABLE | `2026-12-31` | nullable |
| completed_at | DATETIME | | NULLABLE | `NULL` | nullable |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-01 10:24:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-10 09:11:00` | |

### CASE_FIELD_HISTORY

CASE의 필드 단위 변경 이력 (감사 추적용). `CASE_HISTORY`(발화·이벤트 원본)와 별개로, "필드 값이 무엇에서 무엇으로 바뀌었는지"만 정밀 추적.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| canonical_field | VARCHAR | | NOT NULL | `"restoration_scope"` | 변경된 필드명 |
| before_value | VARCHAR | | NULLABLE | `"UNKNOWN"` | 변경 전 값 |
| after_value | VARCHAR | | NOT NULL | `"FULL"` | 변경 후 값 |
| source | VARCHAR | | NOT NULL ⚠️ 값 목록 P0 미정 | `"USER_INPUT"` | 변경 출처 |
| reason | VARCHAR | | NULLABLE | `"사용자가 원상복구 범위 확정함"` | 변경 사유 |
| resulting_case_version | **BIGINT** | | NOT NULL | `3` | 변경 결과로 생성된 `case_version` (CASE.case_version과 동일 타입) |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP ⚠️ 추정 | `2026-09-10 09:11:00` | |

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

CASE에 대한 발화·이벤트 원본 이력.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| raw_input | TEXT | | NOT NULL | `"임대인이랑 얘기 끝났어요, 다음 달까지 나가기로 했어요"` | 입력 원문 (사용자 발화 또는 배치가 에이전트에 전달한 지시문) |
| source | ENUM | | NOT NULL | `USER_INPUT` | `USER_INPUT` / `SYSTEM_BATCH` |
| next_action | VARCHAR | | NULLABLE | `"부가가치세 확정신고를 진행하세요"` | 다음 액션 제안, 판단이 발생한 경우에만 채워짐 |
| priority_blocker_id | BIGINT | FK | NULLABLE | `NULL` | 이 시점에 최우선인 블로커 참조 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-10 09:10:00` | |

### BLOCKER

CASE 진행을 막는 이슈. CASE_HISTORY에서 생성/해소된다.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| created_from_case_history_id | BIGINT | FK | NOT NULL | 5 | 이 blocker를 생성시킨 판단 로그 |
| resolved_from_case_history_id | BIGINT | FK | NULLABLE | `NULL` | 이 blocker를 해소시킨 판단 로그 |
| description | VARCHAR | | NOT NULL | `"원상복구 범위가 아직 확정되지 않았습니다"` | 블로커 내용 본문 — 사용자에게 보여줄 핵심 필드 |
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
| step_name | VARCHAR | | NOT NULL ⚠️ 추정 | `"사업자등록 폐업신고"` | 화면 표시용 이름 |
| utterance_aliases | JSON | | NULLABLE ⚠️ 추정 | `["폐업신고", "사업자 정리"]` | 발화 매칭용 별칭 목록 |
| registry_version | **VARCHAR** | | NOT NULL ⚠️ 추정 (타입은 ERD 확정 — INT 아님) | `"v2"` | 절차 레지스트리 버전 |
| deprecated_at | DATETIME | | NULLABLE | `NULL` | 폐기 시각 (nullable) |
| replaced_by_procedure_step_id | BIGINT | FK(자기참조) | NULLABLE | `NULL` | 이 절차를 대체하는 절차 (nullable) |
| responsible_agency | VARCHAR | | NULLABLE | `"세무서/홈택스"` | 담당 기관 |
| deadline_rule | VARCHAR | | NULLABLE | `"D+0"` | 기한 규칙 |
| required_documents | JSON | | NULLABLE | `[{"name":"휴업(폐업)신고서","mandatory":true}]` | 필요 서류 목록 |
| requires_professional | BOOLEAN | | NOT NULL, DEFAULT false | `false` | 전문가 필요 여부 |
| professional_type | VARCHAR | | NULLABLE | `"세무사"` | 필요한 전문가 유형 |
| caution_note | TEXT | | NULLABLE | `"미신고 시 가산세 부과"` | 주의사항 |
| applicable_business_type | ENUM | | NOT NULL, DEFAULT `ALL` | `ALL` | `ALL`=공통 절차 / 특정 업종명=해당 업종 전용 |
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
CASE ──1:N──► CASE_PROCEDURE_STEP           (현재 상태, 단계당 1 row)
CASE ──1:N──► CASE_PROCEDURE_STEP_HISTORY   (상태 변경마다 새 row 누적)
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
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP | `2026-09-01 10:30:00` | |
| updated_at | DATETIME | | NOT NULL, ON UPDATE CURRENT_TIMESTAMP | `2026-09-10 09:11:00` | |

**제약조건**
- UNIQUE (`case_id`, `procedure_step_id`) — Case 하나당 절차 하나에 대해 진행상태 row는 1개만 존재해야 함

### CASE_PROCEDURE_STEP_HISTORY

CASE_PROCEDURE_STEP 상태 변화 이력.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | |
| procedure_step_id | BIGINT | FK | NOT NULL | 1 | 상태가 바뀐 절차 하나 |
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
| external_notice_id | VARCHAR | | NULLABLE ⚠️ 추정 | `"20260915-001"` | 기업마당 공고 ID |
| catalog_version | VARCHAR | | NULLABLE ⚠️ 추정 | `"v3"` | 카탈로그 버전 |
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
| catalog_version | VARCHAR | | NULLABLE ⚠️ 추정 | `"v3"` | 매칭 시점의 카탈로그 버전 |
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
EVIDENCE ◄──┬── EVIDENCE_LINEAGE (근거 간 파생관계, N:M, EVIDENCE.id 참조)
            │
CASE ──────┴── CONFLICT_REFERENCE (필드값 충돌 1회성 참조)
   │
   └── DECISION_RECORD (Agent 판단·리뷰 결과)
```

### EVIDENCE

Agent 판단의 근거가 되는 출처 기록.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | 내부 식별자 |
| evidence_id | VARCHAR | UK | NOT NULL, UNIQUE ⚠️ 추정 | `"ev_9f8a2c"` | opaque 근거 ID — `id`와 별개의 비즈니스 키, 외부/타 도메인이 참조할 때 사용 |
| case_id | BIGINT | FK | NOT NULL ⚠️ 추정 (소유권 격리 목적으로 필요) | 1 | 소유 케이스 |
| source_type | ENUM | | NOT NULL | `OFFICIAL_DOCUMENT` | `USER_INPUT` / `EXPERT_CONFIRMATION` / `REVIEWED_WIKI` / `OFFICIAL_DOCUMENT` / `OFFICIAL_API` / `CALCULATION_RESULT` / `SYSTEM_RECORD` |
| source_ref | VARCHAR | | NOT NULL ⚠️ 추정 | `"희망리턴패키지 공고문 §3"` | 출처 참조 |
| source_version | VARCHAR | | NULLABLE | `"2026-08판"` | 출처 버전 (nullable) |
| locator | VARCHAR | | NULLABLE ⚠️ 추정 | `"3페이지 2단락"` | 출처 내 위치 |
| excerpt | TEXT | | NULLABLE ⚠️ 추정 | `"임차 매장만 지원 대상..."` | 발췌 내용 |
| published_at | DATETIME | | NULLABLE | `NULL` | 원본 게시 시각 (nullable) |
| retrieved_at | DATETIME | | NOT NULL ⚠️ 추정 | `2026-09-10 10:00:00` | 수집 시각 |
| freshness_status | ENUM | | NOT NULL ⚠️ 추정 | `CURRENT` | `CURRENT` / `STALE` / `UNKNOWN` |
| content_hash | VARCHAR | | NULLABLE | `"a1b2c3..."` | 내용 해시 (nullable, 변경 감지용) |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP ⚠️ 추정 | `2026-09-10 10:00:00` | (updated_at 없음 — ERD 확정) |

### EVIDENCE_LINEAGE

EVIDENCE 간 파생 관계를 나타내는 N:M 접합 테이블. **자체 PK 없음, 두 FK로만 구성.**

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| evidence_id | **BIGINT** | FK (복합 PK) | NOT NULL | `1` | 파생된 근거 (child) — **`EVIDENCE.id` 참조 (evidence_id 아님)** |
| parent_evidence_id | **BIGINT** | FK (복합 PK) | NOT NULL | `2` | 원본 근거 (parent) — **`EVIDENCE.id` 참조** |

### CONFLICT_REFERENCE

CASE 필드 값 충돌을 확인하기 위한 1회성 참조.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | 내부 식별자 |
| conflict_ref | VARCHAR | UK | NOT NULL, UNIQUE ⚠️ 추정 | `"cf_7d8e9f"` | opaque 참조값 — `id`와 별개의 비즈니스 키 |
| case_id | BIGINT | FK | NOT NULL | 1 | 대상 케이스 |
| case_version | BIGINT | | NOT NULL | `3` | 대상 케이스 시점 버전 |
| canonical_field | VARCHAR | | NOT NULL | `"restoration_scope"` | 충돌이 발생한 필드 |
| committed_value | VARCHAR | | NULLABLE ⚠️ 추정 | `"UNKNOWN"` | 기존 값 |
| proposed_value | VARCHAR | | NOT NULL ⚠️ 추정 | `"FULL"` | 새로 제안된 값 |
| conflict_digest | VARCHAR | | NULLABLE ⚠️ 추정 | `"d4e5f6..."` | 충돌 내용 다이제스트 |
| expires_at | DATETIME | | NOT NULL | `2026-09-11 10:00:00` | 만료 시각 |
| used_at | DATETIME | | NULLABLE | `NULL` | 사용(1회) 시각 (nullable) — 1회 사용 검증용 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP ⚠️ 추정 | `2026-09-10 10:00:00` | |

### DECISION_RECORD

Agent의 판단·리뷰 결과 기록.

| 컬럼 | 타입 | 키 | 제약조건 | 예시 값 | 설명 |
|---|---|---|---|---|---|
| id | BIGINT | PK | NOT NULL, AUTO_INCREMENT | 1 | |
| case_id | BIGINT | FK | NOT NULL | 1 | 대상 케이스 |
| case_version | BIGINT | | NOT NULL | `3` | 대상 케이스 시점 버전 |
| run_id | VARCHAR | | NOT NULL ⚠️ 추정 | `"run_20260910_01"` | 실행 단위 ID |
| trace_id | VARCHAR | | NULLABLE | `NULL` | 추적 ID (nullable) |
| review_subject_id | VARCHAR | | NOT NULL ⚠️ 추정 | `"blocker_5"` | 리뷰 대상 ID |
| review_attempt | INT | | NOT NULL, DEFAULT 1 ⚠️ 추정 | `1` | 리뷰 시도 횟수 |
| subject_digest | VARCHAR | | NULLABLE ⚠️ 추정 | `"g7h8i9..."` | 리뷰 대상 다이제스트 |
| verdict | **VARCHAR** | | NOT NULL | `"PASS"` | 판정 결과 — **ENUM 아니라 VARCHAR (ERD 확정)**, 문서상 `PASS`만 규정됨 |
| decision_type | **VARCHAR** | | NOT NULL | `"ACTION"` | **ENUM 아니라 VARCHAR (ERD 확정)** — `ACTION`(블로커+다음액션 제시) / `NEEDS_MORE_INFO`(추가 질문만 제시) |
| summary | TEXT | | NULLABLE ⚠️ 추정 | `"원상복구 범위 미확정, 사용자 확인 필요"` | 판단 요약 |
| human_confirmation_required | BOOLEAN | | NOT NULL, DEFAULT false ⚠️ 추정 | `false` | 사람 확인 필요 여부 |
| reviewed_at | DATETIME | | NOT NULL ⚠️ 추정 | `2026-09-10 10:05:00` | 리뷰 완료 시각 |
| created_at | DATETIME | | NOT NULL, DEFAULT CURRENT_TIMESTAMP ⚠️ 추정 | `2026-09-10 10:00:00` | (updated_at 없음 — ERD 확정) |