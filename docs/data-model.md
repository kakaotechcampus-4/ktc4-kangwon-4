# RE:BORN 데이터 모델

> Case 상태 구조 및 데이터 모델 정의. `docs/architecture.md`, `docs/interface-spec.md`, `docs/hero-scenario.md`는 아래 enum·테이블·Rule을 재정의하지 않고 이 문서를 인용합니다.

## 1. 다섯 가지 개념 — 혼동하지 말 것

Case를 설계할 때 아래 다섯 가지는 서로 다른 축입니다. 실제로 IDEATHON 초안들에서 "진행중"이라는 라벨이 절차 상태와 확인 상태 양쪽에 쓰이며 혼용된 적이 있어, 이 문서에서 명시적으로 분리합니다.

| 구분 | 예시 | 의미 |
|---|---|---|
| 사실 상태 | `demolition_required = UNKNOWN/REQUIRED/NOT_REQUIRED` | 현재 Case에 저장된 사실 값 |
| 사실 출처 | `USER_INPUT`, `DOCUMENT`, `OFFICIAL_API`, `EXPERT` | 그 사실을 어디서 얻었는가 |
| 확인 상태 | `UNCONFIRMED`, `CONFIRMED`, `CONFLICT`, `UNDETERMINED` | 그 사실을 저장해도 되는 정도 (fact-level) |
| 절차 상태 | `NOT_STARTED`, `IN_PROGRESS`, `APPROVAL_PENDING`, `COMPLETED` | 해당 절차(procedure step)를 어디까지 실행했는가 |
| 지원 비교 상태 | `NOT_CHECKED`, `POSSIBLY_RELEVANT`, `NEEDS_CONFIRMATION`, `NOT_RELEVANT`, `STALE` | 지원항목과 Case의 비교 결과 |

예: 임대인이 "철거해야 한다"고 말했다는 것은 `demolition_required = REQUIRED`라는 사실 후보가 될 수 있지만, 철거비 지원 신청을 완료했다는 뜻은 아닙니다 — 전자는 사실 상태, 후자는 절차 상태(또는 `subsidy_application.application_status`) 영역입니다.

### 1.1 확인 상태 (fact-level)

```
UNCONFIRMED   미확인 — 아직 값이 없음
CONFIRMED     확인됨 — 사용자/문서/API로 확정
CONFLICT      충돌 — 기존 값과 신규 값이 다름, 사용자 선택 대기
UNDETERMINED  확정 불가 — 문장만으로 확정할 수 없음 (예: 계약서 특약처럼 사람 확인이 필요한 경우)
```

### 1.2 절차 상태 (`case_step_progress.status`)

```
NOT_STARTED        미시작
IN_PROGRESS         진행중
APPROVAL_PENDING    승인대기 — 지원/행정 절차가 외부 기관 승인을 기다리는 중
COMPLETED           완료
SKIPPED             건너뜀 — dependency_type=RECOMMENDED인 선행 절차를 사용자가 건너뛴 경우 (AI 리드 확정, 2026-09)
```

> 이전 문서들에서 "미시작·진행중·승인대기·완료"(절차 진행 단계)와 "확인됨·미확인·확정 불가"(사실 확인 여부)가 같은 화면 라벨처럼 섞여 쓰인 적이 있습니다. 이 문서에서는 전자를 절차 상태, 후자를 확인 상태로 명확히 분리합니다. "진행중"은 절차 상태에만 속하며, 확인 상태에는 존재하지 않습니다.

### 1.3 사실 출처 (`source_type`)

```
USER_INPUT      사용자 발화/입력 (구 문서의 USER_RESULT와 동의어 — 이 문서에서 USER_INPUT으로 통일)
DOCUMENT        계약서 등 사용자가 제공한 문서
OFFICIAL_API    공식 API 조회 결과
EXPERT          전문가 확인 결과
```

### 1.4 지원 비교 상태 (`match_status`)

```
NOT_CHECKED          아직 비교하지 않음
POSSIBLY_RELEVANT    Case와 관련 있어 보임 (지급 대상이라는 뜻 아님)
NEEDS_CONFIRMATION   조건 일부가 미확인이라 추가 확인 필요
NOT_RELEVANT         관련 없음
STALE                근거 원문이 오래되어 재확인 필요
```

`ELIGIBLE`은 사용하지 않습니다 — 지원기관의 최종 심사 전에는 내부적으로도 `POSSIBLY_RELEVANT`/`NEEDS_CONFIRMATION`으로 제한합니다.

### 1.5 `subsidy_application.application_status`

```
NOT_APPLIED
APPLIED
SUPPLEMENT_REQUIRED
APPROVED
REJECTED
```

지원 비교 상태(`match_status`)와 실제 신청 상태(`application_status`)는 다른 테이블/다른 축입니다 — Agent가 지원항목을 발견했다고 `subsidy_application`을 자동 생성하거나 `APPLIED`로 바꾸지 않습니다.

## 2. 테이블 스키마 (BE 확정본, 2026-09)

9개 테이블 전체 컬럼입니다. 이 문서가 "출처" 표에서 자주 언급하던 "AI 리드 제안 vs Notion BE 초안" 두 버전은 여기서 **BE가 실제로 확정한 아래 스키마로 통일**합니다.

### `members`

| 필드 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | 자체 발급 고유번호 |
| oauth_id | VARCHAR UNIQUE | 카카오 발급 회원번호. 재로그인 시 이 값으로 기존 회원 판별 |
| refresh_token | VARCHAR | **카카오**가 발급한 리프레시 토큰 보관용(카카오 API 재호출용). 우리 자체 JWT의 refresh 토큰과는 다른 것 — §3 참고 |
| created_at | DATETIME | 가입일 |
| updated_at | DATETIME | 마지막 갱신(재로그인 시 `refresh_token` 갱신 시점) |

### `case`

| 필드 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | Case 고유번호 |
| member_id | BIGINT FK → members.id | **이 Case의 소유자.** `GET /cases/{caseId}` 등 모든 조회에서 `requester_id == case.member_id` 검증 근거(`/CLAUDE.md` 개인정보 invariant) |
| business_type | VARCHAR | 업종. 예: "카페" |
| franchise_status | BOOLEAN | 프랜차이즈 여부 |
| employee_count | INT | 직원 수 |
| entity_type | ENUM | `INDIVIDUAL`(개인사업자)/`CORPORATION`(법인·비영리) — §9 지원사업 제외조건("비영리·법인") 매칭에 필요(AI 리드 신규 추가, 2026-09) |
| building_use_type | ENUM | `BUSINESS`(상업용)/`RESIDENTIAL`(주거용) — §9 제외조건("주거용도 건축물") 매칭에 필요(AI 리드 신규 추가, 2026-09) |
| previous_support_history | BOOLEAN | 동일/유사 정부 지원사업 수혜 이력 여부 — §9 제외조건("기 수혜 이력 1회 한도") 및 `docs/interface-spec.md` §11.4 `PREVIOUS_SUPPORT_HISTORY` criterion 매칭에 필요(AI 리드 신규 추가, 2026-09) |
| lease_status | ENUM | §2.1 참고 |
| restoration_status | ENUM | 원상복구 진행 세부 상태 |
| restoration_scope | ENUM | `UNKNOWN`, `MINOR_ONLY`, `DEMOLITION_REQUIRED` |
| demolition_required | ENUM | `UNKNOWN`, `NOT_REQUIRED`, `REQUIRED` |
| case_status | ENUM | §2.2 참고 |
| version | INT | 낙관적 잠금 (§3) |
| consult_started_at | DATETIME | 폐업 상담(서비스 이용) 시작일 |
| planned_closure_date | DATE, nullable | 사용자가 정한 폐업 예정일 — AI 추천 대상 아님 |
| closed_at | DATETIME, nullable | Case 종료 처리 시점 |
| created_at / updated_at | DATETIME | |

**신규 3개 필드 근거**: §9에 이미 시딩된 "점포철거비 지원"의 `exclusion_conditions`(자가건물/무상임차, 기 수혜 이력, 주거용도 건축물, 유사 정부사업 중복수혜, 단순 이전/3년 내 재창업, 비영리·법인, 제외업종)를 기존 `case` 필드와 대조한 결과, `entity_type`/`building_use_type`/`previous_support_history` 3개는 저장할 곳이 아예 없었습니다. "단순 이전/3년 내 재창업" 조건은 아직 매칭할 필드가 마땅치 않아 **명시적 TBD로 남깁니다**(§10 참고).

**폐업 결정 여부(`closure_decision_status`)와 "지원정보 확인 상태"는 이 테이블의 컬럼이 아닙니다** — 전자는 서비스 진입 전제라 수집하지 않고(F1), 후자는 `subsidy_application` 레코드 존재 여부로 판단합니다(별도 컬럼 없음, F1). `region`처럼 이전 초안이 제안했던 필드도 이 확정 스키마에는 없습니다 — 필요해지면 마이그레이션(Alembic)으로 추가합니다.

#### 2.1 `lease_status` — 4값으로 확장 확정

`case.lease_status`를 `UNKNOWN`/`LEASED_PAID`/`LEASED_FREE`/`OWNED` 4값 enum으로 확장합니다(AI 리드 확정, 2026-09 — **BE 승인 대기**). 별도 boolean(`is_paid_lease`)을 추가하는 대신 enum을 확장하는 이유: (1) `restoration_scope`처럼 이 스키마는 이미 "두 축을 하나의 enum으로 합치는" 패턴을 쓰고 있어 일관성이 있고, (2) boolean을 따로 두면 `lease_status=OWNED`인데 `is_paid_lease=true`처럼 모순되는 조합이 만들어질 수 있는데 단일 enum은 이를 구조적으로 차단하며, (3) `docs/interface-spec.md` §11.4 예시가 이미 `case_value: "LEASED_PAID"` 단일 값 비교를 전제로 작성돼 있습니다.

(기존 문제 인식: 이미 seed된 `support_item_점포철거비지원.json`의 자격조건이 "`LEASED_PAID`(유상임차만 — 무상임차·자가건물 제외)"를 요구하는데 기존 2값 enum에는 그 구분이 없었습니다.)

#### 2.2 `case_status` enum

3값으로 확정합니다(AI 리드, 2026-09 — **BE 승인 대기**): `IN_PROGRESS`(진행중), `CLOSED`(종료됨), `CANCELLED`(사용자가 폐업 절차를 중단).

**`CLOSED` 전이 조건**: `case_step_progress`에서 `CLOSURE_REPORT` 절차가 `COMPLETED`일 때만 `case_status`를 `CLOSED`로 전이할 수 있습니다 — `CLOSURE_REPORT`(사업자등록 폐업신고)가 폐업 과정의 법적 완결점이기 때문입니다(§6.2 상태 전이표에도 반영).

### `procedure_step` — 절차 마스터

| 필드 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| step_code | VARCHAR UNIQUE | 예: `DEMOLITION` |
| step_name | VARCHAR | 예: "철거" |
| requires_professional | BOOLEAN | 전문가 판단 영역인지 |
| professional_type | VARCHAR | 예: "세무사", "변호사" |
| decision_authority | ENUM | `LANDLORD`/`USER`/`OFFICIAL` — 이 절차의 결과가 누구의 답변·결정을 기준으로 확정되는지(AI 리드 확정, 2026-09) |
| is_active | BOOLEAN | 현재 사용 중인 절차인지 |

**`step_code` 목록 — MVP 확정(AI 리드, 2026-09)**:

| step_code | step_name | decision_authority | 비고 |
|---|---|---|---|
| `RESTORATION_CHECK` | 원상복구 범위 확인 | `LANDLORD` | 임대인 답변에 따라 `restoration_scope`/`demolition_required` 확정 |
| `DEMOLITION` | 철거(건물) | `LANDLORD` | 건물 구조물 철거 — `점포철거비 지원`과 연결된 유일한 절차 |
| `EQUIPMENT_DISPOSAL` | 집기·장비 처리 | `USER` | 건물이 아닌 사장님 소유 이동자산(의자·테이블·커피머신 등) 처리 — 건물주 응답과 무관, 사용자 본인 결정이 기준. 다른 절차와 순서 의존관계 없음(독립 진행 가능) |
| `LEASE_TERMINATION_NOTICE` | 임대차 계약 해지 통보 | `LANDLORD` | |
| `CLOSURE_REPORT` | 사업자등록 폐업신고 | `OFFICIAL` | `case_status`가 `CLOSED`로 전이하려면 이 절차가 `COMPLETED`여야 함(§2.2) |

**`EMPLOYEE_SEPARATION`(직원 퇴직 처리)은 마스터 데이터에 넣지 않습니다** — `case.employee_count > 0`일 때만 적용되는데, 이건 `step_eligibility`의 정확값 비교로 표현할 수 없는 조건(0보다 큰지)이라 데이터로 만들지 않고 `app/rules/evaluate_step_eligibility()` 코드에 직접 `if case.employee_count > 0` 분기로 하드코딩합니다 — 이미 `app/rules/`의 상태 전이표(§6.2)도 코드로 강제되는 규칙이 있으므로 같은 패턴입니다.

**세무 신고(부가세 확정신고 등)는 MVP 절차 목록에서 제외합니다** — 법적으로 세무사가 반드시 필요한 업무는 아니지만(사업자 본인이 홈택스로 신고 가능), 세무보조 Agent 자체가 MVP 범위 밖(`architecture.md` §7)이므로 절차로도 넣지 않습니다. **추후 세무보조 Agent를 확장할 때 이 절차를 추가할 예정**이라는 확장 지점으로만 남겨둡니다.

### `step_dependency` — 절차 선후관계

| 필드 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| procedure_step_id | BIGINT FK → procedure_step.id | 실행하려는 단계 |
| prerequisite_procedure_step_id | BIGINT FK → procedure_step.id | 먼저 충족되어야 하는 단계 |
| dependency_type | ENUM | `REQUIRED`(선행 절차가 `COMPLETED`여야만 시작 가능) / `RECOMMENDED`(권장 순서지만 건너뛰어도 됨 — §1.2 `SKIPPED` 상태로 진행) — AI 리드 확정, 2026-09 |
| description | VARCHAR | 관계 설명 |

**MVP 확정 데이터(AI 리드, 2026-09)**: `{procedure_step: DEMOLITION, prerequisite: RESTORATION_CHECK, dependency_type: REQUIRED, description: "원상복구 범위가 확인돼야 철거 필요 여부와 절차를 진행할 수 있음"}` 1건뿐입니다. `EQUIPMENT_DISPOSAL`/`LEASE_TERMINATION_NOTICE`는 다른 절차와 순서 의존관계 없이 독립적으로 진행 가능하므로 `step_dependency` 행을 만들지 않습니다.

### `step_eligibility` — 조건별 단계 적용 여부

| 필드 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| procedure_step_id | BIGINT FK → procedure_step.id | 예: "철거" |
| condition_key | VARCHAR | 예: `lease_status` |
| condition_value | VARCHAR | 예: `LEASED_PAID` |

한 단계에 여러 조건이 있으면 전부 AND로 해석합니다. **정확값 비교만 지원**하며(이상/이하 등 범위 비교 불가), 범위 조건(예: `employee_count > 0`)은 이 테이블 대신 `app/rules/` 코드에 직접 작성합니다(위 `procedure_step` §의 `EMPLOYEE_SEPARATION` 설명 참고).

**MVP 확정 데이터(AI 리드, 2026-09)**:
- `RESTORATION_CHECK`: `lease_status IN (LEASED_PAID, LEASED_FREE)` — 자가건물(`OWNED`)은 임대인에게 되돌려줄 원상복구 의무 자체가 없어 이 절차가 적용되지 않음
- `DEMOLITION`: `lease_status IN (LEASED_PAID, LEASED_FREE)` AND `demolition_required = REQUIRED`
- `EQUIPMENT_DISPOSAL`/`LEASE_TERMINATION_NOTICE`/`CLOSURE_REPORT`: 조건 없음(모든 케이스에 적용)

### `case_step_progress`

| 필드 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| case_id | BIGINT FK → case.id | |
| procedure_step_id | BIGINT FK → procedure_step.id | |
| status | ENUM | §1.2 절차 상태 (`NOT_STARTED`/`IN_PROGRESS`/`APPROVAL_PENDING`/`COMPLETED`) |
| updated_at | DATETIME | |

### `subsidy_application`

| 필드 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| case_id | BIGINT FK → case.id | |
| support_item_id | BIGINT FK → support_item.id | |
| application_status | ENUM | §1.5 (`NOT_APPLIED`/`APPLIED`/`SUPPLEMENT_REQUIRED`/`APPROVED`/`REJECTED`) |
| applied_at | DATETIME, nullable | |
| created_at / updated_at | DATETIME | |

`support_item`, `case_history`의 전체 컬럼은 각각 §7~8, §4를 참고하세요(중복 서술하지 않음).

## 3. `case.version` / `expectedVersion` — 낙관적 잠금

채택합니다: 클라이언트는 자신이 마지막으로 본 `case.version`을 `expectedVersion`으로 함께 보내고, 서버는 그 값이 현재 DB의 `version`과 다르면 자동 UPDATE하지 않고 재조회 또는 충돌로 처리합니다. 오래된 화면이 보낸 요청이 최신 값을 덮어쓰는 것을 막기 위함입니다(R4 자동 덮어쓰기 금지, F8 충돌 방지 요구사항 — Notion 기능 요구사항).

**컬럼 타입은 `INT`(1씩 증가)로 확정**합니다 — §2 `case` 테이블에 반영. `docs/interface-spec.md` §5(`POST /results`)의 `expectedVersion: 6 → caseVersion: 7` 예시가 이 의미론을 그대로 따릅니다.

## 4. `case_history` — 스키마 병합

기존에 두 버전이 있었습니다: (a) Notion BE 초안의 `raw_input, blocker, next_action, judgment_basis`, (b) AI 리드 제안의 `event_type, case_version, changed_fields(JSON), decision_json(JSON), evidence_refs(JSON), source_type, source_ref`. 아래는 두 버전을 병합한 스키마입니다 — 기존 필드를 버리지 않고 새 필드를 더합니다.

```
case_history
├─ id                  BIGINT PK
├─ case_id             BIGINT FK
├─ created_at          DATETIME
├─ event_type          VARCHAR   (§4.1 enum)
├─ case_version         INT
├─ raw_input            TEXT (nullable) — 사용자 입력 원문
├─ changed_fields       JSON      — [{field, before, after}, ...]
├─ decision_json        JSON      — 판단 근거 전체를 저장(AI 리드 확정, 2026-09): {case_snapshot: {...판단 시점의 케이스 상태...}, applicable_steps: [...그 시점에 진행해야 하는 절차 목록...], blocker:{code,reason,affected_fields}, next_action:{code,title,reason,questions,requires_human}, rule_version} — `docs/interface-spec.md` §4.3 `RuleDecision`에 `case_snapshot`/`applicable_steps`를 추가한 확장판(`case_id`/`case_version`/`evidence_refs`는 이미 이 테이블의 다른 컬럼이라 중복 저장하지 않음)
├─ evidence_refs        JSON      — [evidence_id, ...]
├─ source_type          VARCHAR         (§1.3 enum)
├─ source_ref           VARCHAR (nullable)
└─ judgment_basis       TEXT (nullable) — 레거시 호환, 판단 근거 서술
```

DB는 **MySQL**로 확정(2026-09 BE, SQLAlchemy + pymysql — `docs/tech-stack.md` §2 참고)되어 위 컬럼들은 MySQL의 `JSON` 타입을 사용합니다(PostgreSQL 전용인 JSONB는 해당 없음). **BE 확인 필요**로 남는 것은 이 병합 스키마(§4, AI 리드 제안) 자체의 최종 채택 여부뿐입니다.

기존 History 레코드는 DELETE하지 않습니다 — 정정이 필요한 경우에도 새 이벤트를 INSERT합니다.

### 4.1 `event_type` enum

```
CASE_CREATED
RESULT_SUBMITTED
FACT_ACCEPTED
CONFLICT_DETECTED
CONFLICT_CONFIRMED
CASE_UPDATED
REPLAN_STARTED
REPLAN_COMPLETED
REPLAN_FAILED
SUPPORT_CHECKED
APPLICATION_RESULT_RECORDED
ACTION_REVERTED
```

`ACTION_REVERTED`: 사용자가 "이전" 버튼으로 직전 처리를 되돌렸을 때 남기는 이벤트(§12 되돌리기 참고, AI 리드 확정 2026-09). 기존 기록을 지우지 않고 새 이벤트로 추가하는 원칙(위 문단)을 그대로 따릅니다.

**Loop 회전 수 측정 기준**: "세션당 Loop 2회전 이상"이라는 제품 성공지표는 `case_history` 단순 레코드 수가 아니라 `REPLAN_COMPLETED` 이벤트 수로 집계합니다 (`RESULT_SUBMITTED → CASE_UPDATED → REPLAN_COMPLETED` 묶음 = 재계획 1회전). 최종 집계 방식은 **PM·BE 확인 필요**.

## 5. Rule Set (R1–R10)

```
R1   폐업 의사는 AI가 결정하지 않는다.               → 미확인 시 사용자 확인 질문
R2   입력 문장에 없는 사실은 추정하지 않는다.         → 값은 UNKNOWN, 필요한 항목 질문
R3   허용되지 않은 상태 전이는 저장하지 않는다.       → 정정 입력 요청 (INVALID_TRANSITION)
R4   기존 값과 새 값이 충돌하면 자동 덮어쓰지 않는다. → CONFLICT, 사용자 확인
R5   Case 조건이 바뀌면 영향받는 절차를 재계산한다.   → 영향받는 Step·Blocker 재평가
R6   Blocker가 여러 개여도 Next Action은 1개만 제시한다. → 우선순위 규칙으로 하나 선택 (§6)
R7   지원정보는 공식 근거가 있는 경우에만 연결한다.   → 공식 URL·조건·확인 행동 표시, 자격/금액 확정 금지
R8   법률·세무·채무·계약·금전 판단은 사람에게 남긴다. → requires_human = true
R9   현실 실행 결과나 증빙 없이 완료 처리하지 않는다. → 조회·클릭만으로 완료 금지
R10  Blocker와 Next Action은 근거를 추적할 수 있어야 한다. → Case 필드·공식 Evidence 연결
```

## 6. `NextActionSelector` 우선순위 (R6 상세 스펙)

```
우선순위 (높음 → 낮음):
1. 안전/금지조건    — 지금 진행하면 지원을 놓치거나 되돌리기 어려운 조건
2. 선행조건         — 다음 절차를 잠그고 있는 미확인 조건
3. 공식기한         — 공고에 명시된 기한과 최신 확인 시각이 있는 경우
4. 영향도           — 해결하지 않으면 여러 절차가 함께 막히는 조건
5. 실행가능성       — 사용자가 지금 실제로 수행할 수 있는 행동

동률 처리: 위 고정 순서만 사용, LLM이 임의로 선택하지 않음.
그래도 못 정하면 → NEEDS_MORE_INFO로 라우팅.
```

### 6.1 `app/rules/` 최소 함수 시그니처

이름·시그니처는 확정이 아니라 **권장안**입니다 — `backend/CLAUDE.md`가 언급하는 6개 모듈을 실제로 구현할 때 이 모양을 그대로 써도 됩니다.

```python
def validate_transition(field: str, before: str, after: str) -> ValidationResult: ...
# R3 — §6.2 상태 전이표를 참고해 허용되지 않은 전이면 INVALID_TRANSITION

def evaluate_step_eligibility(case: CaseState) -> list[ProcedureStep]: ...
# step_eligibility 조건(AND)을 Case와 대조해 현재 적용되는 절차 목록 반환

def resolve_dependencies(case_id: int) -> list[ProcedureStep]:  ...
# step_dependency 기준으로 지금 진행 가능한 절차만 필터링

def detect_blockers(case: CaseState) -> list[Blocker]: ...
# 미확인·충돌·선행조건 미충족 등을 근거로 Blocker 후보 목록 생성 (R1, R2, R5)

class NextActionSelector:
    def select(self, blockers: list[Blocker], case: CaseState) -> NextAction | Literal["NEEDS_MORE_INFO"]: ...
    # §6 우선순위(안전/금지조건 > 선행조건 > 공식기한 > 영향도 > 실행가능성)로 Blocker 중 1개를 골라 NextAction 생성 (R6)

def compare_support_conditions(case: CaseState, item: SupportItem) -> SupportCheckResult: ...
# support_item.eligibility_json과 Case 필드를 비교해 criteria[]·match_status 계산 (R7)
```

### 6.2 상태 전이표 (R3 상세 스펙)

`INVALID_TRANSITION`을 판단하는 최소 기준입니다 — 여기 없는 전이는 허용으로 간주합니다.

| 필드 | 금지되는 전이 |
|---|---|
| `demolition_required` | `REQUIRED → NOT_REQUIRED` 직접 전이 금지 (되돌리려면 `UNKNOWN`을 거쳐 사용자 재확인 필요) |
| `restoration_status` | `COMPLETED`(완료) 이후 `UNKNOWN`으로 되돌리기 금지 |
| `restoration_scope` | `DEMOLITION_REQUIRED → MINOR_ONLY` 직접 전이 금지 (되돌리려면 `UNKNOWN`을 거쳐 사용자 재확인 필요) — `demolition_required`와 같은 실세계 사실을 표현하는 필드라 대칭 규칙 적용(AI 리드 확정, 2026-09) |
| `case_status` | `CLOSED`/`CANCELLED`(종료) 이후에는 어떤 필드도 갱신 금지 — 새 Case 생성으로 유도. `→ CLOSED` 진입은 `CLOSURE_REPORT` 절차 `COMPLETED` 시에만 허용(§2.2) |

나머지 필드의 전이 제약은 발견되는 대로 이 표에 추가합니다(**BE 확인 필요**).

주의: "철거 전 30일"과 같은 기한은 공식 최신 공고·첨부문서에 근거가 있을 때만 Rule로 사용합니다. 예시 문구를 영구적인 정책값으로 하드코딩하지 않습니다.

### Worked example 1

```
원상복구 범위 = UNKNOWN
철거 필요 여부 = UNKNOWN
→ Blocker: 원상복구·철거 범위가 확인되지 않음
→ Next Action: 임대인에게 원상복구 범위와 철거 필요 여부를 확인
```

### Worked example 2

```
철거 필요 여부 = REQUIRED
지원 조건 = NOT_CHECKED
→ Blocker: 철거 전에 확인해야 할 지원 조건과 증빙이 남아 있음
→ Next Action: 공식 점포철거비 지원 조건과 신청 전 필요 서류를 확인
```

## 7. `support_item` 스키마

```
support_item
├─ id
├─ program_id / program_code
├─ item_name
├─ related_procedure_step_id
├─ eligibility_json           — 여러 자격조건·제외조건
├─ required_documents_json    — 서류 목록·제출 단계
├─ application_channel
├─ application_url
├─ source_notice_url
├─ source_notice_version
├─ attachment_urls_json
├─ collected_at
├─ document_hash
├─ review_status              — DRAFT / REVIEWED / REVIEW_REQUIRED
└─ is_active
```

`lease_status`, `demolition_required`, `employee_count_max`처럼 Rule이 자주 검색하는 핵심 조건은 일반 컬럼으로 유지하고, 예외·복수 조건·문서 목록은 JSON 또는 별도 테이블로 둡니다.

## 8. `Evidence` 스키마

```
Evidence
├─ evidence_id
├─ support_item_id
├─ source_url
├─ source_version
├─ document_type       — NOTICE / PDF / GUIDE / MANUAL / API
├─ evidence_text
├─ page_or_section
├─ collected_at
├─ document_hash
└─ review_status
```

`RuleDecision.evidence_refs`에는 이 Evidence ID를 연결합니다. 사용자에게는 URL과 쉬운 설명만 보여주고, 개발자/운영자는 원문 위치까지 추적할 수 있게 합니다.

## 9. 첫 지원사업 슬라이스 — `점포철거비 지원`

첫 `support_item`은 **점포철거비 지원**(희망리턴패키지 원스톱폐업지원)으로 확정합니다 — 실제로 구조화·seed된 유일한 항목이기 때문입니다. **사업정리컨설팅은 "다음 확장" 후보로만 남기고, 이번 문서에서 팀을 대신해 포함 여부를 결정하지 않습니다.**

이미 구조화된 seed 예시(`support_item_점포철거비지원.json`, BE 데이터 시딩 범위 — 이 문서에는 구조만 인용, 파일 자체는 복사하지 않음)가 위 스키마로 실제 구현 가능함을 보여줍니다:

```
item_name: "점포철거비 지원"
program_name: "희망리턴패키지 원스톱폐업지원"
related_procedure_step: "DEMOLITION (철거)"
eligibility: { lease_status: LEASED_PAID, demolition_required: REQUIRED,
               business_operation_days_min: 60, closure_date_after: 2023-01-01,
               self_demolition: 지원 제외 }
exclusion_conditions: [자가건물/무상임차, 기 수혜 이력(1회 한도), 주거용도 건축물,
                        유사 정부사업 중복수혜, 단순 이전/3년 내 재창업, 비영리·법인, 제외업종]
support_amount: { review_status: REVIEW_REQUIRED, candidates: [...] }
required_documents: { 1차_신청서류, 2차_정산서류, 공통서류 }
application_channel: "소상공인24 (sbiz24.kr)"
application_period: "2026년 1월 ~ 예산 소진 시"
```

**R7 실제 사례** (`support_amount.review_status = REVIEW_REQUIRED`): 두 출처의 금액이 불일치합니다 — 웹페이지 기준 "8만원/3.3㎡, 250만원 한도" vs 2차 수정공고 PDF 기준 "20만원/3.3㎡, 폐업일에 따라 400만원 또는 600만원 한도". 이 값이 전화 확인(1533-0100)으로 `CONFIRMED`가 되기 전까지, Agent는 이 항목의 지원 금액을 확정적으로 안내하지 않습니다 — "검토 대상"으로만 표시합니다.

## 10. 명시적 TBD

- **`REPLAN_FAILED` 시 정책**: Case UPDATE는 성공했지만 그 다음 재계획(Blocker/Next Action 재산정)이 실패한 경우, Case를 rollback할지 아니면 Case는 저장한 채로 판단만 재시도할지는 **BE 멘토링·팀 회의에서 정합니다**. 유일하게 고정된 원칙은: 어느 쪽이든 이전 판단을 새 Case 버전의 판단인 것처럼 화면에 보여주지 않는다는 것입니다.
- **`procedureStepId`를 FE가 지정할지 Agent가 문맥에서 판단할지**: `docs/interface-spec.md`에서 다시 다룹니다.
- **"단순 이전/3년 내 재창업" 매칭 필드**: §9 제외조건 중 이것만 아직 어느 `case` 필드로 매칭할지 정하지 못했습니다 — 근거 없이 지어내지 않고 TBD로 남깁니다.
- 위 항목 외 인증(JWT)·트랜잭션 경계·Conflict 임시저장·Obsidian 동기화·스케줄러 등 BE 확인이 필요한 나머지 항목은 `docs/architecture.md` §8, `docs/interface-spec.md` §13 참고 — **현재 BE 확인 대기 중, 추가로 재촉하지 않습니다.**

## 11. 신규 테이블 (AI 리드 확정, 2026-09 — BE 승인 대기)

### `case_equipment_item` — 집기·장비 처리 현황

`EQUIPMENT_DISPOSAL` 절차는 업종마다 처리해야 할 물건이 다르고(카페: 의자·테이블·커피머신 등), 이 물건들은 미리 정해둔 고정 목록이 아니라 **Agent와 사용자 간 대화를 통해 그때그때 파악**해서 저장합니다(자유 텍스트가 아니라 구조화된 표로 관리).

| 필드 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| case_id | BIGINT FK → case.id | |
| item_name | VARCHAR | 예: "커피머신", "테이블(4인용)" |
| disposal_plan | VARCHAR | 사용자가 정한 처리 방침(예: "중고 판매", "폐기", "이전 사용") — `decision_authority=USER`이므로 AI가 방침을 추천하지 않고 사용자가 말한 내용을 그대로 기록 |
| status | ENUM | `NOT_STARTED`/`IN_PROGRESS`/`COMPLETED` (§1.2와 동일 값 재사용, `APPROVAL_PENDING`/`SKIPPED`는 이 항목엔 해당 없음) |
| created_at / updated_at | DATETIME | |

### `support_check_result` — 지원 비교 상태(`match_status`) 저장

`match_status`(§1.4)를 저장할 곳이 기존 9개 테이블 어디에도 없었습니다(재검증 결과, `subsidy_application`에 컬럼으로 추가하는 안은 폐기 — 아래 이유 참고).

| 필드 | 타입 | 설명 |
|---|---|---|
| id | BIGINT PK | |
| case_id | BIGINT FK → case.id | |
| support_item_id | BIGINT FK → support_item.id | |
| match_status | ENUM | §1.4 (`NOT_CHECKED`/`POSSIBLY_RELEVANT`/`NEEDS_CONFIRMATION`/`NOT_RELEVANT`/`STALE`) |
| checked_at | DATETIME | 마지막 비교 시각 |
| source_version | VARCHAR | 비교에 사용한 `support_item.source_notice_version` 스냅샷 — STALE 판정에 사용 |
| evidence_refs | JSON | `[evidence_id, ...]` |

**`subsidy_application`에 넣지 않은 이유**: `match_status`는 사용자가 신청 여부를 결정하기 **전에** 이미 존재해야 하는 값인데, `subsidy_application`은 "Agent가 지원항목을 발견했다고 자동 생성하지 않는다"(§1.5)는 원칙이 있어 이 테이블에 넣으면 저장하는 순간 자동 생성 금지 원칙과 모순됩니다. 그래서 신청 여부와 무관하게 독립적으로 존재할 수 있는 별도 테이블로 분리합니다.

**`STALE` 판정 기준(AI 리드 확정, 2026-09)**: 날짜 경과가 아니라 **원문 비교 결과**로 판정합니다 — 매일 1회(주기 확정, 구체 메커니즘은 APScheduler vs cron **BE 확인 필요**) 공식 원문을 다시 조회해서 `support_item.document_hash`/`source_notice_version`이 바뀐 게 확인되면 관련 `support_check_result.match_status`를 `STALE`로 갱신합니다. "며칠 지나면 오래됨" 같은 날짜 임계값은 근거 없이 지어내는 것이라 쓰지 않습니다(§6.2의 "예시 문구를 영구 정책값으로 하드코딩하지 않는다" 원칙과 동일).

## 12. 되돌리기(Undo) 메커니즘 (AI 리드 확정, 2026-09)

사용자가 "이전" 버튼을 누르면 **바로 직전 1단계 처리만** 되돌릴 수 있습니다(여러 단계 소급 되돌리기는 MVP 범위 밖 — 잘못 누르면 오래된 상태로 확 돌아가버리는 위험을 피하기 위함).

**동작 방식**: 가장 최근 `case_history`의 `changed_fields`(`[{field, before, after}, ...]`)를 읽어서 `after`→`before`로 되돌리는 값을 새로운 Case UPDATE로 반영하고, `event_type=ACTION_REVERTED`인 새 `case_history` 행을 추가합니다(§4 "기존 기록은 절대 지우지 않는다" 원칙 그대로 유지 — 되돌리기도 삭제가 아니라 새 기록 추가입니다). 이후 Rule 엔진을 다시 실행해서 되돌려진 케이스 상태 기준으로 Blocker/Next Action을 재계산합니다(R5와 동일 흐름).

**API**: `docs/interface-spec.md` §5.1 `POST /cases/{caseId}/rollback` 참고.

---

## 출처

| 섹션 | 원본 |
|---|---|
| §1 다섯 가지 개념, §1.1~1.4 enum | `RE_BORN_AI리드_설계안.md` §3.1 |
| §1.2 절차 상태 4단계 병합 | `Q&A.md` M6 (구 미시작/진행중/승인대기/완료) + `RE_BORN_AI리드_설계안.md` §3.1 (3단계 단순화) 병합 |
| §1.5 `subsidy_application.application_status` | `BE_AI_역할분담_및_연동스펙.md` §8.5 |
| §2 테이블 스키마 (9개 전체) | 사용자가 공유한 Notion "Closure Case 최종 DB 스키마"(2026-09) 그대로 채택 — 이전 버전(`BE_AI_역할분담_및_연동스펙.md` §4.1 테이블명만, `RE_BORN_AI리드_설계안.md` §3.2 `case` 필드만)을 대체. `member_id` FK 등 검증 워크플로우가 지적한 누락 컬럼이 이 버전에는 이미 있음 |
| §2.1 `lease_status` 불일치, §2.2 `case_status` enum | 검증 워크플로우 지적사항 — 실제 seed 데이터(`LEASED_PAID`)와 확정 스키마(`LEASED`/`OWNED`) 간 괴리, `case_status` enum 값 부재를 신규로 명시 |
| §3 `case.version` | `BE_AI_역할분담_및_연동스펙.md` §5.4 |
| §4 `case_history` 병합 스키마 | `BE_AI_역할분담_및_연동스펙.md` §5.2~5.3 + `RE_BORN_AI리드_설계안.md` §10.2 병합. `decision_json`은 `docs/interface-spec.md` §11.3 `RuleDecision`과 동일 shape로 정정(검증 워크플로우 지적) |
| §4 MySQL 확정(JSONB→JSON 정정) | 사용자가 공유한 "백엔드 기술스택 최종 확정" 표(2026-09) — DB 엔진이 MySQL로 확정되어 컬럼 타입 표기를 JSON으로 단일화 |
| §4.1 `event_type` enum, Loop 집계 기준 | `RE_BORN_AI리드_설계안.md` §10.1, §10.3 |
| §5 Rule Set R1–R10 | `RE_BORN_AI리드_설계안.md` §4.1 (다른 두 버전 `agent설계.md` §4, `RE_BORN_테크스펙_회의준비_승준.md`과 근접, 가장 정제된 버전 채택) |
| §6 `NextActionSelector` 우선순위, §6.1 함수 시그니처, §6.2 상태 전이표 | 우선순위는 `RE_BORN_AI리드_설계안.md` §4.2 (AI 리드 확정 결정), 함수 시그니처·전이표는 검증 워크플로우가 지적한 구현가능성 공백을 메우기 위해 신규 작성(권장안) |
| §7~8 `support_item`/`Evidence` 스키마 | `RE_BORN_AI리드_설계안.md` §7.2~7.3 |
| §9 첫 지원사업 슬라이스 | `support_item_점포철거비지원.json` + `RE_BORN_AI리드_설계안.md` §15 질문 2 |
| §10 TBD | `RE_BORN_AI리드_설계안.md` §9.5, `interface-spec.md`(이 저장소) §13 |
