# RE:BORN 인터페이스 명세

> FE/BE API 인터페이스 정의. **API를 추가하거나 변경하기 전에 이 문서를 확인/갱신하세요.**
> DRI: FE/BE 합의, 최종 정리는 BE 제안 (`docs/tech-stack.md` §4.5).
> enum 값은 `docs/data-model.md`를, Agent 노드 책임은 `docs/architecture.md`를 참고 — 여기서는 재정의하지 않고 인용합니다.

## 1. 엔드포인트 목록

| Method | Path | 목적 |
|---|---|---|
| GET | `/auth/kakao/login` | 카카오 로그인 시작 |
| GET | `/auth/kakao/callback` | 카카오 OAuth callback |
| POST | `/cases` | Case 생성 + 최초 판단 |
| GET | `/cases/{caseId}` | 현재 Case 상태 조회 (AI 호출 없음) |
| POST | `/cases/{caseId}/results` | ⭐ 핵심 — 결과 입력 → 검증 → Case 갱신 → 재계획 |
| POST | `/cases/{caseId}/results/confirm` | Conflict 확인 후 반영 |
| GET | `/cases/{caseId}/subsidies` | Case에 연결된 지원항목 상태 조회 |
| PATCH | `/subsidy-applications/{applicationId}` | 지원항목 신청 진행상태 변경 |
| GET | `/cases/{caseId}/history` | 과거 입력·판단 조회 (선택, 별도 History 화면 없으면 우선순위 낮음) |
| POST | `/cases/{caseId}/rollback` | "이전" 버튼 — 직전 1단계 처리만 되돌림 (§5.1 참고, AI 리드 확정 2026-09) |

**별도의 `/replan` 엔드포인트는 만들지 않습니다** — 결과 입력이 성공한 뒤 같은 요청(`/results`) 안에서 재계획합니다.

## 2. 인증 — 카카오 OAuth + 자체 발급 JWT (확정)

`docs/tech-stack.md` §2 확정 사항: 카카오 OAuth로 사용자를 식별하고, 이후 요청은 **우리가 직접 발급한 Access/Refresh JWT**(PyJWT)로 인증합니다. 세션 방식이 아닙니다.

```
GET /auth/kakao/login
 → 카카오 로그인 페이지로 redirect

GET /auth/kakao/callback?code=...
 → 카카오 토큰 교환(httpx) → 카카오 사용자정보 조회
 → members.oauth_id로 기존 회원 조회
    ├─ 기존 회원 → members.refresh_token(카카오 발급분) 갱신
    └─ 신규 회원 → members 생성(oauth_id, refresh_token 저장)
 → 우리 서버가 Access/Refresh JWT 발급(PyJWT, memberId를 payload에 포함)
 → FE로 Access/Refresh JWT 전달
```

이후 모든 `/cases/*` 요청은 `Authorization: Bearer {accessToken}` 헤더를 포함해야 합니다. BE는 이 토큰의 `memberId`와 `case.member_id`가 일치하는지 확인한 뒤에만 응답합니다(`/CLAUDE.md` "사용자는 본인의 Case만 조회할 수 있어야 한다").

**명시적 TBD** (BE 확인 필요, 지어내지 않음): Access/Refresh JWT를 FE에 전달하는 방식(JSON body vs `httpOnly` 쿠키), Refresh 토큰 회전·저장(DB에 별도 저장할지 stateless로 둘지), 만료 시간, 카카오 `refresh_token`(members 테이블)과 우리 JWT refresh 토큰은 서로 다른 토큰이라는 점을 FE가 헷갈리지 않도록 할 문서화.

## 3. `POST /cases` — Case 생성

### Request

```json
{
  "rawInput": "카페를 폐업하려고 합니다. 임차 점포이고 원상복구 범위와 철거 여부는 아직 모릅니다.",
  "businessType": "CAFE",
  "franchiseStatus": false,
  "employeeCount": 2,
  "leaseStatus": "LEASED_PAID",
  "plannedClosureDate": null
}
```

자연어(`rawInput`)만으로 생성할지, 구조화 필드를 함께 받을지는 화면 설계에 따라 다르지만 서버는 최소한 위 구조화 필드는 선택적으로 받습니다. `businessType`/`franchiseStatus`/`employeeCount`/`leaseStatus`/`plannedClosureDate`는 `docs/data-model.md` §2 `case` 테이블 필드와 1:1 camelCase 매핑입니다.

### Response

```json
{
  "case": {
    "id": 1,
    "caseVersion": 1,
    "businessType": "CAFE",
    "franchiseStatus": false,
    "employeeCount": 2,
    "leaseStatus": "LEASED_PAID",
    "restorationStatus": "UNKNOWN",
    "restorationScope": "UNKNOWN",
    "demolitionRequired": "UNKNOWN",
    "caseStatus": "IN_PROGRESS",
    "plannedClosureDate": null
  },
  "stepProgress": [
    { "procedureStepId": 1, "stepCode": "RESTORATION_CHECK", "stepName": "원상복구 범위 확인", "status": "NOT_STARTED" }
  ],
  "decision": {
    "blocker": "원상복구 범위가 아직 확인되지 않았습니다.",
    "nextAction": "임대인에게 원상복구 범위를 확인하세요.",
    "requiresHuman": false,
    "evidenceRefs": []
  }
}
```

**`stepProgress`는 `evaluate_step_eligibility(case)`(`docs/data-model.md` §6.1)가 반환하는 모든 절차를 초기화합니다** — 위 예시는 지면상 1개만 보여준 것이고, 실제로는 이 예시 조건(`employeeCount: 2`, `leaseStatus: LEASED_PAID`)에서 `RESTORATION_CHECK`/`EQUIPMENT_DISPOSAL`/`LEASE_TERMINATION_NOTICE`/`EMPLOYEE_SEPARATION`/`CLOSURE_REPORT` 5개가 함께 `NOT_STARTED`로 초기화됩니다(`DEMOLITION`만 `demolition_required`가 아직 `UNKNOWN`이라 제외). 아래 §4 예시도 동일 규칙을 따릅니다.

## 4. `GET /cases/{caseId}` — 현재 Case 조회 (AI 호출 없음)

```json
{
  "case": {
    "id": 1,
    "caseVersion": 3,
    "businessType": "CAFE",
    "franchiseStatus": false,
    "employeeCount": 2,
    "leaseStatus": "LEASED_PAID",
    "restorationStatus": "IN_PROGRESS",
    "restorationScope": "DEMOLITION_REQUIRED",
    "demolitionRequired": "REQUIRED",
    "caseStatus": "IN_PROGRESS",
    "plannedClosureDate": null
  },
  "stepProgress": [
    { "procedureStepId": 1, "stepCode": "RESTORATION_CHECK", "stepName": "원상복구 범위 확인", "status": "COMPLETED" },
    { "procedureStepId": 2, "stepCode": "DEMOLITION", "stepName": "철거", "status": "NOT_STARTED" }
  ],
  "latestDecision": {
    "historyId": 15,
    "blocker": "원상복구 범위가 아직 확인되지 않았습니다.",
    "nextAction": "임대인에게 원상복구 범위를 확인하세요.",
    "requiresHuman": false,
    "evidenceRefs": []
  }
}
```

`case.caseVersion`을 FE가 저장해두었다가 다음 `/results` 요청의 `expectedVersion`으로 그대로 보냅니다. FE는 Blocker/Next Action을 직접 계산하지 않습니다 — `latestDecision`은 `case_history` 최신 판단을 그대로 반환한 것입니다.

## 5. `POST /cases/{caseId}/results` (핵심)

### 처리 흐름

`docs/architecture.md` §5 참고. FE → BE(버전·소유권 확인) → 정보분석 Agent(FactCandidate) → Validator → Case UPDATE → Rule 엔진 → (필요시) 지원금 Agent → Response Writer → History INSERT → FE.

### Request

```json
{
  "rawInput": "임대인이 철거해야 한다고 했어요.",
  "expectedVersion": 6,
  "clientEventId": "event-client-001"
}
```

`procedureStepId`는 주 계약에서 **제외**합니다(서버가 현재 Case 상태로부터 적용 대상 절차를 스스로 판단) — 다만 FE가 현재 화면 context를 함께 보내는 것이 UX상 필요한지는 **BE·FE 확정 필요**입니다.

### Response

```json
{
  "result": "UPDATED",
  "caseVersion": 7,
  "changes": [
    { "field": "demolitionRequired", "previousValue": "UNKNOWN", "newValue": "REQUIRED" }
  ],
  "decision": {
    "blockerCode": "SUPPORT_CHECK_REQUIRED",
    "blocker": "철거 관련 지원 조건 확인이 필요합니다.",
    "nextActionCode": "VERIFY_SUPPORT_BEFORE_DEMOLITION",
    "nextAction": "철거 전에 관련 지원 조건과 필요 서류를 확인하세요.",
    "requiresHuman": true,
    "evidenceRefs": ["support-document-2026-001"]
  }
}
```

JSON API 필드는 `camelCase`를 따릅니다 (`/CLAUDE.md` 용어 규칙). `blockerCode`/`nextActionCode`는 FE가 아이콘·배지를 분기할 때 쓰는 값이고, `requiresHuman`은 §4.3 `RuleDecision.next_action.requires_human`을 그대로 노출한 것입니다(R8 — 법률·세무 등은 사람 판단 필요함을 화면에서 구분 표시).

### 5.1 `POST /cases/{caseId}/rollback` — 직전 처리 되돌리기 (AI 리드 확정, 2026-09)

가장 최근 `case_history`의 `changed_fields`를 반대로 적용해 케이스를 되돌리고, Rule 엔진을 다시 실행합니다(`docs/data-model.md` §12 참고). **한 번에 1단계만** 되돌릴 수 있습니다 — 연속 호출로 여러 단계를 소급하는 것은 막습니다.

### Request

```json
{ "expectedVersion": 7 }
```

### Response

`POST /results`의 `UPDATED` 응답과 동일한 shape(§5)을 반환합니다 — `caseVersion`은 되돌린 뒤 새로 증가한 값이고, `changes`는 되돌아간 필드들을 보여줍니다.

되돌릴 대상이 없거나(변경 이력이 없는 케이스) 직전 이벤트가 이미 되돌리기였다면(연속 되돌리기 방지, `docs/data-model.md` §12) `{"result": "NOTHING_TO_ROLLBACK"}`을 반환합니다(§12 에러/상태 처리 표 참고).

## 6. `POST /cases/{caseId}/results/confirm` — Conflict 확인 후 반영

### Request

```json
{
  "rawInput": "다시 확인했는데 철거해야 한대요.",
  "confirmedChanges": [
    { "field": "demolitionRequired", "value": "REQUIRED" }
  ]
}
```

### Response

`POST /results`의 `UPDATED` 응답과 동일한 shape(§5)을 반환합니다 — 사용자가 확인한 값으로 Case UPDATE + 정정 History INSERT + Rule 재실행까지 마친 뒤의 결과입니다.

## 7. `GET /cases/{caseId}/subsidies` — 지원항목 상태 조회

```json
{
  "items": [
    {
      "applicationId": null,
      "supportItemId": 3,
      "itemName": "점포철거비 지원",
      "applicationStatus": null,
      "matchStatus": "NEEDS_CONFIRMATION",
      "appliedAt": null,
      "sourceUrl": "https://www.sbiz.or.kr/nhrp/cnsl/storRemvlCnslInfo.do?cMenuNo=100301"
    }
  ]
}
```

**신청 전**(=`subsidy_application` 행이 아직 없는) 항목은 `applicationId`/`applicationStatus`/`appliedAt`을 전부 `null`로 반환합니다(AI 리드 확정, 2026-09) — `subsidy_application`을 자동 생성하지 않는다는 원칙(§1.5)과 일관됩니다. `matchStatus`는 `subsidy_application`과 무관하게 `support_check_result`(`docs/data-model.md` §11)에서 조회하므로 신청 여부와 상관없이 항상 채워집니다. 사용자가 실제로 신청해서 `subsidy_application` 행이 생긴 뒤부터 `applicationId`/`applicationStatus`가 채워집니다.

`applicationStatus`는 `subsidy_application` 테이블 값(`docs/data-model.md` §1.5), `matchStatus`는 저장된 `SupportCheckResult.match_status`(§1.4)입니다 — 서로 다른 축이므로 응답에도 둘 다 노출합니다. FE는 자격조건을 직접 계산하지 않습니다.

## 8. `PATCH /subsidy-applications/{applicationId}` — 신청 진행상태 변경

사용자가 실제로 신청을 완료했을 때만 호출합니다(조회만으로 자동 생성/변경되지 않음).

### Request

```json
{ "applicationStatus": "APPLIED" }
```

### Response

```json
{
  "id": 21,
  "supportItemId": 3,
  "applicationStatus": "APPLIED",
  "appliedAt": "2026-09-07T21:20:00",
  "updatedAt": "2026-09-07T21:20:00"
}
```

사용자가 자연어로 "지원금 신청했어요"라고 입력하는 UX를 유지한다면, 이 엔드포인트를 FE가 직접 호출하지 않고 `/results` 내부 처리로 대체할 수도 있습니다 — 실제 화면 UX 확정 후 결정합니다.

## 9. `GET /cases/{caseId}/history` — 과거 입력·판단 조회 (선택)

```json
{
  "history": [
    {
      "id": 15,
      "procedureStep": { "id": 1, "stepCode": "RESTORATION_CHECK", "stepName": "원상복구 범위 확인" },
      "rawInput": "임대인에게 확인했는데 철거가 필요하다고 합니다.",
      "blocker": "철거 관련 지원조건이 아직 확인되지 않았습니다.",
      "nextAction": "관련 지원항목의 조건과 필요한 증빙을 확인하세요.",
      "createdAt": "2026-09-07T20:30:00"
    }
  ]
}
```

MVP에서 별도 History 화면이 없다면 구현 우선순위는 낮습니다.

## 10. 기타 엔드포인트 — BE/AI 책임 분담

| Endpoint | BE | AI/Agent |
|---|---|---|
| `POST /cases` | 인증·소유권, Case 생성, `case_step_progress` 초기화, History 저장, 최종 응답 조립 | FactCandidate 생성, 누락 필드 질문, Rule에 전달할 구조화 상태 반환 |
| `GET /cases/{caseId}` | Case/진행상태/최신 History 조회, 응답 생성 | 호출하지 않는 것이 기본 — 단순 조회에 LLM 불필요 |
| `POST /results/confirm` | 충돌 대상·소유권 확인, 사용자가 선택한 값을 Transaction으로 UPDATE, 정정 History INSERT, Rule 재실행 | 충돌 내용을 이해하기 쉬운 문장으로 설명, 확인 질문 생성 |
| `GET /cases/{caseId}/subsidies` | Case에 연결된 지원항목·신청 상태 조회 | 저장된 `SupportCheckResult`가 없거나 오래된 경우 지원금 Agent 실행 |
| `PATCH /subsidy-applications/{applicationId}` | 신청 상태 변경 (사용자가 실제 신청 결과를 입력할 때만) | 해당 없음 — 조회만으로 `subsidy_application`을 자동 생성하지 않음 |

## 11. LLM/Rule JSON 계약

> 아래 JSON은 Agent 노드/Rule 엔진 간 **내부 계약**이며 DB 컬럼명과 맞춰 의도적으로 `snake_case`를 씁니다 — 루트 `/CLAUDE.md`의 "JSON API 필드는 camelCase" 규칙은 §3~§9의 FE-BE 외부 API 응답에만 적용되고, 이 섹션의 내부 계약에는 적용되지 않습니다.

### 11.1 `FactCandidate` (정보분석 Agent 출력)

```json
{
  "facts": [
    {
      "field_path": "demolition_required",
      "value": "REQUIRED",
      "source_span": "임대인이 철거해야 한다고 했어요",
      "confidence": 0.98,
      "requires_confirmation": false,
      "reason": "철거 필요를 직접 표현함",
      "parser_version": "input-parser-v1"
    }
  ],
  "equipment_items": [
    {
      "item_name": "커피머신",
      "disposal_plan": "폐기",
      "source_span": "커피머신은 그냥 버리려고요"
    }
  ],
  "questions": [],
  "uncertain_fields": []
}
```

규칙:
- `confidence`는 참고용이며 BE가 단독 승인 기준으로 사용하지 않습니다.
- `field_path`는 자유 문장이 아니라 허용된 Case 필드 화이트리스트에서만 선택합니다.
- `source_span`은 사용자 입력에 실제로 존재해야 합니다.
- 애매한 표현은 `requires_confirmation: true` 또는 `uncertain_fields`로 반환합니다.
- 문장에 없는 필드의 기본값을 만들어내지 않습니다.
- **`equipment_items`(신규, AI 리드 2026-09)**: `case` 테이블의 scalar 필드가 아니라 `case_equipment_item`(`docs/data-model.md` §11) 각 행으로 저장됩니다 — `facts` 배열과 다른 대상이라 별도 배열로 분리했습니다. `item_name`/`disposal_plan`은 미리 정해둔 목록이 아니라 사용자가 말한 그대로 기록합니다(추정 금지 원칙 동일 적용).

**금지되는 출력 예시** (절대 반환하면 안 되는 형태):

```json
{ "eligible": true, "tax_due": 3000000, "best_closure_date": "2026-09-30" }
```

### 11.2 `ValidationResult`

가능한 `result` 값:

```
UPDATED
NO_CHANGE
NEEDS_MORE_INFO
CONFLICT
CASE_NOT_FOUND
INVALID_TRANSITION
REPLAN_FAILED
```

(`STALE_SUPPORT_DATA`는 이 enum에 속하지 않습니다 — `docs/data-model.md` §1.4 `match_status`의 `STALE`과 같은 개념이며, `GET /cases/{caseId}/subsidies` 응답의 `matchStatus` 필드에서만 나타납니다. `/results`의 최상위 `result` 필드에는 나타나지 않습니다 — §12 에러 표에서 별도로 다룹니다.)

```json
{
  "result": "UPDATED",
  "accepted_facts": [
    { "field_path": "demolition_required", "before": "UNKNOWN", "after": "REQUIRED", "source_type": "USER_INPUT" }
  ],
  "conflicts": [],
  "missing_fields": [],
  "warnings": []
}
```

### 11.3 `RuleDecision` (Rule 엔진 출력)

```json
{
  "case_id": 1,
  "case_version": 7,
  "blocker": {
    "code": "SUPPORT_CHECK_REQUIRED",
    "reason": "철거 전에 공식 지원 조건과 필요한 증빙을 확인해야 합니다.",
    "affected_fields": ["demolition_required", "support_check_status"]
  },
  "next_action": {
    "code": "VERIFY_SUPPORT_BEFORE_DEMOLITION",
    "title": "점포철거비 지원 조건 확인",
    "reason": "철거 후에는 신청·증빙 조건을 충족하지 못할 수 있어 먼저 확인해야 합니다.",
    "questions": ["철거 예정일과 임대차 종료일은 언제인가요?"],
    "requires_human": true
  },
  "evidence_refs": ["support-notice-2026-v2", "case-history-15"],
  "rule_version": "rules-v1"
}
```

`RuleDecision`의 문장은 LLM이 새로 판단하는 값이 아니라, Rule 엔진이 선택한 `code`/`reason`/`evidence_refs`를 Response Writer(Supervisor)가 자연스럽게 표현하는 구조입니다.

### 11.4 `SupportCheckResult` (지원금 Agent 출력)

```json
{
  "support_item_id": 10,
  "match_status": "NEEDS_CONFIRMATION",
  "criteria": [
    {
      "criterion_code": "LEASED_BUSINESS_PLACE",
      "case_value": "LEASED_PAID",
      "required_value": "LEASED_PAID",
      "status": "MET",
      "evidence_refs": ["evidence-001"]
    },
    {
      "criterion_code": "PREVIOUS_SUPPORT_HISTORY",
      "case_value": null,
      "required_value": "NO_DUPLICATE_SUPPORT",
      "status": "UNKNOWN",
      "evidence_refs": ["evidence-002"]
    }
  ],
  "unknown_fields": ["previous_support_history"],
  "required_documents": ["임대차계약서", "철거 관련 증빙"],
  "application_channel": "SMALL_BUSINESS_24",
  "application_url": "https://www.sbiz24.kr/",
  "evidence_refs": ["evidence-001", "evidence-002"],
  "source_version": "2026-revision-2"
}
```

`match_status` 값은 `docs/data-model.md` §1.4를 참고하세요. `ELIGIBLE`은 사용하지 않습니다. `case_value`/`required_value`의 `LEASED_PAID`는 `docs/data-model.md` §2.1에서 다루는 미확정 enum 확장안입니다 — `lease_status`가 실제로 `LEASED_PAID`/`LEASED_FREE`/`OWNED`로 확장되기 전까지는 예시 표기입니다.

## 12. 에러/상태 처리 표

| 값 | HTTP 상태 | 의미 | FE 처리 |
|---|---|---|---|
| `UPDATED` | 200 | 정상 반영, 재계획 완료 | 변경사항 + 새 Blocker/Next Action 표시 |
| `NO_CHANGE` | 200 | 새로운 상태 변화 없음 | 현재 상태 유지 |
| `NEEDS_MORE_INFO` | 200 | 입력만으로 상태 확정 불가 | 추가 질문 표시 |
| `CONFLICT` | 200 | 기존 Case와 새 입력이 충돌 | 사용자 확인 UI, `/results/confirm` 유도 |
| `INVALID_TRANSITION` | 200 | 상태 기계상 허용되지 않는 전이 | 정정 입력 요청 |
| `REPLAN_FAILED` | 200 | Case 반영 후 판단 생성 실패 | §13 TBD 참고 — 재시도/오류 안내 |
| `NOTHING_TO_ROLLBACK` | 200 | `/rollback` 호출 시 되돌릴 대상이 없거나 직전 이벤트가 이미 되돌리기였음 | "이전" 버튼 비활성화 안내 (`docs/data-model.md` §12) |
| `CASE_NOT_FOUND` | 404 | Case 없음 또는 접근 권한 없음 | 오류 화면 |

**규칙**: 검증 실패(`NEEDS_MORE_INFO`/`CONFLICT`/`INVALID_TRANSITION`/`REPLAN_FAILED`)를 포함해 요청 자체가 정상 처리된 경우는 항상 HTTP 200을 반환하고, FE는 `res.ok`가 아니라 **본문의 `result` 필드로 분기**해야 합니다. `CASE_NOT_FOUND`(권한 없음 포함)만 404입니다. `STALE_SUPPORT_DATA`는 이 표에 속하지 않습니다 — §11.2 설명대로 `GET /subsidies`의 `matchStatus` 필드 값(`STALE`)이며 `/results`의 `result`에는 나타나지 않습니다.

## 13. 명시적 TBD

- **`REPLAN_FAILED` 응답 형태**: Case는 이미 UPDATE된 상태에서 재계획만 실패했을 때, 응답의 `caseVersion`을 갱신된 값으로 반환할지 롤백할지 확정되지 않았습니다. `docs/data-model.md` §10과 동일 이슈 — **BE 멘토링·팀 회의에서 정합니다**.
- **Conflict 임시 저장 방식**: `/results/confirm` 호출 시 충돌 후보를 서버에 `conflict_id`로 임시 저장할지, 클라이언트가 후보값을 다시 전송할지 미정 (`BE_AI_역할분담_및_연동스펙.md` §7 `[확인 필요]`).
- **JWT 전달·저장 방식**: §2 참고 — Access/Refresh를 body로 줄지 쿠키로 줄지, refresh 회전 방식.
- **`refresh_token`(카카오) 저장 방식**: 평문 저장 금지 원칙만 확정, 암호화 또는 별도 인증 테이블 등 구체 방식은 BE 확인 필요 (`/CLAUDE.md` 개인정보 섹션과 연계).
- **`procedureStepId` 포함 여부**: §5 참고, FE·BE 확정 필요.

---

## 출처

| 섹션 | 원본 |
|---|---|
| §1 엔드포인트 목록 | `todo.md` §5 / `BE_AI_역할분담_및_연동스펙.md` §7 / `history` 행은 사용자가 공유한 Notion 인터페이스 명세 §5-8 |
| §2 인증 흐름 | `docs/tech-stack.md` §2(BE기술스택.html 확정: 카카오 OAuth + PyJWT) + 사용자가 공유한 Notion 인터페이스 명세 §5-1 |
| §3 `POST /cases` | 사용자가 공유한 Notion 인터페이스 명세 §5-2 (요청/응답 예시 그대로 채택, camelCase 확인) |
| §4 `GET /cases/{caseId}` | 사용자가 공유한 Notion 인터페이스 명세 §5-3 (`caseVersion` 필드는 §5 버저닝과 일관성 위해 추가) |
| §5 `POST /results` | `BE_AI_역할분담_및_연동스펙.md` §7 (`POST /cases/{caseId}/results`), `blockerCode`/`nextActionCode`/`requiresHuman`은 §11.3 `RuleDecision`과의 정합성을 위해 신규 추가(구현가능성 검증에서 지적) |
| §6 `results/confirm` | 사용자가 공유한 Notion 인터페이스 명세 §5-5 |
| §7 `subsidies` 조회 | 사용자가 공유한 Notion 인터페이스 명세 §5-6, `matchStatus` 필드는 신규 추가(§11.4 `SupportCheckResult`와 연결) |
| §8 `subsidy-applications` PATCH | 사용자가 공유한 Notion 인터페이스 명세 §5-7 |
| §9 `history` 조회 | 사용자가 공유한 Notion 인터페이스 명세 §5-8 |
| §10 BE/AI 책임 분담 | `BE_AI_역할분담_및_연동스펙.md` §7 |
| §11.1 `FactCandidate` | `RE_BORN_AI리드_설계안.md` §5.1 (필드가 더 상세한 버전 채택), 금지 예시는 `BE_AI_역할분담_및_연동스펙.md` §6.1 |
| §11.2 `ValidationResult` | `RE_BORN_AI리드_설계안.md` §5.2 + `BE_AI_역할분담_및_연동스펙.md` §6.2 (enum 통합), `STALE_SUPPORT_DATA`/`STALE` 매핑은 검증 워크플로우에서 지적된 불일치 해소 |
| §11.3 `RuleDecision` | `RE_BORN_AI리드_설계안.md` §5.3 |
| §11.4 `SupportCheckResult` | `RE_BORN_AI리드_설계안.md` §5.4 (criteria 배열이 더 상세한 버전 채택), `LEASED_PAID` 정정은 `docs/data-model.md` §2.1과 통일 |
| §12 에러/상태 표 | `RE_BORN_AI리드_설계안.md` §9.5, HTTP 상태 열은 검증 워크플로우 지적사항 반영 신규 추가 |
| §13 TBD | `RE_BORN_AI리드_설계안.md` §9.5, §12 / `BE_AI_역할분담_및_연동스펙.md` §7, §12 / `todo.md` §5 — 인증 방식은 §2에서 해소되어 이 목록에서 제거 |
