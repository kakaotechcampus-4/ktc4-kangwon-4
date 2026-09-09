# 최종 스키마 (테이블 정의)

## MEMBERS

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| oauth_id | VARCHAR | UK | 카카오 회원번호 |
| nickname | VARCHAR | | 카카오 닉네임 |
| refresh_token | VARCHAR | | |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

## CASE

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| member_id | BIGINT | FK | |
| business_type | VARCHAR | | |
| franchise_status | BOOLEAN | | |
| employee_count | INT | | |
| case_status | ENUM | | IN_PROGRESS / COMPLETED |
| lease_status | ENUM | | LEASED / OWNED |
| restoration_status | ENUM | | NOT_STARTED / IN_PROGRESS / COMPLETED / NOT_REQUIRED |
| restoration_scope | ENUM | | PARTIAL / FULL / NOT_REQUIRED |
| restoration_scope_detail | VARCHAR | | nullable, 구체적인 원상복구 범위 자연어 기록 |
| demolition_required | ENUM | | REQUIRED / NOT_REQUIRED |
| planned_closure_date | DATE | | nullable |
| completed_at | DATETIME | | nullable |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

## CASE_LOG

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| raw_input | TEXT | | 입력 원문 (사용자 발화 또는 배치가 에이전트에 전달한 지시문) |
| source | ENUM | | USER_INPUT / SYSTEM_BATCH |
| next_action | VARCHAR | | nullable, 판단이 발생한 경우에만 |
| priority_blocker_id | BIGINT | FK | nullable, 이 next_action이 해결하려는 blocker |
| created_at | DATETIME | | |

## BLOCKER

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| created_from_case_log_id | BIGINT | FK | 이 blocker를 생성시킨 판단 로그 |
| resolved_from_case_log_id | BIGINT | FK | nullable, 이 blocker를 해소시킨 판단 로그 |
| description | VARCHAR | | |
| status | ENUM | | ACTIVE / RESOLVED |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |
| resolved_at | DATETIME | | nullable |

## CASE_CLOSURE_PROCEDURE_STEP_HISTORY

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| closure_procedure_step_id | BIGINT | FK | NOT NULL - 상태가 바뀐 절차 하나 |
| case_log_id | BIGINT | FK | nullable, 이 변화를 유발한 판단 로그 |
| previous_status | ENUM | | NOT_STARTED / IN_PROGRESS / COMPLETED |
| new_status | ENUM | | NOT_STARTED / IN_PROGRESS / COMPLETED |
| changed_at | DATETIME | | |

## CASE_CLOSURE_PROCEDURE_STEP_PROGRESS

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| closure_procedure_step_id | BIGINT | FK | |
| status | ENUM | | NOT_STARTED / IN_PROGRESS / COMPLETED (현재 상태) |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

## SUPPORT_PROGRAM_APPLICATION

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| case_id | BIGINT | FK | |
| support_program_id | BIGINT | FK | |
| application_status | ENUM | | NOT_CHECKED / ELIGIBLE / NOT_ELIGIBLE / APPLIED / SUPPLEMENT_REQUIRED / RESUBMITTED / APPROVED / REJECTED |
| applied_at | DATETIME | | nullable |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

## SUPPORT_PROGRAM

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

## CLOSURE_PROCEDURE_STEP

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| step_name | VARCHAR | UK | |
| requires_professional | BOOLEAN | | |
| professional_type | VARCHAR | | |
| is_active | BOOLEAN | | |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

## CLOSURE_PROCEDURE_STEP_DEPENDENCY

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| closure_procedure_step_id | BIGINT | FK | |
| prerequisite_closure_procedure_step_id | BIGINT | FK | |
| dependency_type | VARCHAR | | |
| description | VARCHAR | | |
| created_at | DATETIME | | |

## CLOSURE_PROCEDURE_STEP_ELIGIBILITY

| 컬럼 | 타입 | 키 | 설명 |
|---|---|---|---|
| id | BIGINT | PK | |
| closure_procedure_step_id | BIGINT | FK | |
| condition_key | VARCHAR | | |
| condition_value | VARCHAR | | |
| created_at | DATETIME | | |

