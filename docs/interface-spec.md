# RE:BORN 외부 HTTP 인터페이스 제안

> 상태: **`[PROPOSED_HTTP][NOT_IMPLEMENTED]` — FE/BE/AI 공동 승인 전 예시**
>
> FE/BE API 후보를 정리한 문서입니다. **현재 FastAPI route나 승인된 OpenAPI로 해석하지 마세요.**
> DRI 제안: FE/BE가 외부 계약을 공동 승인하고 BE가 승인된 OpenAPI를 관리합니다. 현재 승인 대기 상태입니다.
> Agent·Tool 책임과 실행 순서는 `docs/architecture.md`를 따릅니다. 승인되지 않은 논리 DB 후보는 `docs/schema/schema_table.md`를 참고하되, 외부 API와 물리 DB의 정확한 매핑은 FE·BE·AI 공동 승인 전까지 미정입니다.
>
> **주의:** 아래 JSON의 `caseVersion`·`expectedVersion`과 enum은 기존 제안입니다. 현재 branch에는 대응하는 BE route·ORM model·migration 근거가 없어 물리 schema와의 일치 여부를 확인할 수 없습니다. 동시성 제어 방식과 enum 계약이 공동 승인되기 전에는 구현 기준으로 사용하지 않습니다.
>
> 상태 구분: Agent 내부 `agent-io/2.0` schema와 strict runtime 모델만 `[CURRENT_AI]`로 구현돼 있습니다. 이 문서의 endpoint, HTTP DTO, status code, enum과 `docs/schema/schema_table.md`의 DDL·migration은 모두 `[PROPOSED_SHARED][NOT_IMPLEMENTED]`입니다. 현재 승인 기록이 있는 `[AGREED_SHARED]` HTTP 계약은 0개입니다. 규범적인 Agent 내부 필드는 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md), BE 구현 경계와 승인 기준은 [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)를 따릅니다.

상태 표기는 다음 기준으로 읽습니다.

| 표기 | 의미 | 구현 기준으로 사용 |
|---|---|---:|
| `[CURRENT_AI]` | 현재 Agent 코드·테스트에 있는 내부 실행 계약 | Agent 내부에서만 O |
| `[TYPE_ONLY]` | Python type은 있으나 현재 성공 경로가 없음 | X |
| `[PROPOSED_HTTP]`·`[PROPOSED_SHARED]` | FE/BE/AI 공동 승인 전 외부/shared 후보 | X |
| `[NOT_APPROVED]`·`[NOT_IMPLEMENTED]` | 승인 기록 또는 실행 코드가 없음 | X |
| `[DECIDED_ARCHITECTURE]` | 큰 기술 방향만 결정. payload·route·저장 구현은 별도 | 세부 구현 기준 X |
| `[CURRENT_SECURITY_POLICY]` | 저장소의 보안 원칙만 현재 적용 | 저장 기능 완료로 해석 X |
| `[REGISTRY_BLOCKED]`·`[PRIVACY_TBD]` | 선행 registry 또는 개인정보 정책 결정 전 구현 금지 | X |
| `[DEPRECATED]`·`[DEPRECATED_PROPOSAL]`·`[DO_NOT_IMPLEMENT]` | 폐기된 과거 예시 | X |
| `[DEFERRED]`·`[TARGET_UNIMPLEMENTED]`·`[TBD]` | 후속 범위이거나 미결정 | X |

## 1. `[PROPOSED_HTTP][NOT_IMPLEMENTED]` 엔드포인트 후보

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

현재 제안은 **별도의 `/replan` endpoint를 두지 않고** 결과 입력 뒤 같은 요청(`/results`)에서 재계획하는 방식입니다. 공동 승인 전 결정이며 현재 route도 없습니다.

## 2. `[DECIDED_ARCHITECTURE][NOT_IMPLEMENTED]` 인증 방식 — 세부 계약 TBD

카카오 OAuth로 사용자를 식별하고 이후 요청은 서버가 발급한 Access/Refresh JWT(PyJWT)로 인증한다는 **방식 선택만 결정**됐습니다. 아래 callback, token 전달·회전·저장, 401/403/404 동작은 구현·공동 계약 전 예시입니다.

```text
[PROPOSED_FLOW — 현재 BE 서버 구현 아님]
GET /auth/kakao/login
 → 카카오 로그인 페이지로 redirect

GET /auth/kakao/callback?code=...
 → 카카오 토큰 교환(httpx) → 카카오 사용자정보 조회
 → members.oauth_id로 기존 회원 조회
    ├─ 기존 회원 → members.refresh_token(카카오 발급분) 갱신
    └─ 신규 회원 → members 생성(oauth_id, refresh_token 저장)
 → 목표 BE가 Access/Refresh JWT 발급(PyJWT, memberId를 payload에 포함하는 안)
 → FE로 Access/Refresh JWT 전달
```

`[PROPOSED_HTTP]` 이후 `/cases/*` 요청에 `Authorization: Bearer {accessToken}`을 요구하고, BE가 token의 member와 Case 소유권을 확인한 뒤 응답하는 방식을 제안합니다. 정확한 claim과 401/403/404 정책은 아직 공동 승인 전입니다.

**명시적 TBD** (BE 확인 필요, 지어내지 않음): Access/Refresh JWT를 FE에 전달하는 방식(JSON body vs `httpOnly` 쿠키), Refresh 토큰 회전·저장(DB에 별도 저장할지 stateless로 둘지), 만료 시간, 카카오 `refresh_token`(members 테이블)과 우리 JWT refresh 토큰은 서로 다른 토큰이라는 점을 FE가 헷갈리지 않도록 할 문서화.

## 3. `[PROPOSED_HTTP][NOT_IMPLEMENTED]` `POST /cases` 예시

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

`[PROPOSED_SHARED][REGISTRY_BLOCKED]` **`stepProgress` 초기화 대상은 승인될 versioned canonical 절차 registry와 적용 조건으로 계산하는 안입니다.** 절차조회 Tool은 인터넷에서 공식 절차 내용을 조회할 뿐 DB step ID나 적용 단계 집합을 만들지 않습니다. 공동 승인 시 BE 초기화 transaction이 적용 단계마다 progress row를 하나씩 만들고 완료 후 대상 수와 row 수를 대조합니다. 제안 `UNIQUE (case_id, closure_procedure_step_id)`는 중복을 막아 최대 1개만 보장하고, 초기화·검증이 누락 row를 막습니다. registry/적용 조건·migration이 없으므로 현재는 구현할 수 없습니다.

## 4. `[PROPOSED_HTTP][NOT_IMPLEMENTED]` `GET /cases/{caseId}` 예시

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
    "blocker": "철거 관련 지원조건이 아직 확인되지 않았습니다.",
    "nextAction": "관련 지원항목의 조건과 필요한 증빙을 확인하세요.",
    "requiresHuman": false,
    "evidenceRefs": []
  }
}
```

이 **제안 예시**에서 `RESTORATION_CHECK=COMPLETED`이므로 `latestDecision`은 이미 끝난 원상복구 확인을 다시 blocker로 제시하지 않습니다. `historyId=15`의 입력으로 새로 드러난 철거 단계의 지원조건 확인을 blocker/next action으로 반환합니다. FE가 Blocker/Next Action을 직접 계산하지 않고, 공동 승인 시 BE projection이 같은 Case/version의 최신 판단을 반환하는 안입니다. `caseVersion`/`expectedVersion`과 `CASES.version`의 연결, 실제 migration·원자적 compare-and-set 방식은 아직 모두 `[PROPOSED_SHARED][NOT_IMPLEMENTED]`입니다.

## 5. `[PROPOSED_HTTP][NOT_IMPLEMENTED]` `POST /cases/{caseId}/results` 예시

### 처리 흐름

`[CURRENT_AI]` Agent 내부 first pass는 `ProcedureLookupTool → Info Agent → Support Agent → Supervisor → Review Tool` 순서입니다. `[PROPOSED_SHARED][NOT_IMPLEMENTED]` 생산에서는 BE Coordinator가 입력 Guardrail과 인증된 CaseSnapshot 조회 후 Graph를 호출하고, Review를 통과한 초안도 Output/State Transition Guardrail과 version CAS 뒤 저장하는 경계를 제안합니다. trigger별 선택 호출 최적화는 `[TARGET_UNIMPLEMENTED]`입니다.

### Request

```json
{
  "rawInput": "임대인이 철거해야 한다고 했어요.",
  "expectedVersion": 6,
  "clientEventId": "event-client-001"
}
```

현재 제안에서는 `procedureStepId`를 **제외**합니다. 포함 여부와 서버의 적용 대상 계산 방식은 BE·FE·AI 공동 확정 전입니다.

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

JSON API 필드는 `camelCase`를 따릅니다 (`/CLAUDE.md` 용어 규칙). `blockerCode`/`nextActionCode`는 FE가 아이콘·배지를 분기할 때 쓰는 후보이고, `requiresHuman`은 Supervisor 판단을 외부에 표현할 후보입니다. 이 HTTP 필드들의 포함 여부는 Agent 내부 schema 구현과 별개로 공동 승인해야 합니다.

## 6. `[DEPRECATED_PROPOSAL][DO_NOT_IMPLEMENT]` 폐기된 Conflict payload 설명

client가 임의 `field/value` 배열을 다시 보내는 과거 shape는 폐기됐으며, 복사 가능한 JSON 예시도 이 명세에서 제거합니다. 이 방식이나 같은 의미의 별도 필드를 다시 도입하면 안 됩니다.

`[PROPOSED_SHARED][NOT_IMPLEMENTED]` production 방향은 서버가 발급·복원하는 opaque conflict reference, 원 digest, Case version, 사용자 확인 의도를 결합하고 서버가 원 후보를 복원하는 것입니다. client가 변경할 field/value를 다시 정하지 않습니다. exact request/response DTO, pending conflict 저장 위치, TTL·소비·CAS·재계획/Review/저장 순서는 공동 승인 전이므로 이 문서에는 구현 가능한 payload를 제시하지 않습니다.

## 7. `[PROPOSED_HTTP][NOT_IMPLEMENTED]` `GET /cases/{caseId}/subsidies` 예시

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

## 8. `[PROPOSED_HTTP][NOT_IMPLEMENTED]` `PATCH /subsidy-applications/{applicationId}` 예시

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

## 9. `[DEFERRED][NOT_IMPLEMENTED]` `GET /cases/{caseId}/history` 예시

```json
{
  "history": [
    {
      "id": 15,
      "procedureStep": { "id": 1, "stepCode": "RESTORATION_CHECK", "stepName": "원상복구 범위 확인" },
      "blocker": "철거 관련 지원조건이 아직 확인되지 않았습니다.",
      "nextAction": "관련 지원항목의 조건과 필요한 증빙을 확인하세요.",
      "createdAt": "2026-09-07T20:30:00"
    }
  ]
}
```

`[PRIVACY_TBD]` 사용자 원문은 이 외부 조회 예시에서 의도적으로 제외했습니다. redacted excerpt를 제공할지조차 원문 보존·암호화·접근·보존기간·삭제 정책을 공동 승인한 뒤 결정합니다. MVP에서 별도 History 화면이 없다면 구현 우선순위는 낮습니다.

## 10. `[PROPOSED_SHARED][NOT_IMPLEMENTED]` endpoint 책임 분담

| Endpoint | BE | AI/Agent |
|---|---|---|
| `POST /cases` | 인증·소유권, Case 생성, 진행상태 초기화, History 저장, API 응답 | 현재 AgentGraph의 고정 dependency 실행. 목표에서는 Supervisor가 호출 계획을 제안하고 Graph가 집행 |
| `GET /cases/{caseId}` | Case/진행상태/최신 History 조회, 응답 생성 | 호출하지 않는 것이 기본 — 단순 조회에 LLM 불필요 |
| `POST /results/confirm` | opaque conflict reference로 원 후보·digest·Case/version·소유권을 복원하고 사용자 확인 의도를 검증하는 안 | 승인될 confirmation trigger로 Graph 재계획·Review 수행. exact DTO와 저장 경계는 공동 확정 |
| `GET /cases/{caseId}/subsidies` | Case에 연결된 지원항목·신청 상태 조회 | 목표에서는 stale/missing 재계획을 Coordinator가 Graph에 요청. Supervisor 직접 호출은 현재 구현 아님 |
| `PATCH /subsidy-applications/{applicationId}` | 신청 상태 변경 (사용자가 실제 신청 결과를 입력할 때만) | 해당 없음 — 조회만으로 `subsidy_application`을 자동 생성하지 않음 |

## 11. Agent/Tool JSON 상태 구분

> 아래 §11.1·§11.2·§11.4 예시는 기존 설계에서 가져온 **구형 검토용 초안**이며 구현 계약이 아닙니다. Agent/Tool 내부 입출력은 AI가 이미 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md)와 strict runtime 모델로 정의했습니다. BE는 provider/local 내부 DTO를 복사하지 말고 `SharedCaseSnapshotDTO`·`AgentRunOutcome`·Guardrail·persistence shared 경계만 공동 확정해야 합니다. 외부 HTTP DTO는 FE·BE·AI 합의 후 갱신하며 그 전에는 아래 예시 필드를 임의로 구현하지 않습니다.

### 11.1 `[DEPRECATED][DO_NOT_IMPLEMENT]` 구형 `FactCandidate` 예시

아래 JSON과 규칙은 과거 설계 의도 설명용이며 현재 schema 검증 기준이 아닙니다.

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

### 11.2 `[DEPRECATED][DO_NOT_IMPLEMENT]` 구형 `ValidationResult`

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

### 11.3 `[CURRENT_AI]` 현재 내부 실행 계약 / `[PROPOSED_SHARED]` 외부 매핑 TBD

기존 `RuleDecision` 계약은 Rule 엔진 제거와 함께 폐기합니다. 정확한 현재 계약은 `agent-tool-io-schema.md` §4~§14 중 **`[CURRENT_AI]`로 표시된 부분**과 `backend/app/agent/schemas.py`이며, 핵심 타입은 다음과 같습니다. 같은 절 안의 `[TYPE_ONLY]`·`[PROPOSED_SHARED]` 모델은 현재 실행 계약에 포함하지 않습니다.

- 절차조회 Tool: `ProcedureLookupInput` → 공식 원문·Evidence·provider 시도 내역을 포함한 `ProcedureLookupResult`
- Info Agent: 사용자 입력과 raw lookup 결과를 분석하고 caller가 제공한 `KnownProcedureStep`에만 `ProcedureFinding`을 결합
- Support Agent: caller가 주입한 immutable `ReviewedSupportCatalog`를 비교해 `SupportAnalysisResult`를 생성. `[CURRENT_AI]` BizInfo discovery adapter는 별도 구현돼 있지만 이 reviewed catalog 또는 Graph에 자동 연결되지 않음
- Supervisor: `[CURRENT_AI]` 실행 가능한 `ACTION | NEEDS_MORE_INFO` tagged decision, typed target, `MutationSet`, `GroundedClaim`; `[TYPE_ONLY]` `CASE_COMPLETE` class는 있으나 authoritative procedure coverage가 없어 Supervisor와 Review가 항상 거부
- Review Tool: immutable `ReviewSubject`와 digest를 검증하고 `PASS | REVISE`, 문제·누락 Evidence·재작업 권고 대상을 반환

이 내부 schema는 BE HTTP endpoint를 뜻하지 않습니다. 현재 성공/실패 runtime outcome은 정확히 `REVIEWED_PLAN | CONFLICT | SAFE_FAILURE` 세 가지이고 `CASE_COMPLETE` 성공 경로는 없습니다. 목표 계약의 `NO_CHANGE`, 외부 `UPDATED | NEEDS_MORE_INFO | ...` 변환, persistence DTO와 HTTP status/viewState는 아직 `[PROPOSED_SHARED][NOT_IMPLEMENTED]`입니다.

### 11.4 `[DEPRECATED][DO_NOT_IMPLEMENT]` 구형 `SupportCheckResult` 예시

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

## 12. `[PROPOSED_HTTP][NOT_APPROVED][NOT_IMPLEMENTED]` 에러/상태 처리안

| 값 | HTTP 상태 | 의미 | FE 처리 |
|---|---|---|---|
| `UPDATED` | 200 | 정상 반영, 재계획 완료 | 변경사항 + 새 Blocker/Next Action 표시 |
| `NO_CHANGE` | 200 | 새로운 상태 변화 없음 | 현재 상태 유지 |
| `NEEDS_MORE_INFO` | 200 | 입력만으로 상태 확정 불가 | 추가 질문 표시 |
| `CONFLICT` | 200 | 기존 Case와 새 입력이 충돌 | 사용자 확인 UI, `/results/confirm` 유도 |
| `INVALID_TRANSITION` | 200 | 상태 기계상 허용되지 않는 전이 | 정정 입력 요청 |
| `REPLAN_FAILED` | 200 | 재계획 또는 필수 Review 완료 실패 | §13 TBD 참고 — 재시도/오류 안내 |
| `CASE_NOT_FOUND` | 404 | Case 없음 또는 접근 권한 없음 | 오류 화면 |

**제안 규칙이며 아직 승인되지 않았습니다.** 검증 실패를 HTTP 200 + body discriminator로 표현할지 4xx와 나눌지 BE·FE·AI가 확정해야 합니다. 위 표를 현재 구현 또는 확정된 status code 정책으로 사용하지 않습니다.

## 13. `[TBD]` 공동 결정 대기

- **동시성 제어 구현**: 논리 schema는 `CASES.version`을 후보로 제안합니다. 공동 승인 시 BE가 migration, `expectedVersion` 불일치 응답, `/results/confirm`까지 포함한 원자적 compare-and-set을 구현합니다.
- **enum 정합성**: 이 문서 예시의 `UNKNOWN`·`LEASED_PAID`·`DEMOLITION_REQUIRED` 등이 `schema_table.md`의 논리 후보와도 다릅니다. 예시를 구현하기 전에 canonical enum과 외부 API 값을 공동 승인해야 합니다.
- **`REPLAN_FAILED` 응답 형태**: Case 변경 후 재계획만 실패했을 때 변경 상태를 유지할지 전체 요청을 실패 처리할지 확정되지 않았습니다. **BE 트랜잭션 계약에서 정합니다**.
- **Conflict reference 수명주기**: client의 field/value 재전송 방식은 폐기했습니다. pending conflict를 BE가 저장할지 production `ConflictRefFactory`를 Graph에 주입할지, opaque ref의 TTL·단일 소비·digest/version 결합을 공동 결정합니다.
- **JWT 전달·저장 방식**: §2 참고 — Access/Refresh를 body로 줄지 쿠키로 줄지, refresh 회전 방식.
- **`refresh_token`(카카오) 저장 방식**: `[CURRENT_SECURITY_POLICY]` 평문 저장 금지. `[TBD]` 암호화 또는 별도 인증 테이블 등 구체 방식은 공동 결정이 필요합니다 (`/CLAUDE.md` 개인정보 섹션과 연계).
- **`procedureStepId` 포함 여부**: §5 참고, FE·BE 확정 필요.
- **필드 한글 라벨("업종", "원상복구 범위" 등) 제공 주체**: 기존 문서 예시는 raw enum 코드와 완성 문장을 섞어 사용하지만, 이를 현재 BE 서버 응답으로 검증한 것은 아닙니다. **FE가 key→label 매핑을 갖는 안을 AI 리드가 제안**하며 FE·BE 공동 승인이 필요합니다 (`feature/current-case` PR 리뷰에서 발견).

---

## 출처

| 섹션 | 원본 |
|---|---|
| §1 엔드포인트 목록 | `todo.md` §5 / `BE_AI_역할분담_및_연동스펙.md` §7 / `history` 행은 사용자가 공유한 Notion 인터페이스 명세 §5-8 |
| §2 인증 흐름 | `docs/tech-stack.md` §2의 architecture decision(카카오 OAuth + PyJWT) + 사용자가 공유한 Notion 인터페이스 명세 §5-1. 현재 BE 구현 근거는 아님 |
| §3 `POST /cases` | 사용자가 공유한 Notion 인터페이스 명세 §5-2의 요청/응답을 가져온 **미승인 과거 예시**. camelCase convention만 별도 확인 필요 |
| §4 `GET /cases/{caseId}` | 사용자가 공유한 Notion 인터페이스 명세 §5-3. `caseVersion`은 동시성 계약 확정 전 제안 |
| §5 `POST /results` | `BE_AI_역할분담_및_연동스펙.md` §7 (`POST /cases/{caseId}/results`). Agent 내부 schema는 현재 구현됐지만 외부 판단 필드는 공동 승인 전 |
| §6 `results/confirm` | 사용자가 공유한 Notion 인터페이스 명세 §5-5의 client-supplied field/value 안은 폐기. 현재 문서는 opaque reference 방향만 제안하고 exact DTO는 미정 |
| §7 `subsidies` 조회 | 사용자가 공유한 Notion 인터페이스 명세 §5-6. `matchStatus`는 과거 §11.4와 연결해 검토한 제안일 뿐, deprecated `SupportCheckResult` shape를 재사용하지 않음 |
| §8 `subsidy-applications` PATCH | 사용자가 공유한 Notion 인터페이스 명세 §5-7 |
| §9 `history` 조회 | 사용자가 공유한 Notion 인터페이스 명세 §5-8 |
| §10 BE/AI 책임 분담 | `BE_AI_역할분담_및_연동스펙.md` §7 |
| §11.1 `FactCandidate` | 구형 예시 출처는 `RE_BORN_AI리드_설계안.md` §5.1. 현재 구현 계약은 `agent-tool-io-schema.md` §8과 `backend/app/agent/schemas.py` |
| §11.2 `ValidationResult` | 구형 외부 결과 제안은 `RE_BORN_AI리드_설계안.md` §5.2 + `BE_AI_역할분담_및_연동스펙.md` §6.2. 현재 Agent outcome과 외부 mapping 차이는 `agent-tool-io-schema.md` §13·§15 |
| §11.3 Supervisor·절차조회·Review 계약 | `agent-tool-io-schema.md` §4~§14 중 `[CURRENT_AI]` 표시 부분과 `backend/app/agent/schemas.py`. `[TYPE_ONLY]`·`[PROPOSED_SHARED]`를 제외한 현재 실행 schema만 구현됐고 외부 HTTP/shared mapping은 합의 대기 |
| §11.4 `SupportCheckResult` | `RE_BORN_AI리드_설계안.md` §5.4에서 가져온 구형 검토용 초안. 현재 구현 계약은 `agent-tool-io-schema.md` §9이며 외부 HTTP/shared mapping은 합의 대기 |
| §12 에러/상태 표 | `RE_BORN_AI리드_설계안.md` §9.5, HTTP 상태 열은 검증 워크플로우 지적사항 반영 신규 추가 |
| §13 TBD | `RE_BORN_AI리드_설계안.md` §9.5, §12 / `BE_AI_역할분담_및_연동스펙.md` §7, §12 / `todo.md` §5 — 인증 방식은 §2에서 해소되어 이 목록에서 제거 |
