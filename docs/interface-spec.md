# RE:BORN 인터페이스 명세

> FE/BE API 인터페이스 정의. **API를 추가하거나 변경하기 전에 이 문서를 확인/갱신하세요.**
> DRI: FE/BE 합의, 최종 정리는 BE 제안 (`docs/tech-stack.md` §4.5).
> Agent·Tool 책임과 실행 순서는 `docs/architecture.md`를 따릅니다. 물리 DB 초안은 `docs/schema/schema_table.md`를 참고하되, 외부 API와 DB의 정확한 매핑은 FE·BE 합의로 확정합니다.
>
> **주의:** 아래 JSON의 `caseVersion`·`expectedVersion`과 enum 예시는 기존 제안이며 아직 BE 물리 schema와 일치하지 않습니다. 동시성 제어 방식과 enum 계약이 확정되기 전에는 구현 기준으로 사용하지 않습니다.

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

자연어(`rawInput`)만으로 생성할지, 구조화 필드를 함께 받을지는 화면 설계에 따라 다릅니다. 아래 필드와 물리 DB의 정확한 매핑은 BE schema 확정 후 함께 갱신합니다. `entityType`/`buildingUseType`/`previousSupportHistory`는 이 요청에 포함하지 않고, 이후 대화(`/results`)에서 확인하는 현재 제안을 유지합니다.

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
    "entityType": "UNKNOWN",
    "buildingUseType": "UNKNOWN",
    "previousSupportHistory": "UNKNOWN",
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

**`stepProgress` 초기화 대상은 절차조회 Tool이 반환한 적용 가능 후보를 기준으로 합니다.** 정확한 절차 목록과 적용 조건은 Agent/Tool 계약 및 BE 절차 데이터가 확정된 뒤 이 예시와 함께 갱신합니다.

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
    "entityType": "UNKNOWN",
    "buildingUseType": "UNKNOWN",
    "previousSupportHistory": "UNKNOWN",
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

`caseVersion`/`expectedVersion`은 동시 변경 방지를 위한 기존 제안이며 최종 채택 전입니다. FE는 Blocker/Next Action을 직접 계산하지 않고, `latestDecision`은 BE가 확정할 최신 판단 이력 저장소의 값을 반환합니다.

## 5. `POST /cases/{caseId}/results` (핵심)

### 처리 흐름

`docs/architecture.md`를 따릅니다. 입력 Guardrail과 CaseSnapshot 조회 후 Supervisor가 필요한 Agent-as-Tool·절차조회 Tool을 선택 호출하고, Blocker·Next Action 초안은 필수 Review와 Output Guardrail을 모두 통과해야 저장·전달됩니다.

### Request

```json
{
  "rawInput": "임대인이 철거해야 한다고 했어요.",
  "expectedVersion": 6,
  "clientEventId": "event-client-001"
}
```

`procedureStepId`는 주 계약에서 **제외**합니다(서버가 현재 Case 상태로부터 적용 대상 절차를 스스로 판단) — 다만 FE가 현재 화면 context를 함께 보내는 것이 UX상 필요한지는 **BE·FE 확정 필요**입니다.

`expectedVersion`을 유지할지 다른 동시성 제어 방식을 쓸지는 BE 계약에서 정합니다. 같은 보호가 `/results/confirm`에도 필요하며, 현재 예시에 필드가 없다는 점도 함께 확정해야 합니다.

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

JSON API 필드는 `camelCase`를 따릅니다 (`/CLAUDE.md` 용어 규칙). `blockerCode`/`nextActionCode`는 FE가 아이콘·배지를 분기할 때 쓰는 값이고, `requiresHuman`은 Supervisor가 사용자 확인 필요성을 판단한 최종 결과입니다. 필드의 최종 채택 여부는 Agent 출력 schema와 함께 확정합니다.

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

`POST /results`의 `UPDATED` 응답과 동일한 shape(§5)을 반환합니다. 확인된 값의 상태 전이 검증, Case·이력 저장, Supervisor 재계획·필수 Review를 수행하되 정확한 저장 순서와 트랜잭션 경계는 TBD입니다.

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

**신청 전**(=`subsidy_application` 행이 아직 없는) 항목은 `applicationId`/`applicationStatus`/`appliedAt`을 전부 `null`로 반환합니다. `matchStatus`의 물리 저장 방식은 BE schema 확정 대상이며, 조회만으로 신청 행을 자동 생성하지 않습니다.

`applicationStatus`와 지원조건 비교 결과인 `matchStatus`는 서로 다른 축이므로 응답에도 둘 다 노출합니다. FE는 자격조건을 직접 계산하지 않습니다.

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
| `POST /cases` | 인증·소유권, Case 생성, 진행상태 초기화, History 저장, API 응답 | Supervisor 실행, 필요한 Agent·Tool 호출, 누락 질문과 최종 판단 생성 |
| `GET /cases/{caseId}` | Case/진행상태/최신 History 조회, 응답 생성 | 호출하지 않는 것이 기본 — 단순 조회에 LLM 불필요 |
| `POST /results/confirm` | 충돌 대상·소유권 확인, 사용자 선택값의 상태 전이 검증과 저장 | 확인된 CaseSnapshot으로 Supervisor 재계획·Review 수행. 저장 경계는 공동 확정 |
| `GET /cases/{caseId}/subsidies` | Case에 연결된 지원항목·신청 상태 조회 | 저장된 비교 결과가 없거나 오래된 경우 Supervisor가 지원금 Agent-as-Tool 호출 |
| `PATCH /subsidy-applications/{applicationId}` | 신청 상태 변경 (사용자가 실제 신청 결과를 입력할 때만) | 해당 없음 — 조회만으로 `subsidy_application`을 자동 생성하지 않음 |

## 11. Agent/Tool JSON 계약

> 아래 예시는 기존 설계에서 가져온 **검토용 초안**이며 구현 계약이 아닙니다. Agent/Tool 입출력 schema는 AI가 확정해 BE에 전달합니다. 외부 API 계약은 FE·BE 합의 후 갱신하며, 그 전에는 필드를 임의로 구현하지 않습니다.

### 11.1 `FactCandidate` (정보분석 Agent-as-Tool 출력 초안)

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
- `equipment_items`의 물리 DB 저장 방식은 BE schema 계약이 확정될 때 결정합니다. Agent가 임의의 테이블·컬럼을 전제하지 않습니다.

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

(`STALE_SUPPORT_DATA`는 이 enum에 속하지 않습니다. 오래된 지원 근거는 `GET /cases/{caseId}/subsidies`의 `matchStatus`에서 표현하는 현재 제안을 유지하되, 정확한 enum은 BE 계약에서 확정합니다.)

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

### 11.3 Supervisor·절차조회·Review 계약 — TBD

기존 `RuleDecision` 계약은 Rule 엔진 제거와 함께 폐기합니다. 대체 schema는 AI가 정의해 BE에 전달하며, 최소 의미 요구사항만 다음처럼 확정합니다.

- 절차조회 Tool: 절차 후보, 필요 조건, 불가능 사유
- Supervisor: Blocker 1개, Next Action 1개, 선택 이유, 사용자 확인 필요 여부, Evidence 참조
- Review Tool: `PASS` 또는 `REVISE`, 문제와 사유, 누락 Evidence, 재작업 권고 대상

정확한 필드명·타입·필수 여부는 아직 구현 계약이 아닙니다.

### 11.4 `SupportCheckResult` (지원금 Agent-as-Tool 출력 초안)

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
      "case_value": "UNKNOWN",
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

지원기관의 최종 심사 전에는 `ELIGIBLE`을 사용하지 않습니다. `case_value`의 미확인 표현과 `match_status`의 정확한 enum은 BE schema와 Agent 출력 계약에서 함께 확정합니다.

## 12. 에러/상태 처리 표

| 값 | HTTP 상태 | 의미 | FE 처리 |
|---|---|---|---|
| `UPDATED` | 200 | 정상 반영, 재계획 완료 | 변경사항 + 새 Blocker/Next Action 표시 |
| `NO_CHANGE` | 200 | 새로운 상태 변화 없음 | 현재 상태 유지 |
| `NEEDS_MORE_INFO` | 200 | 입력만으로 상태 확정 불가 | 추가 질문 표시 |
| `CONFLICT` | 200 | 기존 Case와 새 입력이 충돌 | 사용자 확인 UI, `/results/confirm` 유도 |
| `INVALID_TRANSITION` | 200 | 상태 기계상 허용되지 않는 전이 | 정정 입력 요청 |
| `REPLAN_FAILED` | 200 | 재계획 또는 필수 Review 완료 실패 | §13 TBD 참고 — 재시도/오류 안내 |
| `CASE_NOT_FOUND` | 404 | Case 없음 또는 접근 권한 없음 | 오류 화면 |

**규칙**: 검증 실패(`NEEDS_MORE_INFO`/`CONFLICT`/`INVALID_TRANSITION`/`REPLAN_FAILED`)를 포함해 요청 자체가 정상 처리된 경우는 항상 HTTP 200을 반환하고, FE는 `res.ok`가 아니라 **본문의 `result` 필드로 분기**해야 합니다. `CASE_NOT_FOUND`(권한 없음 포함)만 404입니다. `STALE_SUPPORT_DATA`는 이 표에 속하지 않습니다 — §11.2 설명대로 `GET /subsidies`의 `matchStatus` 필드 값(`STALE`)이며 `/results`의 `result`에는 나타나지 않습니다.

## 13. 명시적 TBD

- **동시성 제어**: 현행 물리 schema에는 `case.version`이 없습니다. `caseVersion`/`expectedVersion`을 추가할지 다른 방식을 쓸지, `/results/confirm`까지 어떻게 보호할지 BE가 확정해야 합니다.
- **enum 정합성**: 이 문서 예시의 `UNKNOWN`·`LEASED_PAID`·`DEMOLITION_REQUIRED` 등이 현행 `schema_table.md`와 다릅니다. 예시를 구현하기 전에 BE schema와 외부 API 값을 하나로 맞춰야 합니다.
- **`REPLAN_FAILED` 응답 형태**: Case 변경 후 재계획만 실패했을 때 변경 상태를 유지할지 전체 요청을 실패 처리할지 확정되지 않았습니다. **BE 트랜잭션 계약에서 정합니다**.
- **Conflict 임시 저장 방식**: `/results/confirm` 호출 시 충돌 후보를 서버에 `conflict_id`로 임시 저장할지, 클라이언트가 후보값을 다시 전송할지 미정 (`BE_AI_역할분담_및_연동스펙.md` §7 `[확인 필요]`).
- **JWT 전달·저장 방식**: §2 참고 — Access/Refresh를 body로 줄지 쿠키로 줄지, refresh 회전 방식.
- **`refresh_token`(카카오) 저장 방식**: 평문 저장 금지 원칙만 확정, 암호화 또는 별도 인증 테이블 등 구체 방식은 BE 확인 필요 (`/CLAUDE.md` 개인정보 섹션과 연계).
- **`procedureStepId` 포함 여부**: §5 참고, FE·BE 확정 필요.
- **필드 한글 라벨("업종", "원상복구 범위" 등) 제공 주체**: 지금까지 서버가 내려주는 값은 전부 raw enum 코드뿐이고 라벨을 함께 준 적이 없어(예외: `blocker`/`nextAction` 완성 문장, `blockerCode`/`nextActionCode` 코드), 이 패턴상 **FE가 key→label 매핑을 갖는 쪽을 AI 리드가 추천**합니다 — 다만 FE·BE 확정 필요 (`feature/current-case` PR 리뷰에서 발견).

---

## 출처

| 섹션 | 원본 |
|---|---|
| §1 엔드포인트 목록 | `todo.md` §5 / `BE_AI_역할분담_및_연동스펙.md` §7 / `history` 행은 사용자가 공유한 Notion 인터페이스 명세 §5-8 |
| §2 인증 흐름 | `docs/tech-stack.md` §2(BE기술스택.html 확정: 카카오 OAuth + PyJWT) + 사용자가 공유한 Notion 인터페이스 명세 §5-1 |
| §3 `POST /cases` | 사용자가 공유한 Notion 인터페이스 명세 §5-2 (요청/응답 예시 그대로 채택, camelCase 확인) |
| §4 `GET /cases/{caseId}` | 사용자가 공유한 Notion 인터페이스 명세 §5-3. `caseVersion`은 동시성 계약 확정 전 제안 |
| §5 `POST /results` | `BE_AI_역할분담_및_연동스펙.md` §7 (`POST /cases/{caseId}/results`), 판단 필드는 새 Agent 출력 schema 확정 후 재검토 |
| §6 `results/confirm` | 사용자가 공유한 Notion 인터페이스 명세 §5-5 |
| §7 `subsidies` 조회 | 사용자가 공유한 Notion 인터페이스 명세 §5-6, `matchStatus` 필드는 신규 추가(§11.4 `SupportCheckResult`와 연결) |
| §8 `subsidy-applications` PATCH | 사용자가 공유한 Notion 인터페이스 명세 §5-7 |
| §9 `history` 조회 | 사용자가 공유한 Notion 인터페이스 명세 §5-8 |
| §10 BE/AI 책임 분담 | `BE_AI_역할분담_및_연동스펙.md` §7 |
| §11.1 `FactCandidate` | `RE_BORN_AI리드_설계안.md` §5.1 (필드가 더 상세한 버전 채택), 금지 예시는 `BE_AI_역할분담_및_연동스펙.md` §6.1 |
| §11.2 `ValidationResult` | `RE_BORN_AI리드_설계안.md` §5.2 + `BE_AI_역할분담_및_연동스펙.md` §6.2 (enum 통합), `STALE_SUPPORT_DATA`/`STALE` 매핑은 검증 워크플로우에서 지적된 불일치 해소 |
| §11.3 Supervisor·절차조회·Review 계약 | 2026-09-13 Agent 구조 합의. 정확한 schema는 AI 확정 대기 |
| §11.4 `SupportCheckResult` | `RE_BORN_AI리드_설계안.md` §5.4에서 가져온 검토용 초안. 정확한 schema는 AI 확정 대기 |
| §12 에러/상태 표 | `RE_BORN_AI리드_설계안.md` §9.5, HTTP 상태 열은 검증 워크플로우 지적사항 반영 신규 추가 |
| §13 TBD | `RE_BORN_AI리드_설계안.md` §9.5, §12 / `BE_AI_역할분담_및_연동스펙.md` §7, §12 / `todo.md` §5 — 인증 방식은 §2에서 해소되어 이 목록에서 제거 |
