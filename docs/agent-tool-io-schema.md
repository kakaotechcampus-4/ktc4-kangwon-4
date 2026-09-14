# RE:BORN Agent/Tool 입출력 schema 제안

> 상태: **v0.3 — AI standalone 실행 구현 완료 / BE 계약 합의 전**
> 기준일: 2026-09-15
> 기준 구조: `docs/architecture.md`의 Supervisor Global Loop, 정보분석/지원금 Local Loop, 절차조회 Tool, 필수 Review Tool

이 문서는 Agent 런타임과 BE 사이, Supervisor와 하위 Agent/Tool 사이의 데이터 계약을 먼저 합의하기 위한 문서입니다. AI 소유 범위의 standalone Pydantic 모델과 실행 Graph는 구현되어 있으나, BE adapter·인증/소유권 확인·DB migration·저장 API는 아직 구현되지 않았습니다. 현재 구현 범위와 목표 BE 계약의 차이는 §18에 정리합니다.

역할과 호출 방향은 `docs/architecture.md`가 기준입니다. 합의 전까지 `docs/interface-spec.md` §11의 기존 예시와 이 문서 모두 구현 확정본이 아닙니다.

## 1. 먼저 합의할 결론

| 항목 | v0.3 제안 |
|---|---|
| 실행 주체 | 비-LLM `PlanningCoordinator`가 인증, Guardrail, Agent Graph 호출, 저장, HTTP 변환을 조정 |
| Supervisor 권한 | 필요한 하위 Agent/Tool 선택, 결과 충분성 판단, 정상 `ACTION`이면 Blocker 1개와 Next Action 1개 초안 결정 |
| 하위 구성요소 권한 | 읽기·분석 결과만 반환. 서로 호출하거나 DB를 쓰거나 최종 우선순위를 결정하지 않음 |
| Review | 정상 초안과 LLM이 만든 사용자 확인 질문은 전부 필수 Review |
| 저장 | 어떤 Agent/Tool에도 쓰기 함수를 Tool로 등록하지 않음. BE `shared/functions`만 수행 |
| 직렬화 | Agent 내부 `snake_case`, 외부 HTTP API `camelCase`, DB 컬럼 `snake_case` |
| 응답 방식 | v1은 non-streaming 완결 응답. SSE/WebSocket schema는 만들지 않음 |
| 미확인 | Agent 내부는 `status=UNKNOWN`, `value=null`로 명시. `NOT_REQUIRED`와 구분 |
| 오류 | 기술 실행 실패와 업무 판단 결과를 서로 다른 discriminator로 표현 |
| Review 증명 | 결정뿐 아니라 snapshot, 모든 변경 후보, 사용한 하위 결과, Evidence 전체를 하나의 digest로 묶음 |

## 2. 실행 및 저장 경계

```text
FastAPI / PlanningCoordinator (코드)
  1. Input Guardrail + 인증/소유권 확인
  2. CaseSnapshot 생성
  3. Agent Graph 실행
       Supervisor
         ├─ 정보분석 Agent-as-Tool
         ├─ 지원금 Agent-as-Tool
         └─ 절차조회 Tool
       SupervisorDraft → Review Tool
  4. Review PASS 결과와 ReviewSubject digest 검증
  5. Output Guardrail
  6. State Transition Guardrail — 변경 후보 전체를 승인하거나 전체 거부
  7. BE shared/functions로만 저장
  8. 외부 HTTP 응답으로 변환
```

Supervisor나 Agent Graph가 DB 저장 Tool을 호출하지 않습니다. Graph는 `AgentRunOutcome`을 `PlanningCoordinator`에 반환하고, Coordinator가 코드 Guardrail과 transaction을 소유합니다.

### 목표 BE 호출 계약 (adapter 미구현)

현재 standalone 공개 진입점은 envelope 없이 `AgentGraph.run(SupervisorRunInput, trace_id=None) -> AgentRunOutcome`이며, 하위 구성요소도 payload/result 또는 안전한 예외를 직접 주고받습니다. 아래 표의 `ComponentRequest`/`ComponentResult`와 `PlanningCoordinator`는 BE 통합 시 구현할 목표 경계이지 현재 호출 형태가 아닙니다.

| 호출자 | 수신자 | 입력 payload | 출력 payload |
|---|---|---|---|
| PlanningCoordinator | Supervisor Graph | `ComponentRequest[SupervisorRunInput]` | `AgentRunOutcome` |
| Supervisor | 정보분석 Agent | `ComponentRequest[InfoAnalysisInput]` | `ComponentResult[InfoAnalysisResult]` |
| Supervisor | 지원금 Agent | `ComponentRequest[SupportAnalysisInput]` | `ComponentResult[SupportAnalysisResult]` |
| Supervisor | 절차조회 Tool | `ComponentRequest[ProcedureLookupInput]` | `ComponentResult[ProcedureLookupResult]` |
| Supervisor | Review Tool | `ComponentRequest[ReviewSubject]` | `ComponentResult[ReviewResult]` |
| PlanningCoordinator | BE 저장 함수 | `PersistReviewedPlanCommand` | `PersistResult` |

지원금 Agent 내부의 Wiki/Chroma/S3 adapter는 지원금 Agent 전용 read-only 구현입니다. 이 문서에서는 BE 공용 계약을 만들지 않고, 모든 조회 결과가 공통 `EvidenceRecord`로 정규화되어야 한다는 경계만 정합니다.

## 3. 공통 표기와 생성 주체

### 필수/nullable

- 표의 `필수=O`는 key가 반드시 존재한다는 뜻입니다.
- `T | null`은 key는 존재하지만 값이 명시적으로 `null`일 수 있다는 뜻입니다.
- 목록은 값이 없을 때 `[]`이며 `null`이 아닙니다.
- Pydantic v2 구현 시 “optional type”과 “default 생략 가능”을 같은 의미로 쓰지 않습니다.
- 모든 schema는 extra field를 거부합니다.

### 공통 값 타입

`StrictScalar`는 `strict string | strict integer | strict boolean | date | null`이고, `NonNullStrictScalar`는 여기서 `null`을 제외한 타입입니다. `boolean`을 `0/1`로, 숫자를 문자열로 자동 변환하지 않습니다. 필드별 허용 타입과 enum은 §6의 `CaseFieldKey` 표를 구현한 BE canonical field registry로 다시 검증합니다.

날짜는 `YYYY-MM-DD`, 시각은 timezone을 포함한 RFC 3339 문자열입니다. 내부 저장 시각 기준(UTC 권장)과 외부 표시 timezone은 BE가 확정해야 합니다.

### ID와 runtime 생성값

| 이름 | 타입 | 생성/검증 주체 | LLM 생성 허용 |
|---|---|---|---:|
| `case_id` | positive integer | DB/BE | X |
| `case_version` | positive integer | DB/BE | X |
| `snapshot_id` | UUID | PlanningCoordinator | X |
| `run_id` | UUID | PlanningCoordinator | X |
| `call_id` | UUID | Agent runtime | X |
| `input_event_id` | opaque string | BE | X |
| `candidate_id` | UUID | 구조화 출력 검증 후 runtime | X |
| `draft_id` | UUID | Supervisor output 검증 후 runtime | X |
| `review_subject_id` | UUID | runtime | X |
| `evidence_id` | opaque string | BE 또는 신뢰된 read-only resolver | X |
| `conflict_ref` | opaque string | BE. 저장 ID 또는 서명된 token | X |
| `procedure_step_id` | positive integer | DB/BE master | X |
| `support_program_id` | positive integer | DB/BE catalog | X |
| `wiki_uuid` | UUID string | DB/BE catalog와 Wiki 매핑 | X |
| `history_id` | positive integer | DB/BE | X |
| 모든 `*_at` | date/datetime | BE/runtime/resolver | X |
| 모든 digest | `sha256:<hex>` | runtime | X |

LLM은 의미 필드만 구조화해서 반환합니다. ID, 시각, digest, 출처 최신성은 runtime이나 신뢰된 resolver가 검증 후 주입합니다.

## 4. 공통 실행 envelope

이 절의 `ComponentRequest[T]`와 `ComponentResult[T]`는 목표 BE adapter 계약입니다. standalone 런타임에는 아직 이 envelope adapter가 없으며, 런타임이 생성한 `InvocationMeta`는 Review provenance와 내부 실행 경계에서 사용합니다.

### `InvocationMeta`

이 값은 runtime 전용이며 모델 prompt에 그대로 노출하지 않습니다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `schema_version` | literal `agent-io/1.0` | O | 계약 버전 |
| `run_id` | UUID | O | Global Loop 한 번의 ID |
| `call_id` | UUID | O | 구성요소 호출 한 번의 ID |
| `parent_call_id` | UUID \| null | O | 상위 호출 ID |
| `case_id` | positive integer | O | 인가가 끝난 Case ID |
| `component` | `SUPERVISOR` \| `INFO_AGENT` \| `SUPPORT_AGENT` \| `PROCEDURE_TOOL` \| `REVIEW_TOOL` | O | 실행 구성요소 |
| `attempt` | positive integer | O | 같은 목적의 호출 시도 번호 |
| `requested_at` | datetime | O | 호출 시각 |
| `trace_id` | opaque string \| null | O | 관측 시스템 연결 ID |

### `ComponentRequest[T]`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `meta` | `InvocationMeta` | O | runtime 호출 문맥 |
| `input` | `T` | O | 아래 구성요소별 입력 payload |

runtime은 모델에게 필요한 최소 필드만 투영하며 `trace_id`, 내부 인증·인가 정보, digest는 모델 입력에서 제외합니다.

### `ComponentResult[T]`

Pydantic 구현 시 한 모델의 nullable 조합이 아니라 `execution_status`로 구분하는 tagged union을 사용합니다.

`ComponentSuccess[T]`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `execution_status` | literal `SUCCESS` | O | discriminator |
| `meta` | `InvocationMeta` | O | 요청과 같은 run/call/case |
| `output` | `T` | O | 구성요소별 결과 |
| `warnings` | `ComponentWarning[]` | O | 비차단 경고 |

`ComponentFailure`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `execution_status` | literal `ERROR` | O | discriminator |
| `meta` | `InvocationMeta` | O | 요청과 같은 run/call/case |
| `error` | `ComponentError` | O | 기술 실패 |

업무상 결과 부족은 각 output의 `completion_status`로 표현합니다. 실행 envelope에는 `PARTIAL`을 두지 않습니다.

`ComponentWarning`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `code` | upper snake case string | O | 패턴 `[A-Z][A-Z0-9_]*` |
| `message` | string | O | 내부 운영 요약, chain-of-thought 금지 |
| `target_path` | JSON Pointer \| null | O | 해당 output 기준 경로 |

`ComponentError`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `code` | `INVALID_INPUT` \| `SCHEMA_VALIDATION_FAILED` \| `SNAPSHOT_UNAVAILABLE` \| `SOURCE_UNAVAILABLE` \| `TIMEOUT` \| `RATE_LIMITED` \| `UPSTREAM_ERROR` \| `LOOP_LIMIT_REACHED` \| `INTERNAL_ERROR` | O | 기술 실패 코드 |
| `message_code` | upper snake case string | O | 사용자 노출 문구가 아닌 내부 고정 코드 |
| `retryable` | boolean | O | 동일 조건으로 재시도 가능한지 |
| `failed_dependency` | string \| null | O | 실패한 외부 저장소/API |
| `retry_after_ms` | non-negative integer \| null | O | 알려진 경우에만 |

인증·소유권·version conflict는 Agent 호출 전후의 BE 코드 결과이므로 `ComponentError`에 넣지 않습니다.

## 5. 개인정보 입력과 Evidence

### `RedactedInput`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `input_event_id` | opaque string | O | 원본 입력 식별자 |
| `source_type` | `USER_INPUT` \| `EXPERT_CONFIRMATION` | O | `EXPERT_CONFIRMATION`은 인증된 BE 흐름만 발급 |
| `redacted_text` | string | O | Input Guardrail을 거친 모델 입력 |
| `redactions` | `Redaction[]` | O | 원문을 포함하지 않는 마스킹 정보 |
| `submitted_at` | datetime | O | 서버 수신 시각 |

`Redaction`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `type` | `ADDRESS` \| `NATIONAL_ID` \| `ACCOUNT` \| `TOKEN` \| `OTHER` | O | 마스킹 종류 |
| `placeholder` | string | O | redacted text 안 대체 문자열 |
| `start_offset` | non-negative integer | O | redacted text 기준 inclusive |
| `end_offset` | positive integer | O | redacted text 기준 exclusive |

원래 값은 포함하지 않습니다.

정보분석 모델은 정확한 `source_text`만 반환하고, runtime이 `redacted_text`에서 위치를 찾아 아래 `VerifiedTextSpan`을 만듭니다.

`VerifiedTextSpan`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `input_event_id` | opaque string | O | 입력 ID |
| `text` | string | O | `redacted_text`에 실제 존재하는 최소 구간 |
| `start_offset` | non-negative integer | O | Unicode code point 기준 inclusive |
| `end_offset` | positive integer | O | Unicode code point 기준 exclusive |

### `EvidenceRecord`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `evidence_id` | opaque string | O | 신뢰된 resolver가 발급한 ID |
| `source_type` | `USER_INPUT` \| `EXPERT_CONFIRMATION` \| `PROCEDURE_MASTER` \| `REVIEWED_WIKI` \| `OFFICIAL_DOCUMENT` \| `OFFICIAL_API` \| `CALCULATION_RESULT` \| `SYSTEM_RECORD` | O | 출처 종류 |
| `source_ref` | opaque string | O | credential 없는 원본 참조 |
| `source_version` | string \| null | O | 문서, master, 계산 규칙 버전 |
| `locator` | string | O | text span, page, section, record key |
| `excerpt` | string | O | 판단에 필요한 최소 구간. 원문 전체 금지 |
| `parent_evidence_refs` | opaque string[] | O | Wiki→공식 원문 등 lineage |
| `published_at` | datetime \| null | O | 출처 공개 시각 |
| `retrieved_at` | datetime | O | resolver 확인 시각 |
| `freshness_status` | `CURRENT` \| `STALE` \| `UNKNOWN` | O | 최신성 |
| `content_hash` | `sha256:<hex>` \| null | O | 원문 변경 감지 |

`REVIEWED_WIKI`가 고위험 주장을 뒷받침하려면 `parent_evidence_refs`로 `OFFICIAL_DOCUMENT` 또는 `OFFICIAL_API`를 연결해야 합니다. `CALCULATION_RESULT`는 공식 규칙 Evidence, 계산 규칙 버전, 입력 사실 Evidence를 부모로 연결합니다.

### `GroundedClaim`

Review가 자유 문장 속 위험한 단정을 놓치지 않도록 사용자에게 노출될 고위험 주장을 목록화합니다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `claim_id` | UUID | O | runtime 생성 |
| `claim_type` | `SUPPORT_PROGRAM` \| `AMOUNT` \| `DATE_OR_DEADLINE` \| `ELIGIBILITY` \| `LEGAL` \| `TAX` \| `PROCEDURE` | O | 위험 주장 종류 |
| `target_path` | JSON Pointer | O | `ReviewSubject` 기준 문장 위치 |
| `text` | string | O | 실제 검토할 주장 |
| `assertion_level` | `INFORMATION` \| `NEEDS_CONFIRMATION` | O | 최종 자격 확정 값은 없음 |
| `evidence_refs` | opaque string[] (min 1) | O | 이 주장에 직접 연결된 근거 |

금액·기한·법률·세무·지원조건은 `GroundedClaim` 없이 사용자 노출 문장에 넣지 않습니다. 명시적인 지원 자격·대상 표현은 같은 path/text의 `ELIGIBILITY` claim이 별도로 있어야 하며 `SUPPORT_PROGRAM` claim으로 대신할 수 없습니다. `ELIGIBILITY` 주장은 출처 최신성과 무관하게 항상 `NEEDS_CONFIRMATION`이어야 하고, “지원 대상입니다”처럼 사용자 문장 자체가 확정형이면 claim metadata와 관계없이 거부합니다. 그 밖의 주장도 `STALE`/`UNKNOWN` 출처로는 `INFORMATION`을 만들지 않고 `NEEDS_CONFIRMATION`만 허용합니다.

runtime은 `target_path`가 `ReviewSubject.supervisor_draft` 안의 사용자 노출 string 하나로 해석되고 그 실제 값이 `text`와 byte-for-byte 같은지 검증합니다. 존재하지 않는 경로, 객체/배열 경로, 다른 안전 문장을 대신 가리키는 claim은 거부합니다.

### 개인정보와 trace

- `redacted_text`, span text, Evidence excerpt, 이유·질문 문구는 기본 `no_trace` 대상입니다.
- Langfuse에는 run/call ID, component, latency, token, status, digest만 기본 기록합니다.
- 모델에 전달한 Evidence ID와 시각은 감사 이력으로 남기되 원문은 기록하지 않습니다.
- Output Guardrail은 모든 자유 문자열의 개인정보 유출을 검사하고 탐지 시 전체 거부합니다. Review 뒤 문자열을 마스킹·재작성하지 않습니다.

## 6. 공통 도메인 schema

### `CaseFieldKey`와 `CaseFact`

v1 정보분석 화이트리스트 제안입니다. `case_status`와 절차 진행상태는 LLM이 직접 바꾸는 사실 필드가 아닙니다.

| `field_path` | `value_type` | 비고 |
|---|---|---|
| `business_type` | `STRING` | 값 사전은 BE canonical registry 사용 |
| `franchise_status` | `BOOLEAN` | |
| `employee_count` | `INTEGER` | |
| `lease_status` | `ENUM` | 현 API/DB enum 불일치 해결 필요 |
| `entity_type` | `ENUM` | 지원 비교에 필요, 현 CASE 테이블에는 없음 |
| `building_use_type` | `ENUM` | 지원 비교에 필요, 현 CASE 테이블에는 없음 |
| `previous_support_history` | `ENUM` | 지원 비교에 필요, 현 CASE 테이블에는 없음 |
| `restoration_status` | `ENUM` | |
| `restoration_scope` | `ENUM` | 현 API/DB enum 불일치 해결 필요 |
| `restoration_scope_detail` | `STRING` | nullable |
| `demolition_required` | `ENUM` | 현 API/DB `UNKNOWN` 처리 불일치 해결 필요 |
| `planned_closure_date` | `DATE` | 사용자가 제시한 날짜만 허용 |

`CaseFact`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `field_path` | `CaseFieldKey` | O | snapshot 안에서 unique |
| `value_type` | `STRING` \| `INTEGER` \| `BOOLEAN` \| `DATE` \| `ENUM` | O | registry와 일치해야 함 |
| `value` | `StrictScalar` | O | `UNKNOWN`이면 `null` |
| `status` | `CONFIRMED` \| `UNKNOWN` | O | unresolved conflict는 여기에 저장하지 않음 |
| `evidence_refs` | opaque string[] | O | `CONFIRMED`이면 min 1 |
| `updated_at` | datetime \| null | O | 미확인 초기값은 `null` 가능 |

`CONFIRMED`는 non-null value, `UNKNOWN`은 null value여야 합니다. nullable 필드를 사용자가 명시적으로 비우는 동작은 `FactChangeCandidate.operation=CLEAR`로 표현하며 “필요 없음”으로 해석하지 않습니다.

### 안정 참조

`ProcedureStepRef`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `procedure_step_id` | positive integer | O | DB PK |
| `step_code` | upper snake case string | O | 안정 코드. 두 값이 같은 master row인지 runtime 검증 |

`SupportProgramRef`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `support_program_id` | positive integer | O | canonical DB ID |
| `wiki_uuid` | UUID string | O | Wiki exact lookup ID. DB ID와 같은 catalog row인지 resolver 검증 |

표시명은 식별자로 사용하지 않습니다. 기존 `support_item_id` 명칭은 위 canonical ID로 통일할지 BE 확인이 필요합니다.

### 최종 판단 구조

`BlockerDraft`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `blocker_code` | upper snake case string | O | versioned code catalog 값 |
| `title` | string | O | 한 줄 설명 |
| `description` | string | O | 쉬운 설명 |
| `evidence_refs` | opaque string[] (min 1) | O | Blocker 근거 |

`NextActionDraft`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `action_code` | upper snake case string | O | versioned code catalog 값 |
| `sequence` | positive integer | O | Case 안의 표시 순서 |
| `title` | string | O | 현실에서 할 일 하나 |
| `reason` | string | O | 지금 먼저 해야 하는 이유 |
| `questions_to_ask` | string[] | O | 임대인·기관 등에 물을 구체 질문 |
| `target_procedure` | `ProcedureStepRef` \| null | O | 관련 절차가 있으면 객체 전체를 포함 |
| `evidence_refs` | opaque string[] (min 1) | O | 행동과 선후관계의 근거 |

`DecisionDraft`는 `decision_type`으로 구분하는 tagged union입니다.

공통 필드:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `draft_id` | UUID | O | 구조화 출력 검증 후 runtime 생성 |
| `draft_version` | positive integer | O | 같은 run 안 초안 번호 |
| `selection_summary` | string | O | 근거를 추적할 수 있는 짧은 선택 이유 |
| `requires_human` | boolean | O | 사람/기관 확인 필요 여부 |
| `evidence_refs` | opaque string[] (min 1) | O | 판단 전체 근거 |
| `based_on_call_ids` | UUID[] (min 1) | O | 사용한 하위 정상 호출 |
| `created_at` | datetime | O | runtime 생성 시각 |

variant별 필드:

| variant | `decision_type` | `blocker` | `next_action` | `questions_for_user` |
|---|---|---|---|---|
| `ActionDecisionDraft` | literal `ACTION` | `BlockerDraft` | `NextActionDraft` | exact `[]` |
| `NeedsMoreInfoDecisionDraft` | literal `NEEDS_MORE_INFO` | `BlockerDraft` | exact `null` | string[] (min 1) |
| `CaseCompleteDecisionDraft` | literal `CASE_COMPLETE` | exact `null` | exact `null` | exact `[]` |

`selection_summary`는 근거를 추적할 수 있는 짧은 결정 이유이며 숨겨진 chain-of-thought가 아닙니다. `requires_human=true`는 시스템 근거만으로 해당 사실·자격·절차 완료를 확정할 수 없어 사용자, 임대인, 전문가 또는 공식기관 확인이 필요하다는 뜻입니다.

Blocker 1개 + Next Action 1개 불변식은 실행 가능한 정상 계획인 `ACTION`에 적용합니다. `NEEDS_MORE_INFO`는 계획을 확정할 정보가 없는 확인 분기이고, `CASE_COMPLETE`는 더 수행할 Action이 없는 종료 분기이므로 명시적 예외입니다.

`NEEDS_MORE_INFO`는 항상 `requires_human=true`, `CASE_COMPLETE`는 항상 `requires_human=false`입니다. `ACTION`은 실제 확인 주체에 따라 true/false가 가능합니다.

Supervisor는 `CASE_COMPLETE`를 제안할 수 있지만 외부 전달·저장은 State Transition Guardrail이 완료 조건을 확인한 뒤에만 가능합니다.

### 변경 후보

`FactChangeCandidate`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `candidate_id` | UUID | O | runtime 생성 |
| `operation` | `SET` \| `CLEAR` | O | 값 설정/명시적 비우기 |
| `source_fact_candidate_id` | UUID | O | 원 정보분석 사실 후보 |
| `source_type` | `INFO_ANALYSIS` \| `CONFIRMED_CONFLICT` | O | provenance discriminator |
| `field_path` | `CaseFieldKey` | O | 변경 대상 |
| `value_type` | `CaseFact.value_type` | O | registry와 일치 |
| `before_status` | `CONFIRMED` \| `UNKNOWN` | O | snapshot 상태 |
| `before_value` | `StrictScalar` | O | snapshot 값 |
| `proposed_status` | `CONFIRMED` \| `UNKNOWN` | O | 제안 상태 |
| `proposed_value` | `StrictScalar` | O | `CLEAR`이면 `null` |
| `candidate_status` | literal `READY_FOR_REVIEW` | O | 저장 검토 가능한 후보만 MutationSet 진입 |
| `reason_summary` | string | O | 짧은 근거 요약 |
| `source_evidence_refs` | opaque string[] (min 1) | O | 입력 근거 |
| `source_call_id` | UUID \| null | O | 일반 정보분석 후보면 원 호출 |
| `confirmed_conflict_ref` | opaque string \| null | O | 충돌 확인 후보면 원 conflict ref |

`INFO_ANALYSIS`는 `source_call_id`만, `CONFIRMED_CONFLICT`는 `confirmed_conflict_ref`만 non-null이어야 합니다. 후자는 원 conflict Evidence와 confirmation Evidence를 `source_evidence_refs`에 모두 포함합니다. `SET`은 `proposed_status=CONFIRMED`와 non-null value, `CLEAR`는 `proposed_status=UNKNOWN`과 null value여야 합니다. `CLEAR`는 `USER_INPUT` 또는 인증된 `EXPERT_CONFIRMATION` Evidence가 직접 연결된 명시적 철회일 때만 허용합니다.

`ProcedureProgressChangeCandidate`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `candidate_id` | UUID | O | runtime 생성 |
| `procedure_step` | `ProcedureStepRef` | O | 대상 절차 |
| `before_status` | `NOT_STARTED` \| `IN_PROGRESS` \| `COMPLETED` \| null | O | row가 없으면 `null` |
| `proposed_status` | `NOT_STARTED` \| `IN_PROGRESS` \| `COMPLETED` | O | 변경 후보 |
| `reason_summary` | string | O | 변경 이유 |
| `execution_evidence_refs` | opaque string[] (min 1) | O | `COMPLETED`에는 현실 실행/공식 결과 근거 필수 |
| `execution_input_event_id` | opaque string \| null | O | 사용자/전문가 입력이 근거면 해당 event ID |
| `source_observation_id` | UUID \| null | O | 정보분석이 추출한 절차 관측. 공식/system event면 null 가능 |
| `source_observation_call_id` | UUID \| null | O | 관측을 만든 정보분석 호출. 위 필드와 함께 null/non-null |
| `procedure_evaluation_call_id` | UUID | O | 근거 절차조회 호출 |

`COMPLETED`는 `USER_INPUT`, `EXPERT_CONFIRMATION`, `OFFICIAL_API`, `OFFICIAL_DOCUMENT`, `SYSTEM_RECORD` 중 현실 실행을 증명하는 Evidence가 있어야 합니다. 사용자/전문가 입력 Evidence이면 `execution_input_event_id`가 그 Evidence의 source event와 같아야 합니다.

`SupportMatchUpdateCandidate`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `candidate_id` | UUID | O | runtime 생성 |
| `before_match` | `SupportMatchSummary` \| null | O | snapshot의 기존 비교 결과. 없으면 null |
| `support_check` | `SupportCheck` | O | Review할 비교 결과 전체 |
| `source_call_id` | UUID | O | 지원금 Agent 호출 |

`CaseStatusChangeCandidate`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `candidate_id` | UUID | O | runtime 생성 |
| `before_status` | `IN_PROGRESS` | O | v1 종료 전 상태 |
| `proposed_status` | literal `COMPLETED` | O | 완료 제안 |
| `reason_summary` | string | O | 완료 판단 이유 |
| `evidence_refs` | opaque string[] (min 1) | O | 완료 조건 근거 |

`MutationSet`은 다음 네 key를 항상 갖습니다.

| 필드 | 타입 | 필수 |
|---|---|---:|
| `fact_changes` | `FactChangeCandidate[]` | O |
| `procedure_progress_changes` | `ProcedureProgressChangeCandidate[]` | O |
| `support_match_updates` | `SupportMatchUpdateCandidate[]` | O |
| `case_status_change` | `CaseStatusChangeCandidate` \| null | O |

`SupportApplicationChangeCandidate`는 v1 `MutationSet`에 넣지 않습니다. 실제 신청상태는 명시적 신청상태 변경 API가 소유합니다. 자연어 `RESULT_SUBMITTED`로도 이를 바꿀 UX를 채택한다면 `application_id`, before/proposed status, 입력 event와 Evidence, 허용 전이를 가진 별도 candidate를 계약 버전 상향 후 추가해야 합니다.

한 `MutationSet` 안의 모든 `candidate_id`는 전역 unique입니다. 같은 `field_path`, `procedure_step_id`, `support_program_id`에는 각각 최대 1개의 변경만 허용하며 저장 순서로 충돌을 해소하지 않습니다.

runtime 조립 시 다음 deep-equality provenance를 강제합니다.

- `INFO_ANALYSIS` fact 변경의 operation/path/type/proposed value/Evidence는 참조한 `FactCandidate`와 같고 그 후보의 `requires_confirmation=false`여야 합니다.
- `CONFIRMED_CONFLICT` fact 변경은 trigger의 같은 candidate/ref/digest를 가리켜야 합니다. `ACCEPT_PROPOSED`일 때만 mutation을 만들고 operation/status/value를 원 충돌의 proposed 값과 같게 합니다. `KEEP_COMMITTED`이면 fact mutation을 만들지 않습니다.
- 절차 변경의 step/status/Evidence는 참조한 `ProcedureProgressObservation`과 같고 그 관측의 `requires_confirmation=false`여야 합니다. `procedure_evaluation_call_id`의 결과에도 같은 step이 존재해야 합니다.
- 지원 비교 변경의 `support_check`는 `source_call_id` 결과의 한 항목과 deep-equal이고, `before_match`는 같은 program의 snapshot 값 또는 null과 같아야 합니다.

runtime이 하위 결과와 다른 값으로 mutation을 재작성하는 것은 금지합니다.

`DecisionDraft.decision_type=CASE_COMPLETE`이면 `case_status_change.proposed_status=COMPLETED`가 반드시 존재하고, `ACTION` 또는 `NEEDS_MORE_INFO`이면 `case_status_change=null`이어야 합니다. 완료 mutation은 모든 필수 절차와 종료 조건이 충족됐는지 State Transition Guardrail이 다시 확인합니다.

절차 진행은 v1에서 `NOT_STARTED(또는 row 없음) → IN_PROGRESS → COMPLETED` 순방향을 기본으로 하며, 현실 실행 Evidence가 있으면 `NOT_STARTED → COMPLETED` 단축만 허용합니다. 동일 상태는 mutation을 만들지 않고, 역행·완료 취소는 별도의 인증된 정정 계약을 만들기 전까지 거부합니다.

### 충돌과 사용자 확인

`ConflictCandidate`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `conflict_ref` | opaque string | O | BE가 발급한 pending conflict 참조 |
| `conflict_digest` | `sha256:<hex>` | O | 아래 충돌 내용 전체의 runtime digest |
| `candidate_id` | UUID | O | runtime 생성 |
| `snapshot_id` | UUID | O | 충돌 검출 기준 |
| `case_version` | positive integer \| null | O | 동시성 버전 |
| `field_path` | `CaseFieldKey` | O | 충돌 필드 |
| `committed_status` | `CONFIRMED` | O | 기존 저장 상태 |
| `committed_value` | `NonNullStrictScalar` | O | 기존 값 |
| `proposed_operation` | `SET` \| `CLEAR` | O | 신규 후보 동작 |
| `proposed_status` | `CONFIRMED` \| `UNKNOWN` | O | 신규 후보 상태 |
| `proposed_value` | `StrictScalar` | O | SET이면 non-null, CLEAR이면 null |
| `source_evidence_refs` | opaque string[] (min 1) | O | 신규 입력 근거 |
| `source_call_id` | UUID | O | 정보분석 호출 |

`SET`은 `proposed_status=CONFIRMED`/non-null 값, `CLEAR`는 `proposed_status=UNKNOWN`/null 값이어야 합니다. `conflict_digest`는 자기 자신과 `conflict_ref`만 제외한 나머지 충돌 필드를 §12와 같은 canonical serializer로 묶고, `conflict_ref`는 이 digest와 Case 소유권에 결합되어야 합니다.

`ConfirmedConflictResolution`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `conflict_ref` | opaque string | O | 서버 발급 참조 |
| `expected_conflict_digest` | `sha256:<hex>` | O | 원 충돌 digest와 같아야 함 |
| `candidate_id` | UUID | O | 원 후보와 같아야 함 |
| `field_path` | `CaseFieldKey` | O | 원 충돌과 같아야 함 |
| `resolution` | `KEEP_COMMITTED` \| `ACCEPT_PROPOSED` | O | 임의의 제3 값 입력 금지 |
| `confirmation_input_event_id` | opaque string | O | 확인 입력 이력 |
| `confirmation_evidence_refs` | opaque string[] (min 1) | O | 인증된 확인 입력 근거 |
| `expected_snapshot_id` | UUID | O | 원 충돌 snapshot |
| `expected_case_version` | positive integer \| null | O | version 미채택 시 field-level compare-and-set 필수 |
| `confirmed_at` | datetime | O | BE 수신 시각 |

`CONFLICT_CONFIRMED`는 클라이언트가 임의로 붙이는 source type이 아닙니다. BE가 유효한 `conflict_ref`, 현재 값/version, 확인 event를 검증한 뒤에만 Supervisor 입력을 만듭니다.

정보분석 모델은 `conflict_ref`나 digest를 만들지 않습니다. 모델의 fact candidate를 구조화 검증한 뒤 PlanningCoordinator의 deterministic conflict resolver가 snapshot과 비교하고, 충돌이면 candidate를 이 타입으로 변환한 다음 서명 token 또는 pending row 방식으로 `conflict_ref`를 발급합니다.

## 7. `CaseSnapshot`

BE가 인증·소유권 확인 후 만드는 읽기 전용 snapshot입니다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `snapshot_id` | UUID | O | 실행 동안 immutable |
| `case_id` | positive integer | O | meta와 같아야 함 |
| `case_version` | positive integer \| null | O | 미채택 시 field-level CAS 필요 |
| `case_status` | `IN_PROGRESS` \| `COMPLETED` | O | Case 전체 상태 |
| `facts` | `CaseFact[]` | O | registry 대상 field를 unique하게 포함 |
| `procedure_progress` | `ProcedureProgress[]` | O | Case별 절차 현재 상태 |
| `support_applications` | `SupportApplicationSummary[]` | O | 실제 신청 상태 |
| `support_matches` | `SupportMatchSummary[]` | O | 최근 지원 비교 상태 |
| `latest_decision` | `LatestDecisionSummary` \| null | O | 마지막 Review 통과 판단 |
| `history_window` | `HistoryWindow` | O | bounded history |
| `evidence_records` | `EvidenceRecord[]` | O | snapshot의 참조 중 이번 실행에 필요한 최소 근거 |
| `captured_at` | datetime | O | BE 생성 시각 |

`ProcedureProgress`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `procedure_step` | `ProcedureStepRef` | O | 절차 master 참조 |
| `status` | `NOT_STARTED` \| `IN_PROGRESS` \| `COMPLETED` | O | 현재 진행 상태 |
| `evidence_refs` | opaque string[] | O | 완료 상태면 min 1 |
| `updated_at` | datetime | O | 마지막 변경 시각 |

`SupportApplicationSummary`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `application_id` | positive integer | O | 실제 신청 row |
| `support_program` | `SupportProgramRef` | O | 대상 사업 |
| `application_status` | `APPLIED` \| `SUPPLEMENT_REQUIRED` \| `RESUBMITTED` \| `APPROVED` \| `REJECTED` | O | 실제 신청 생명주기만 포함 |
| `applied_at` | datetime \| null | O | 신청 전이면 row 자체를 만들지 않는 방안 권장 |
| `updated_at` | datetime | O | 마지막 갱신 |

`SupportMatchSummary`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `support_program` | `SupportProgramRef` | O | 지원사업 참조 |
| `match_status` | `SupportMatchStatus` | O | §9의 비교 상태 |
| `source_version` | string \| null | O | 판단에 사용한 자료 버전 |
| `freshness_status` | `CURRENT` \| `STALE` \| `UNKNOWN` | O | 자료 최신성 |
| `checked_at` | datetime | O | 마지막 비교 시각 |
| `evidence_refs` | opaque string[] | O | 비교 근거 |

`LatestDecisionSummary`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `history_id` | positive integer | O | 저장 판단 이력 |
| `decision` | `DecisionDraft` | O | 저장된 Review 통과 판단 |
| `review_subject_digest` | `sha256:<hex>` | O | 원 Review 대상 digest |
| `created_at` | datetime | O | 저장 시각 |

`HistoryWindow`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `selection_policy` | literal `RECENT_PLUS_ACTIVE_DECISION` | O | 최근 이력 + 현재 판단 관련 이력 |
| `limit` | positive integer | O | 설정에서 주입 |
| `truncated` | boolean | O | 더 오래된 이력이 있는지 |
| `items` | `CaseHistorySummary[]` | O | 시간 오름차순 |

`CaseHistorySummary`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `history_id` | positive integer | O | 이력 ID |
| `event_type` | upper snake case string | O | versioned event code |
| `input_event_id` | opaque string \| null | O | 원인 입력이 있으면 연결 |
| `changed_paths` | JSON Pointer[] | O | 해당 이력에서 바뀐 경로 |
| `decision_history_id` | positive integer \| null | O | 판단 이력 연결 |
| `created_at` | datetime | O | 생성 시각 |

과거 raw input 전체는 snapshot에 반복 포함하지 않습니다.

Snapshot 안의 모든 `evidence_refs`는 같은 snapshot의 `evidence_records`에서 해석되어야 합니다. 이후 구성요소가 새로 만든 Evidence는 해당 `ComponentSuccess` output에 포함합니다.

`UNKNOWN` fact 자체는 Evidence가 없을 수 있습니다. 다만 “정보가 없다”는 사실을 Blocker나 질문의 근거로 사용할 가능성이 있으면 PlanningCoordinator가 snapshot 생성 시 해당 JSON Pointer와 captured time을 가리키는 `SYSTEM_RECORD` Evidence를 `snapshot.evidence_records`에 포함합니다.

## 8. 정보분석 Agent-as-Tool

`KnownProcedureStep`은 자연어 진행 발화를 안정 ID에 연결하기 위한 입력 전용 타입입니다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `procedure_step` | `ProcedureStepRef` | O | 안정 참조 |
| `step_name` | string | O | 현재 표시명 |
| `utterance_aliases` | string[] | O | BE master에서 관리하는 동의 표현 |

### 입력 — `InfoAnalysisInput`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `input` | `RedactedInput` | O | 현재 입력 한 건 |
| `case_snapshot` | `CaseSnapshot` | O | 기존 사실 비교용 |
| `allowed_field_paths` | `CaseFieldKey[]` | O | runtime 화이트리스트 |
| `known_procedure_steps` | `KnownProcedureStep[]` | O | 발화에서 진행 관측을 안정 절차에 연결 |
| `review_feedback` | `ReviewIssue[]` | O | 최초 호출은 `[]` |

### 출력 — `InfoAnalysisResult`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `completion_status` | `COMPLETE` \| `NEEDS_USER_INPUT` \| `PARTIAL` | O | 분석 충분성 |
| `fact_candidates` | `FactCandidate[]` | O | 충돌하지 않은 사실 후보 |
| `procedure_progress_observations` | `ProcedureProgressObservation[]` | O | 사용자가 명시한 현실 절차 진행 관측 |
| `conflicts` | `ConflictCandidate[]` | O | 기존 확정값과 충돌한 후보 |
| `missing_fields` | `MissingField[]` | O | 판단에 필요한 미확인 사실 |
| `uncertainties` | `Uncertainty[]` | O | 애매함/낮은 근거 |
| `question_candidates` | `QuestionCandidate[]` | O | Supervisor용 질문 후보 |
| `evidence_records` | `EvidenceRecord[]` | O | 검증된 입력 span Evidence |
| `parser_version` | string | O | prompt/schema 버전 |
| `based_on_snapshot_id` | UUID | O | 입력 snapshot과 같아야 함 |

`FactCandidate`는 `operation`으로 구분하는 `SetFactCandidate | ClearFactCandidate` tagged union입니다. 공통 필드는 다음과 같습니다.

현재 standalone 구현은 같은 조건부 불변식을 단일 `FactCandidate` 모델과 validator로 강제합니다. 위 tagged union은 BE shared DTO의 목표 형태이며, wire schema를 확정할 때 둘 중 한 표현으로 통일해야 합니다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `candidate_id` | UUID | O | runtime 생성 |
| `operation` | `SET` \| `CLEAR` | O | discriminator |
| `field_path` | `CaseFieldKey` | O | whitelist 값 |
| `value_type` | `CaseFact.value_type` | O | registry와 일치 |
| `value` | `StrictScalar` | O | `SET`이면 non-null, `CLEAR`이면 null |
| `source_span` | `VerifiedTextSpan` | O | runtime 검증 |
| `source_evidence_refs` | opaque string[] (min 1) | O | 같은 결과의 Evidence |
| `confidence_bps` | integer `0..10000` | O | 참고용 basis points, 승인 기준 금지 |
| `requires_confirmation` | boolean | O | 사람 확인 필요 여부 |
| `reason_summary` | string | O | 짧은 추출 근거, chain-of-thought 금지 |

`SetFactCandidate`는 `operation=SET`, `value=NonNullStrictScalar`이고, `ClearFactCandidate`는 `operation=CLEAR`, `value=null`입니다. 기존 `CONFIRMED` 값을 바꾸거나 지우는 후보는 runtime이 §6의 `ConflictCandidate`로 이동시키며 일반 fact candidate로 통과시키지 않습니다.

`ProcedureProgressObservation`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `observation_id` | UUID | O | 구조화 출력 검증 후 runtime 생성 |
| `procedure_step` | `ProcedureStepRef` | O | `known_procedure_steps[*].procedure_step` 중 하나 |
| `observed_status` | `IN_PROGRESS` \| `COMPLETED` | O | 발화에 명시된 현실 상태 |
| `source_span` | `VerifiedTextSpan` | O | runtime 검증 |
| `source_evidence_refs` | opaque string[] (min 1) | O | 같은 결과의 입력 Evidence |
| `requires_confirmation` | boolean | O | 상태 변경에 추가 확인이 필요한지 |
| `reason_summary` | string | O | 짧은 추출 이유 |

`MissingField`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `field_path` | `CaseFieldKey` | O |
| `reason_summary` | string | O |
| `blocks` | (`PROCEDURE_LOOKUP` \| `SUPPORT_ANALYSIS` \| `SUPERVISOR_DECISION`)[] (min 1) | O |
| `question_candidate_id` | UUID \| null | O |

`Uncertainty`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `code` | `AMBIGUOUS_INPUT` \| `LOW_CONFIDENCE` \| `CONTEXT_MISSING` \| `SOURCE_STALE` \| `SOURCE_UNAVAILABLE` | O |
| `target_path` | JSON Pointer | O |
| `reason_summary` | string | O |
| `evidence_refs` | opaque string[] | O |

`QuestionCandidate`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `question_id` | UUID | O | 구조화 출력 검증 후 runtime 생성 |
| `text` | string | O | 사용자에게 확인할 단일 질문 후보 |
| `resolves_field_paths` | `CaseFieldKey[]` (min 1) | O | 답변으로 해소하려는 사실 |
| `reason_summary` | string | O | 질문이 필요한 짧은 이유 |

사용자에게 실제로 보낼지는 Supervisor가 결정하고 Review가 검토합니다.

정보분석 Agent는 Case를 바꾸거나 Blocker/Next Action을 반환하지 않습니다. 문장에 없는 값, whitelist 밖 필드, 자격 확정, 추정 세금, 최적 폐업일도 반환하지 않습니다.

기존 초안의 `equipment_items`는 저장 모델이 없으므로 v1에서 제외합니다. 필요하면 별도 후보/저장 schema 합의 후 계약 버전을 올립니다.

## 9. 지원금 Agent-as-Tool

### 공통 입력 — `PlanningContext`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `case_snapshot` | `CaseSnapshot` | O | 실행 시작 시점의 immutable snapshot |
| `fact_overlays` | `FactChangeCandidate[]` | O | 아직 저장하지 않은 사실 변경 후보 |

`fact_overlays`에는 `candidate_status=READY_FOR_REVIEW`인 후보만 들어갈 수 있습니다. 구성요소는 overlay를 snapshot에 적용한 것처럼 평가하되 원본 snapshot을 바꾸지 않으며, 실제 사용한 candidate ID를 출력에 돌려줍니다.

### 입력 — `SupportAnalysisInput`

`lookup_goal` discriminator를 쓰는 tagged union입니다.

- `DiscoverSupportInput`: `lookup_goal=DISCOVER_RELEVANT`; 아래 공통 필드만 가지며 `support_programs` 필드는 없음
- `CheckSpecificSupportInput`: `lookup_goal=CHECK_SPECIFIC`; 공통 필드 + `support_programs: SupportProgramRef[]` (min 1)
- `RefreshSupportInput`: `lookup_goal=REFRESH_STALE`; 공통 필드 + `support_programs: SupportProgramRef[]` (min 1)

공통 필드:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `planning_context` | `PlanningContext` | O | snapshot과 임시 fact overlay |
| `related_steps` | `ProcedureStepRef[]` | O | 관련 절차 필터. 없으면 `[]` |
| `as_of` | date | O | 유효성 판단 기준일 |
| `review_feedback` | `ReviewIssue[]` | O | 최초 호출은 `[]` |

`planning_context`는 위 `PlanningContext`입니다.

### 출력 — `SupportAnalysisResult`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `completion_status` | `COMPLETE` \| `NO_CANDIDATE` \| `PARTIAL` | O | 검색 충분성 |
| `support_checks` | `SupportCheck[]` | O | 복수 후보 허용 |
| `no_candidate_reason_code` | upper snake code \| null | O | 0건이면 non-null, 그 외 null |
| `uncertainties` | `Uncertainty[]` | O | 출처 부족 등 |
| `search_summary` | `SupportSearchSummary` | O | 조회 경로 요약 |
| `evidence_records` | `EvidenceRecord[]` | O | 조회에 사용한 근거 |
| `based_on_snapshot_id` | UUID | O | 입력 snapshot과 같아야 함 |
| `based_on_candidate_ids` | UUID[] | O | 실제 overlay한 READY 후보의 부분집합 |

`SupportMatchStatus`:

`POSSIBLY_RELEVANT | NEEDS_CONFIRMATION | NOT_RELEVANT | STALE | UNVERIFIABLE`

`SupportCheck`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `support_program` | `SupportProgramRef` | O | 검수 catalog 항목 |
| `program_name` | string | O | catalog에서 가져온 표시명 |
| `related_steps` | `ProcedureStepRef[]` | O | 관련 절차 |
| `match_status` | `SupportMatchStatus` | O | `ELIGIBLE` 값 없음 |
| `criteria` | `SupportCriterionResult[]` | O | 조건별 비교 |
| `unknown_field_paths` | `CaseFieldKey[]` | O | 추가 확인할 Case 사실 |
| `required_documents` | `RequiredDocument[]` | O | 공식 출처에 있는 서류 |
| `application_channel` | `SourcedText` \| null | O | 공식 신청 채널 |
| `application_url` | `SourcedText` \| null | O | 공식 URL |
| `application_period` | `SourcedText` \| null | O | 공식 원문 표현, 추정 금지 |
| `source_version` | string \| null | O | 확인 불가 시 null |
| `freshness_status` | `CURRENT` \| `STALE` \| `UNKNOWN` | O | 원문 최신성 |
| `checked_at` | datetime | O | runtime/resolver 생성 |
| `reason_summary` | string | O | 비교 이유 요약 |
| `evidence_refs` | opaque string[] | O | positive match는 min 1 |

`SourcedText`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `text` | string | O |
| `evidence_refs` | opaque string[] (min 1) | O |

`SupportCriterionResult`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `criterion_code` | upper snake code | O |
| `case_value` | `StrictScalar` | O |
| `required_values` | `NonNullStrictScalar[]` (min 1) | O |
| `status` | `MET` \| `NOT_MET` \| `UNKNOWN` | O |
| `reason_summary` | string | O |
| `evidence_refs` | opaque string[] (min 1) | O |

`RequiredDocument`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `name` | string | O |
| `submission_stage` | string \| null | O |
| `evidence_refs` | opaque string[] (min 1) | O |

`SupportSearchSummary`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `wiki_lookup` | `HIT` \| `MISS` \| `NOT_REQUESTED` | O |
| `rag_used` | boolean | O |
| `official_source_checked` | boolean | O |
| `checked_at` | datetime | O |

조건부 불변식:

- `completion_status=NO_CANDIDATE` iff `support_checks=[]`이고 `no_candidate_reason_code`가 non-null입니다.
- `COMPLETE`이면 `support_checks`가 min 1이고 `no_candidate_reason_code=null`입니다.
- `PARTIAL`이면 `uncertainties`가 min 1이고 `no_candidate_reason_code=null`이며, 확인된 check가 없으면 `support_checks=[]`일 수 있습니다.
- criterion은 `case_value=null` iff `status=UNKNOWN`이고, non-null이면 status가 `MET | NOT_MET`입니다.
- `match_status=STALE` iff `freshness_status=STALE`입니다. `freshness_status=UNKNOWN`이면 `match_status=UNVERIFIABLE`입니다.

지원 안전 규칙:

- 공식 근거가 없거나 오래되면 `POSSIBLY_RELEVANT`로 올리지 않습니다.
- `NOT_RELEVANT`는 CURRENT 공식 근거가 있는 명시적 `NOT_MET` criterion이 최소 1개일 때만 허용합니다.
- 기관 심사 전에 `ELIGIBLE`, “지원 가능 확정”, “수령 확정”을 반환하지 않습니다.
- `match_status`는 조건 비교, `application_status`는 실제 신청 결과입니다.
- 조회만으로 신청 row를 생성·변경하지 않습니다.
- 금액 필드는 v1 `SupportCheck`에 두지 않습니다. 추후 추가 시 CURRENT 공식 Evidence를 가진 별도 `GroundedClaim`이 필수입니다.

## 10. 절차조회 Tool

### 입력 — `ProcedureLookupInput`

`lookup_scope` discriminator를 쓰는 tagged union입니다.

- `AllProcedureLookupInput`: `lookup_scope=ALL_STEPS`; 아래 공통 필드만 가지며 `step_codes` 필드는 없음
- `SpecificProcedureLookupInput`: `lookup_scope=SPECIFIC_STEPS`; 공통 필드 + `step_codes: upper snake case string[]` (min 1)

공통 필드:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `planning_context` | `PlanningContext` | O | snapshot과 임시 fact overlay |
| `as_of` | date | O | master/조건 평가 기준일 |

`planning_context`의 overlay 규칙은 `PlanningContext`와 같습니다.

### 출력 — `ProcedureLookupResult`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `completion_status` | `COMPLETE` \| `PARTIAL` | O | master 조회 충분성 |
| `procedure_data_version` | string | O | 사용한 master 버전 |
| `step_evaluations` | `ProcedureStepEvaluation[]` | O | 대상 절차 평가 |
| `evidence_records` | `EvidenceRecord[]` | O | master/공식 근거 |
| `based_on_snapshot_id` | UUID | O | 입력 snapshot과 같아야 함 |
| `based_on_candidate_ids` | UUID[] | O | 실제 overlay한 READY 후보 부분집합 |

`ProcedureStepEvaluation`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `procedure_step` | `ProcedureStepRef` | O | 대상 절차 |
| `step_name` | string | O | 표시명 |
| `is_active` | boolean | O | master 활성 여부 |
| `applicability` | `APPLICABLE` \| `NOT_APPLICABLE` \| `UNDETERMINED` | O | Case 적용 여부 |
| `readiness` | `READY` \| `BLOCKED` \| `UNDETERMINED` | O | 지금 실행 가능 여부 |
| `current_status` | `NOT_STARTED` \| `IN_PROGRESS` \| `COMPLETED` \| null | O | progress row가 없으면 null |
| `conditions` | `ProcedureConditionResult[]` | O | 조건 평가 |
| `prerequisites` | `ProcedurePrerequisiteResult[]` | O | 선행절차 평가 |
| `unavailable_reasons` | `ProcedureUnavailableReason[]` | O | 불가/보류 이유 |
| `requires_professional` | boolean | O | 전문가 확인 필요 여부 |
| `professional_type` | string \| null | O | false면 null |
| `decision_authority` | `USER` \| `LANDLORD` \| `OFFICIAL_AGENCY` \| `PROFESSIONAL` \| `UNKNOWN` | O | 확인 주체, 현 master 보완 필요 |
| `evidence_refs` | opaque string[] (min 1) | O | master/공식 근거 |

`requires_professional=false`이면 `professional_type=null`, true이면 non-empty string이어야 합니다.

`ProcedureConditionResult`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `condition_id` | positive integer | O |
| `field_path` | `CaseFieldKey` | O |
| `operator` | `EQ` \| `IN` \| `GT` \| `GTE` \| `LT` \| `LTE` | O |
| `expected_values` | `NonNullStrictScalar[]` (min 1) | O |
| `actual_value` | `StrictScalar` | O |
| `status` | `MET` \| `NOT_MET` \| `UNKNOWN` | O |
| `evidence_refs` | opaque string[] (min 1) | O |

`ProcedurePrerequisiteResult`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `procedure_step` | `ProcedureStepRef` | O |
| `dependency_type` | `REQUIRED` \| `RECOMMENDED` | O |
| `current_status` | `NOT_STARTED` \| `IN_PROGRESS` \| `COMPLETED` \| null | O |
| `satisfaction` | `SATISFIED` \| `NOT_SATISFIED` \| `UNKNOWN` | O |
| `reason_summary` | string | O |

`ProcedureUnavailableReason`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `code` | `STEP_INACTIVE` \| `CONDITION_NOT_MET` \| `CONDITION_UNKNOWN` \| `PREREQUISITE_INCOMPLETE` | O | 불가/보류 원인 |
| `message` | string | O | 사용자에게 이해 가능한 짧은 설명 |
| `evidence_refs` | opaque string[] (min 1) | O | 원인 근거 |

결정표:

| 조건 | `applicability` | `readiness` |
|---|---|---|
| `is_active=false` | `NOT_APPLICABLE` | `BLOCKED` |
| condition 중 `NOT_MET` 존재 | `NOT_APPLICABLE` | `BLOCKED` |
| `NOT_MET`은 없고 `UNKNOWN` 존재 | `UNDETERMINED` | `UNDETERMINED` |
| condition 모두 `MET`, REQUIRED prerequisite가 `NOT_SATISFIED` | `APPLICABLE` | `BLOCKED` |
| condition 모두 `MET`, REQUIRED prerequisite가 `UNKNOWN` | `APPLICABLE` | `UNDETERMINED` |
| condition 모두 `MET`, REQUIRED prerequisite 모두 충족 | `APPLICABLE` | `READY` |

`RECOMMENDED` prerequisite 미충족은 `readiness`를 막지 않고 reason/warning으로만 반환합니다.

절차조회 출력에는 `priority`, `rank`, `selected`, `blocker`, `next_action` 필드를 두지 않습니다.

## 11. Supervisor Agent

### 입력 — `SupervisorRunInput`

`RunTrigger`는 `trigger_type` discriminator를 쓰는 다음 네 variant의 tagged union입니다. 아래에 적지 않은 variant 전용 필드는 extra field로 거부합니다.

- `CaseCreatedTrigger`: `trigger_type=CASE_CREATED`, `input_event_id: opaque string`, `client_event_id: opaque string | null`, `input: RedactedInput`, `submitted_at: datetime`
- `ResultSubmittedTrigger`: `trigger_type=RESULT_SUBMITTED`; 나머지 필드는 `CaseCreatedTrigger`와 동일
- `ConflictConfirmedTrigger`: `trigger_type=CONFLICT_CONFIRMED`, `input_event_id: opaque string`, `client_event_id: opaque string | null`, `confirmation_input: RedactedInput`, `confirmation_evidence_records: EvidenceRecord[]` (min 1), `referenced_conflicts: ConflictCandidate[]` (min 1), `referenced_conflict_evidence_records: EvidenceRecord[]` (min 1), `confirmed_conflicts: ConfirmedConflictResolution[]` (min 1), `submitted_at: datetime`
- `SupportRefreshTrigger`: `trigger_type=SUPPORT_REFRESH`, `input_event_id: opaque string`, `client_event_id: opaque string | null`, `support_programs: SupportProgramRef[]` (min 1), `as_of: date`; 사용자 raw input 필드 없음

`SupervisorRunInput`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `trigger` | `RunTrigger` | O | 실행 원인 |
| `case_snapshot` | `CaseSnapshot` | O | 실행 기준 snapshot |

trigger의 `input_event_id`, snapshot의 case ID, 바깥 `InvocationMeta`의 run/case는 runtime이 교차 검증합니다. `ConflictConfirmedTrigger`는 BE가 `conflict_ref`로 복원한 원 충돌과 resolution을 1:1로 포함해야 합니다. 원 충돌과 확인의 모든 Evidence 참조는 각각 같은 trigger의 Evidence 목록에서 해석되고, `confirmation_input.input_event_id`와 trigger의 ID가 같아야 합니다. 재호출은 새 외부 trigger가 아니라 같은 `run_id` 안의 Graph 제어입니다.

### 내부 상태 — `AgentGraphState`

아래 표는 목표 상태 모델입니다. 현재 standalone의 실제 `TypedDict`는 `request`, `run_id`, `trace_id`, `phase`, source result, fact overlay, Review/rework 상태와 outcome/failure 필드를 사용하며, envelope 기반 `component_results`/`errors` 구조와 정확히 같지 않습니다. 현재 상태는 §18을 기준으로 봅니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `run_id` | UUID | 전체 실행 |
| `phase` | `PLANNING` \| `CALLING_COMPONENT` \| `DRAFTING` \| `REVIEWING` \| `REVISING` \| `COMPLETED` \| `SAFE_FAILED` | Agent Graph 내부 단계 |
| `trigger` | `RunTrigger` | 실행 원인 |
| `case_snapshot` | `CaseSnapshot` | immutable |
| `component_results` | (`ComponentSuccess[InfoAnalysisResult]` \| `ComponentSuccess[SupportAnalysisResult]` \| `ComponentSuccess[ProcedureLookupResult]`)[] | 같은 run/case/snapshot의 검증된 결과만 |
| `conflicts` | `ConflictCandidate[]` | 미해결 충돌 |
| `mutations` | `MutationSet` | 미저장 후보 |
| `current_draft` | `DecisionDraft` \| null | 현재 초안 |
| `review_result` | `ComponentResult[ReviewResult]` \| null | 현재 subject 검토 |
| `revision_count` | integer `0..2` | Review 반송 후 재작성 횟수 |
| `errors` | `ComponentError[]` | 기술 실패 |

### 출력 — `SupervisorDraft`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `decision` | `DecisionDraft` | O | Supervisor만 생성 가능 |
| `mutations` | `MutationSet` | O | runtime이 하위 결과와 연결해 조립 |
| `grounded_claims` | `GroundedClaim[]` | O | 고위험 사용자 노출 주장 |
| `source_call_ids` | UUID[] (min 1) | O | 사용한 하위 결과 |

runtime은 `source_call_ids`가 같은 run/case/snapshot의 `ComponentSuccess`인지 검증합니다. 이 집합은 `decision.based_on_call_ids`, 각 mutation의 non-null current-run source call, 그리고 decision·mutation·claim이 참조한 새 Evidence를 소유한 source result call의 합집합과 정확히 같아야 합니다. `CONFIRMED_CONFLICT` provenance는 digest로 보호된 trigger에서 닫히므로 이전 run의 call을 이 집합에 넣지 않습니다. 사용하지 않은 호출을 끼워 넣거나 사용한 호출을 생략할 수 없습니다. 절차와 관련된 `ACTION`이면 해당 `ProcedureStepEvaluation`이 반드시 있어야 하고, 지원사업 문구가 있으면 해당 `SupportCheck`가 반드시 있어야 합니다.

Supervisor는 전문 Evidence를 새로 만들거나 하위 결과를 고쳐 쓰지 않습니다. 결과가 부족하면 호출을 반복하고, 충분할 때만 `SupervisorDraft`를 만듭니다.

## 12. Review Tool

### 입력 — `ReviewSubject`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `schema_version` | literal `agent-io/1.0` | O | 계약 버전 |
| `review_subject_id` | UUID | O | runtime 생성 |
| `review_attempt` | integer `1..3` | O | 최초 1회 + 재작성 최대 2회 |
| `run_id` | UUID | O | 실행 ID |
| `case_id` | positive integer | O | Case ID |
| `trigger` | `RunTrigger` | O | 판단과 저장의 원인 event 전체 |
| `snapshot` | `CaseSnapshot` | O | 판단 기준 |
| `source_results` | `ReviewSourceResult[]` (min 1) | O | 초안에 실제 사용한 하위 정상 결과 |
| `supervisor_draft` | `SupervisorDraft` | O | 결정, 변경 후보, claim 목록 |
| `subject_digest` | `sha256:<hex>` | O | 아래 전체 검토 대상 digest |

`ReviewSourceResult`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `meta` | `InvocationMeta` | O | 원 `ComponentSuccess.meta` 전체 |
| `output_digest` | `sha256:<hex>` | O | runtime이 원 output 전체로 계산 |
| `output` | `InfoAnalysisResult` \| `SupportAnalysisResult` \| `ProcedureLookupResult` | O | component에 대응하는 정확한 타입 |

`meta.component`는 `INFO_AGENT | SUPPORT_AGENT | PROCEDURE_TOOL` 중 하나이며 output 타입과 반드시 일치해야 합니다. `ComponentFailure`나 사용하지 않은 결과는 넣지 않으며, `output_digest`는 `subject_digest`와 같은 canonical serializer 규칙으로 계산합니다.

`source_results[*].meta.call_id` 집합은 `supervisor_draft.source_call_ids` 집합과 정확히 같아야 합니다. 각 meta의 run/case와 output의 snapshot ID도 `ReviewSubject`와 같아야 합니다.

`subject_digest`는 자기 자신만 제외한 `ReviewSubject`의 모든 필드(`schema_version`, `review_subject_id`, `review_attempt`, run/case, trigger 전체, snapshot 전체, source results 전체, supervisor draft 전체)를 묶습니다. 현재 Python 구현은 serialization hook을 우회해 선언된 model field를 직접 읽고 `subject_digest`만 제외한 뒤, enum/UUID/date를 문자열로 바꾸고 datetime을 UTC 고정 6자리 microseconds의 `Z` 형식으로 정규화합니다. 그 결과를 `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`로 직렬화한 UTF-8 bytes에 SHA-256을 적용합니다. 배열 순서는 유지하며 float/NaN을 허용하지 않습니다. LLM은 digest를 보거나 생성하지 않습니다. BE의 다른 언어 구현과 연결하기 전에는 동일 입력/출력의 cross-language 고정 test vector를 공동 확정해야 합니다.

Evidence ID가 중복되면 내용과 content hash가 완전히 같아야 합니다. 모든 Evidence 참조는 trigger, snapshot 또는 source results의 `evidence_records`에서 해석되어야 합니다.

### 출력 — `ReviewResult`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `reviewed_subject_id` | UUID | O | 입력 subject ID |
| `reviewed_subject_digest` | `sha256:<hex>` | O | 입력 digest와 일치 |
| `verdict` | `PASS` \| `REVISE` | O | 품질 검토 결과 |
| `issues` | `ReviewIssue[]` | O | 문제 목록 |
| `missing_evidence` | `MissingEvidence[]` | O | 누락 근거 |
| `recommended_rework_targets` | (`SUPERVISOR` \| `INFO_AGENT` \| `SUPPORT_AGENT` \| `PROCEDURE_TOOL`)[] | O | 권고일 뿐 명령 아님 |
| `resolution_reason` | string | O | 검토 결론 요약, chain-of-thought 금지 |

Review 모델은 verdict와 검토 내용만 생성합니다. wrapper가 요청에서 검증한 `reviewed_subject_id`와 `reviewed_subject_digest`를 결과에 주입하므로 모델이 ID/digest를 복사하거나 임의 생성하지 않습니다.

현재 runtime은 모델이 제안한 `recommended_rework_targets`를 최종 라우팅 근거로 신뢰하지 않습니다. 모든 `BLOCKING` issue의 검증된 `target_component`와 `missing_evidence → SUPERVISOR` 규칙으로 목록을 고정 순서 재계산합니다. `MissingEvidence.claim_path`는 non-null `/supervisor_draft/...` 경로만 허용합니다. `REVISE`는 `BLOCKING` issue 또는 `missing_evidence`가 있을 때만 유효하고, warning-only 결과는 `PASS`와 빈 rework target이어야 합니다.

`ReviewIssue`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `issue_code` | `CASE_MISMATCH` \| `UNSUPPORTED_CLAIM` \| `MISSING_EVIDENCE` \| `STALE_EVIDENCE` \| `OVERCONFIDENT_LANGUAGE` \| `INFEASIBLE_ACTION` \| `HUMAN_CONFIRMATION_OMITTED` \| `AMBIGUOUS_LANGUAGE` \| `PROCEDURE_CONFLICT` \| `CONTRACT_VIOLATION` | O | 문제 코드 |
| `category` | `FACTUALITY` \| `EVIDENCE` \| `PROCEDURE` \| `SAFETY` \| `ACTIONABILITY` \| `LANGUAGE` \| `CONTRACT` | O | 분류 |
| `severity` | `BLOCKING` \| `WARNING` | O | 차단 여부 |
| `target_component` | `SUPERVISOR` \| `INFO_AGENT` \| `SUPPORT_AGENT` \| `PROCEDURE_TOOL` | O | 수정 권고 대상 |
| `target_call_id` | UUID \| null | O | 하위 결과 대상일 때 |
| `target_path` | JSON Pointer | O | `ReviewSubject` root 기준 경로 |
| `reason_summary` | string | O | 문제 이유 |
| `evidence_refs` | opaque string[] | O | package 안 기존 Evidence만 |

`MissingEvidence`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `claim_path` | `/supervisor_draft/...` JSON Pointer | O |
| `required_source_types` | `EvidenceRecord.source_type[]` (min 1) | O |
| `reason_summary` | string | O |

Review 불변식:

- `PASS`이면 blocking issue와 `missing_evidence`가 없어야 하며 `recommended_rework_targets=[]`입니다.
- `REVISE`이면 blocking issue 또는 missing evidence가 최소 1개입니다.
- `UNSUPPORTED_CLAIM`, `MISSING_EVIDENCE`, `STALE_EVIDENCE`, `PROCEDURE_CONFLICT`, `CONTRACT_VIOLATION`은 항상 `BLOCKING`입니다.
- trigger, 초안, mutation, source result, Evidence, snapshot 중 하나라도 바뀌면 subject ID/digest를 새로 만들고 다시 Review합니다.
- Review는 수정본, 새 Evidence, 확정 재호출 명령을 반환하지 않습니다.
- timeout이나 malformed output은 `REVISE`가 아니라 `ComponentFailure`입니다.

### `ReviewProof`

Review 모델이 직접 만드는 값이 아니라 runtime이 성공한 Review 응답을 검증한 뒤 발급합니다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `review_call_id` | UUID | O | Review 호출 ID |
| `run_id` | UUID | O | subject와 같아야 함 |
| `case_id` | positive integer | O | subject와 같아야 함 |
| `snapshot_id` | UUID | O | subject snapshot |
| `case_version` | positive integer \| null | O | subject snapshot version |
| `review_subject_id` | UUID | O | 검토 대상 |
| `reviewed_subject_digest` | `sha256:<hex>` | O | runtime 재계산 값과 일치 |
| `verdict` | literal `PASS` | O | PASS만 proof 생성 |
| `reviewed_at` | datetime | O | runtime 시각 |

runtime은 Review의 `ComponentSuccess.meta`가 subject의 run/case 및 요청 call과 일치하고, 응답 subject ID/digest가 일치하며, `verdict=PASS` 불변식이 성립할 때만 proof를 발급합니다.

## 13. Agent Graph의 최종 출력

`AgentRunOutcome`은 `outcome_type`으로 구분하는 tagged union입니다.

### `ReviewedPlanOutcome`

| 필드 | 타입 | 필수 |
|---|---|---:|
| `outcome_type` | literal `REVIEWED_PLAN` | O |
| `review_subject` | `ReviewSubject` | O |
| `review_proof` | `ReviewProof` | O |

두 객체의 run/case/snapshot/subject/digest가 전부 같아야 합니다.

### `ConflictOutcome`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `outcome_type` | literal `CONFLICT` | O | runtime 생성 variant |
| `run_id` | UUID | O | 실행 ID |
| `case_id` | positive integer | O | Case ID |
| `trigger` | `RunTrigger` | O | 충돌을 만든 원인 event |
| `snapshot_id` | UUID | O | 충돌 기준 |
| `case_version` | positive integer \| null | O | 동시성 버전 |
| `conflicts` | `ConflictCandidate[]` (min 1) | O | 구조화 충돌 |
| `message_code` | literal `CONFIRM_CONFLICT` | O | BE 고정 문구 key |

LLM이 만든 자유 문장은 넣지 않습니다. 충돌 안내를 새로 생성해야 한다면 `NeedsMoreInfoDecisionDraft`로 만들어 Review를 거칩니다.

### `NoChangeOutcome`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `outcome_type` | literal `NO_CHANGE` | O | discriminator |
| `run_id` | UUID | O | 실행 ID |
| `case_id` | positive integer | O | Case ID |
| `trigger` | `RunTrigger` | O | 처리한 원인 event |
| `snapshot_id` | UUID | O | 현재 snapshot |
| `case_version` | positive integer \| null | O | 현재 version |
| `latest_decision_history_id` | positive integer | O | 기존 Review 통과 판단 |
| `latest_review_subject_digest` | `sha256:<hex>` | O | 기존 판단 Review 연결 |
| `reason_code` | `DUPLICATE_EVENT` \| `NO_NEW_FACT` \| `ALREADY_CURRENT` | O | 자유 문장 금지 |

기존 판단과 호환되는 같은 Case version에서 새 사용자 노출 문장을 만들지 않을 때만 Review 없이 사용합니다.

### `SafeFailureOutcome`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `outcome_type` | literal `SAFE_FAILURE` | O | runtime 생성 variant |
| `run_id` | UUID | O | 실행 ID |
| `case_id` | positive integer | O | Case ID |
| `trigger` | `RunTrigger` | O | 실패한 원인 event |
| `snapshot_id` | UUID | O | 실패 기준 snapshot |
| `case_version` | positive integer \| null | O | 현재 version |
| `failure_code` | `REVIEW_RETRY_EXHAUSTED` \| `COMPONENT_UNAVAILABLE` \| `STRUCTURED_OUTPUT_FAILED` | O | Graph 내부 실패 원인 |
| `message_code` | upper snake case string | O | BE allowlist 문구 key. 자유 문장 금지 |
| `recovery_action_code` | `RETRY` \| `RESUBMIT_INPUT` \| `CONTACT_SUPPORT` \| `NONE` | O | BE allowlist 복구 행동 |
| `requested_field_paths` | `CaseFieldKey[]` | O | 재입력이 필요할 때의 구조화 목록, 그 외 `[]` |
| `retryable` | boolean | O | 재시도 여부 |
| `failed_component` | `SUPERVISOR` \| `INFO_AGENT` \| `SUPPORT_AGENT` \| `PROCEDURE_TOOL` \| `REVIEW_TOOL` \| null | O | 실패 지점 |
| `trace_id` | opaque string \| null | O | 운영 추적 |

검토되지 않은 Blocker, Next Action, mutation, Evidence는 포함하지 않습니다.

## 14. State Guardrail과 BE 저장 DTO

Agent Graph는 §13의 결과를 반환하면 끝납니다. 이후 Output/State Transition Guardrail은 PlanningCoordinator 단계이며 `AgentGraphState.phase`가 아닙니다.

Output Guardrail과 State Transition Guardrail은 Review된 payload를 수정하지 않습니다. PASS하거나 아래 고정 schema로 전체 거부합니다. 문구·값을 바꿔야 하면 새 `ReviewSubject`를 만들어 다시 Review합니다.

### `GuardrailRejection`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `result` | literal `REJECTED` | O | discriminator |
| `stage` | `OUTPUT` \| `STATE_TRANSITION` | O | 거부 지점 |
| `run_id` | UUID | O | 실행 ID |
| `case_id` | positive integer | O | Case ID |
| `snapshot_id` | UUID | O | 검증 기준 |
| `case_version` | positive integer \| null | O | snapshot version |
| `review_subject_id` | UUID | O | 거부한 Review 대상 |
| `reviewed_subject_digest` | `sha256:<hex>` | O | 변경되지 않은 Review 대상 |
| `violation_codes` | upper snake case string[] (min 1) | O | 결정적 코드 검사 결과 |
| `concurrency_conflicts` | `ConcurrencyConflictDetail[]` | O | 동시성 충돌이 아니면 `[]` |
| `message_code` | upper snake case string | O | BE allowlist 문구 key |
| `retryable` | boolean | O | 새 snapshot 재시도 가능 여부 |
| `checked_at` | datetime | O | runtime 시각 |

`ConcurrencyConflictDetail`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `target_kind` | `CASE` \| `FACT` \| `PROCEDURE_PROGRESS` \| `SUPPORT_MATCH` | O | 충돌 대상 종류 |
| `target_ref` | opaque string | O | field path 또는 안정 ID |
| `expected_state_digest` | `sha256:<hex>` | O | Review한 before 상태 |
| `current_state_digest` | `sha256:<hex>` | O | 저장 직전 상태 |
| `current_case_version` | positive integer \| null | O | 현재 version |

두 state digest는 §12 serializer로 `{"target_kind": ..., "target_ref": ..., "state": ...}` projection을 hash합니다. row가 없으면 `state={"absent": true}`를 사용합니다. row가 있으면 target별 state는 다음 필드만 포함합니다.

- `CASE`: `case_status`
- `FACT`: `field_path`, `value_type`, `value`, `status`, `evidence_refs`
- `PROCEDURE_PROGRESS`: `procedure_step`, `status`, `evidence_refs`
- `SUPPORT_MATCH`: `SupportMatchSummary` 전체

expected는 ReviewSubject snapshot/before 값, current는 같은 target을 저장 직전에 다시 읽은 값으로 계산합니다.

`GuardrailRejection`이면 저장 함수를 호출하지 않습니다. Input Guardrail 실패는 Agent 실행 전의 기존 HTTP 오류 계약을 사용하므로 이 DTO 범위가 아닙니다.

### `OutputGuardrailProof`

| 필드 | 타입 | 필수 |
|---|---|---:|
| `run_id` | UUID | O |
| `case_id` | positive integer | O |
| `review_subject_id` | UUID | O |
| `reviewed_subject_digest` | `sha256:<hex>` | O |
| `result` | literal `PASS` | O |
| `checked_at` | datetime | O |

### 전부 승인 또는 전부 재계획

State Transition Guardrail은 Review된 `MutationSet`에서 일부만 골라 저장하지 않습니다.

- 모든 mutation이 현재 snapshot/version에서 유효하면 전체 승인합니다.
- 하나라도 conflict, confirmation 필요, invalid transition이면 아무것도 저장하지 않습니다.
- 일부 후보를 제외해야 한다면 새 snapshot으로 Supervisor 재계획 → 새 ReviewSubject → 새 Review를 거칩니다.
- 승인 mutation은 ReviewSubject의 candidate ID, field/step/program, before/after 값, Evidence가 정확히 같아야 합니다. 값 수정은 금지하고 전체 승인/거부만 허용합니다.

### `StateGuardrailProof`

| 필드 | 타입 | 필수 |
|---|---|---:|
| `run_id` | UUID | O |
| `case_id` | positive integer | O |
| `review_subject_id` | UUID | O |
| `reviewed_subject_digest` | `sha256:<hex>` | O |
| `snapshot_id` | UUID | O |
| `case_version` | positive integer \| null | O |
| `approved_candidate_ids` | UUID[] | O |
| `result` | literal `PASS` | O |
| `checked_at` | datetime | O |

`approved_candidate_ids`는 ReviewSubject의 모든 mutation candidate ID 집합과 정확히 같아야 합니다. 변경이 하나도 없는 Review된 질문은 `[]`가 가능합니다.

### `PersistReviewedPlanCommand`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `review_subject` | `ReviewSubject` | O | Review 당시 객체 그대로 |
| `review_proof` | `ReviewProof` | O | subject digest PASS |
| `output_guardrail_proof` | `OutputGuardrailProof` | O | 동일 digest, 내용 수정 없는 PASS |
| `state_guardrail_proof` | `StateGuardrailProof` | O | 동일 digest 전체 승인 |

세 proof와 subject의 run/case/subject ID/digest는 전부 같아야 하고 `review_proof.reviewed_at <= output_guardrail_proof.checked_at <= state_guardrail_proof.checked_at`이어야 합니다.

BE는 필요한 원인 event/idempotency key, `EvidenceRecord`, fact changes, procedure progress changes, support match updates, case status change, 최종 decision, History, run/trace 연결을 이 command 하나에서 얻습니다. 원인 event와 idempotency key는 digest로 보호된 `review_subject.trigger`만 사용하며 별도 값으로 덮어쓰지 않습니다. Evidence를 영속화한다면 참조 row보다 먼저 저장하되 정확한 transaction 분리는 BE가 정합니다.

### `PersistResult`

`persist_status` discriminator를 쓰는 tagged union입니다.

`StoredPersistResult`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `persist_status` | literal `STORED` | O |
| `case_id` | positive integer | O |
| `case_version` | positive integer \| null | O |
| `history_id` | positive integer | O |
| `stored_at` | datetime | O |

`VersionConflictPersistResult`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `persist_status` | literal `VERSION_CONFLICT` | O |
| `case_id` | positive integer | O |
| `current_case_version` | positive integer \| null | O |
| `conflicts` | `ConcurrencyConflictDetail[]` (min 1) | O |

`InvalidTransitionPersistResult`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `persist_status` | literal `INVALID_TRANSITION` | O |
| `case_id` | positive integer | O |
| `violation_codes` | upper snake case string[] (min 1) | O |

`FailedPersistResult`:

| 필드 | 타입 | 필수 |
|---|---|---:|
| `persist_status` | literal `ERROR` | O |
| `case_id` | positive integer | O |
| `error` | `ComponentError` | O |

version을 채택하지 않으면 fact/status의 before 값, 절차의 before status, 지원 비교의 `before_match`, Case before status를 조건으로 한 원자적 compare-and-set이 필요합니다. `InvalidTransitionPersistResult`는 BE 함수의 방어적 재검증 결과이며, 저장 전 State Transition Guardrail을 대체하지 않습니다.

## 15. 외부 API/FE 변환 경계

Agent 내부 결과와 HTTP `result`는 같은 enum이 아닙니다.

| 외부 `result` | 생성 지점 | 내부 근거 |
|---|---|---|
| `UPDATED` | BE 저장 성공 | `REVIEWED_PLAN` + Guardrail PASS + `STORED`, 변경 1개 이상 |
| `NO_CHANGE` | BE/Graph | `NoChangeOutcome` |
| `NEEDS_MORE_INFO` | Supervisor + Review | Review PASS한 `NeedsMoreInfoDecisionDraft`, 저장 정책에 따라 History 기록 |
| `CONFLICT` | Graph 또는 Coordinator/BE | 의미 충돌 `ConflictOutcome`, 또는 `GuardrailRejection`/`VersionConflictPersistResult`의 동시성 충돌 |
| `INVALID_TRANSITION` | Coordinator/BE | State `GuardrailRejection`, 또는 방어적 `InvalidTransitionPersistResult` |
| `REPLAN_FAILED` | Coordinator | `SafeFailureOutcome`, Output `GuardrailRejection`, 또는 저장 후 재계획 실패 |
| `CASE_NOT_FOUND` | Input Guardrail | Agent 미호출 |

한 요청에서 확정 가능한 변경과 추가 질문이 동시에 나온 경우 `UPDATED`와 `NEEDS_MORE_INFO` 중 무엇을 우선할지는 외부 API 계약으로 BE/AI/FE가 확정해야 합니다. `STALE`은 지원 비교 상태이며 `/results.result`가 아닙니다.

### Decision → FE view 제안

현재 FE는 `blocker=null`, `nextAction=null`을 정보 부족으로 렌더링하므로 완료/오류와 구분할 discriminator가 필요합니다.

| 내부 | 외부 제안 `viewState` | FE 변환 |
|---|---|---|
| `ACTION` | `ACTION` | `blocker`, `nextAction`; `sequence→seq`, `questions_to_ask→questions` |
| `NEEDS_MORE_INFO` | `NEEDS_MORE_INFO` | blocker + `questionsForUser`, Next Action 없음 |
| `CASE_COMPLETE` | `CASE_COMPLETE` | 완료 화면, 정보 부족 화면 사용 금지 |
| `SAFE_FAILURE` | `ERROR` | 재시도/오류 화면, 정보 부족 화면 사용 금지 |

`CaseFact.status`의 `CONFIRMED/UNKNOWN`과 FE의 `CONFIRMED/IN_PROGRESS/UNKNOWN`, fact label 제공 주체도 외부 adapter 계약에서 맞춰야 합니다. 기존 API 예시의 flat Blocker/Next Action 문자열은 code/title/description/reason/questions 구조와 함께 재검토해야 합니다.

## 16. 구성요소별 capability allowlist

| 구성요소 | 허용 | 금지 |
|---|---|---|
| Supervisor | 정보분석·지원금·절차조회 호출, Review 제출 | DB/Case write, Review 생략, Evidence 생성 |
| 정보분석 Agent | 제공된 redacted input과 snapshot 분석 | 외부 Tool 호출, DB write, 최종 결정 |
| 지원금 Agent | read-only catalog/Wiki/Chroma/S3 조회 | 신청 상태 변경, Wiki 자동 수정, 자격 확정 |
| 절차조회 Tool | 제공된 snapshot과 read-only master 평가 | 자체 반복, 우선순위·Next Action 결정, DB write |
| Review Tool | ReviewSubject만 읽기 | 검색 Tool, DB resolver, 초안 수정, 재호출 결정 |
| PlanningCoordinator | Guardrail, runtime enrichment, Graph 호출, BE 저장 함수 호출 | 도메인 판단 문장 생성 |

BE persistence 함수와 SQL/ORM/session/command handle은 어떤 Agent Tool registry에도 등록하지 않습니다.

## 17. 재시도 규칙

- 목표 BE envelope 계약에서는 정보분석·지원금 Local Loop 상한을 설정값으로 강제하고, 소진을 빈 성공이 아닌 `PARTIAL` output 또는 `LOOP_LIMIT_REACHED` 실패로 구분합니다. 현재 standalone은 정보분석/Supervisor의 constructor 상한과 지원금의 고정 상한을 사용하며, deterministic 검증 소진 시 예외를 Graph 경계에서 `STRUCTURED_OUTPUT_FAILED`로 변환합니다.
- Review `REVISE` 후 재작성은 최대 2회이므로 Review 호출은 최초를 포함해 최대 3회입니다.
- Review 권고는 명령이 아닙니다. 현재 Review runtime은 모든 blocking issue의 `target_component`를 `recommended_rework_targets`에 포함하고, Graph는 그 전체 목록에서 dependency 순서상 가장 앞선 구성요소부터 결정론적으로 재실행합니다. BE 통합 후에도 동일 정책을 유지할지는 계약으로 확정합니다.
- 초안이나 근거가 바뀌면 이전 Review proof를 재사용하지 않습니다.
- Tool timeout/upstream 장애를 `NOT_RELEVANT`, `UNKNOWN`, `CASE_COMPLETE`로 바꾸지 않습니다.
- 상한을 넘으면 검토되지 않은 판단을 폐기하고 `SafeFailureOutcome`을 반환합니다.
- `REPLAN_FAILED`에서 앞서 반영된 Case 변경을 유지할지 rollback할지는 BE transaction 계약에서 확정합니다. 이전 판단을 새 snapshot의 판단처럼 반환하지 않습니다.

## 18. Standalone Agent 런타임 현황과 검증

### 현재 구현된 AI 범위

| 범위 | 현재 구현 |
|---|---|
| 공통 계약 | `backend/app/agent/schemas.py`의 strict Pydantic schema, Review digest/proof, standalone field registry |
| 정보분석 Agent | provider 형식과 로컬 의미 schema 분리, redacted 입력 span 검증, 사실/절차 관측 후보, 충돌 분리, bounded local retry |
| 지원금 Agent | provider 형식과 로컬 의미 schema 분리, 주입된 reviewed catalog 기반 조회/판정, 최소 prompt projection, Evidence 연결 |
| 절차조회 Tool | 주입된 read-only master의 선행조건 DAG·snapshot 기반 결정론적 평가 |
| Supervisor Agent | 전달된 하위 결과 전체를 기반으로 `ACTION`일 때 정확히 1개 Blocker/Next Action 조립, 직전 초안 기반 Review 수정, 고위험 claim 사전검증, mutation/provenance 검증, bounded rewrite |
| Review Tool | provider 형식 출력과 로컬 의미 검증 분리, bounded corrective retry, ReviewSubject digest·독립 규칙 재검사, `PASS`/`REVISE` ReviewResult 반환 |
| Graph | LangGraph 기반 정보분석→절차조회→지원금 순차 실행, Review dependency rerouting, 최대 2회 재작성, `PASS` 후 Review proof 발급, fail-closed outcome |
| 실행/검증 | 합성 fixture 전용 CLI와 `backend/tests/agent` contract/runtime test |

현재 공개 사용 형태는 다음과 같습니다.

```python
outcome: AgentRunOutcome = await graph.run(request, trace_id="request-trace-id")
```

현재 실제 `AgentRunOutcome`은 `REVIEWED_PLAN | CONFLICT | SAFE_FAILURE` 세 variant입니다. 이 문서의 `NO_CHANGE`는 목표 계약으로만 남아 있으며 아직 runtime에 구현되지 않았습니다. `REVIEWED_PLAN`은 검토된 제안이지 저장 허가가 아니므로, `ReviewProof`가 있어도 BE Output/State Guardrail과 transaction 없이 DB에 반영하면 안 됩니다.

LLM provider에는 `InfoProviderOutput`, `SupportProviderOutput`, `SupervisorModelOutput`, `ReviewProviderOutput`의 형식 중심 structured-output schema를 전달합니다. 각 응답은 Agent 내부 bounded retry에서 각각 `InfoAnalysisDraft`, `SupportAnalysisDraft`, `SupervisorSemanticDraft`, `ReviewModelOutput`의 의미 규칙으로 다시 검증합니다. 이들은 새 runtime identity·시각·digest·인증 정보와 비-redacted 원문을 모델이 생성하지 않도록 제한한 최소 projection이며 BE wire DTO가 아닙니다. 분석에 필요한 stable reference/Evidence ID, Review 대상 call ID와 정보분석의 redacted input에서 선택한 `source_text`는 입력에서 선택·복사할 수 있고 runtime이 원 입력과 대조합니다. provider 호환 strict JSON Schema에서는 지원되지 않는 annotation keyword를 제거하고 object property를 required로 투영하지만, 전체 Pydantic 검증과 결정론적 domain/provenance Guardrail은 로컬 runtime이 최종 권한을 가집니다. 구조화 출력 호출 형태는 [OpenAI Chat Completions API](https://developers.openai.com/api/reference/cli/resources/chat), Graph 구성 방식은 [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)를 기준으로 검증했습니다.

### 로컬 실행

Python 3.12 환경에서 다음과 같이 독립 검증할 수 있습니다.

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/agent
PYTHONPATH=backend backend/.venv/bin/python -m app.agent.cli --live --compact --trace-id local-smoke
```

CLI는 임의의 실제 Case 입력을 받지 않고 repository의 합성 fixture만 사용합니다. `--live`는 필수이고 설정된 provider에 과금 가능한 실제 API 요청을 보내지만, BE API·DB·외부 저장소에는 쓰지 않습니다.

필수 환경변수 이름은 `CHAT_PROXY_URL`, `PROXY_TOKEN`, `OPENAI_MODEL`입니다. `CHAT_PROXY_URL`은 loopback 개발 서버를 제외하면 HTTPS여야 하고 credential/query/fragment를 포함할 수 없습니다. 연결 endpoint가 허용하는 모델명을 써야 하며 2026-09-15 최종 검증에도 `openai/gpt-4.1-mini`를 사용했습니다. 선택 설정은 `OPENAI_REASONING_EFFORT`, `AGENT_LLM_TIMEOUT_SECONDS`, `AGENT_LLM_MAX_RETRIES`, `AGENT_LLM_RETRY_BACKOFF_SECONDS`입니다. 토큰과 실제 endpoint 값은 문서·출력·trace에 남기지 않습니다.

2026-09-15 최종 검증 결과는 다음과 같습니다.

- 주요 public/provider/local 입출력 schema 19종 JSON Schema compile 통과
- Agent test `155 passed` (`-W error`), Ruff check/format check 통과
- 공식 standalone CLI로 실제 structured-output API 전체 Graph 실행 성공, exit code `0`
- 최종 outcome `REVIEWED_PLAN`, Review `PASS`, decision `ACTION`
- Blocker 1개, Next Action 1개, 사용한 source result 3개
- 최종 코드 실행은 `review_attempt=1`에서 통과했으며, 직전 초안 기반 수정과 content-aware Review 재작성 경로도 자동 테스트로 검증
- 보강 전 반복 실행에서 구조화 의미 오류와 `REVIEW_RETRY_EXHAUSTED`를 관찰해 provider/local schema 분리, runtime rework target 계산, Supervisor 고위험 claim 사전검증을 추가함
- 모델 판단과 외부 provider가 포함되므로 한 번의 live 호출이 항상 `PASS`하는 것은 아니며, 제한 내 해결되지 않으면 미검토 결과 대신 `SAFE_FAILURE`만 반환
- 합성 입력만 사용했고 BE/DB persistence는 0건

### BE 연동 전에 남은 경계

standalone 정상 실행은 아래 생산 연동 기능의 완료를 뜻하지 않습니다.

- `ComponentRequest`/`ComponentResult` envelope와 HTTP adapter가 아직 없으며 현재 구성요소 호출은 bare payload/result입니다.
- 현재 `CaseSnapshot`은 목표 계약의 `support_applications`, `support_matches`, `latest_decision`, `history_window`를 아직 포함하지 않습니다.
- 현재 mutation은 목표 저장 계약의 절차 `execution_input_event_id`, `source_observation_id`, `source_observation_call_id`와 지원 `before_match`를 아직 포함하지 않습니다.
- `PlanningCoordinator`, 인증/소유권, idempotency, version/CAS, Output Guardrail, State Transition Guardrail, transaction, DB 저장 함수는 미구현입니다.
- standalone `conflict_ref`는 `standalone:<24-hex digest prefix>` 형식의 simulation 전용 값입니다. 저장하거나 `/results/confirm`에 전달할 수 없으며, BE가 발급·복원하는 reference와 confirmed-conflict round trip이 별도로 필요합니다.
- 현재 `FactCandidate`는 단일 모델+validator이고, 목표 BE 계약은 `SET | CLEAR` tagged union입니다.
- provider semantic schema는 BE schema가 아니며 그대로 shared DTO로 사용하면 안 됩니다.
- `CASE_FIELD_SPECS`는 standalone 임시 registry입니다. BE canonical enum/type과 합의 없이 확장하거나 production 판단에 사용하면 안 됩니다.
- Review digest의 cross-language 고정 test vector가 없으므로 다른 언어의 BE 구현과 digest가 같다는 보장이 아직 없습니다.
- 현재 Graph state와 §11의 목표 `AgentGraphState`가 다르고, Review 재작업 대상은 Supervisor 판단이 아니라 `recommended_rework_targets` 전체에서 가장 앞선 dependency로 선택됩니다.
- `NO_CHANGE`, 생산용 `CONFLICT_CONFIRMED`, 실데이터 resolver/catalog/procedure adapter는 아직 연결되지 않았습니다.

따라서 현재 상태는 “BE 없이 합성 입력으로 Agent 의사결정·Review 루프를 실행할 수 있음”이며, “실제 사용자 Case를 안전하게 읽고 저장할 수 있음”은 아닙니다. 생산 연동에서는 `ReviewedPlanOutcome + ReviewProof`만으로 저장하지 말고 §14의 Coordinator/Guardrail/persistence 계약을 먼저 구현해야 합니다.

## 19. BE 통합 전에 확정할 항목

### P0 — schema 구현을 막는 항목

- [ ] `case_version`을 채택할지, 아니면 field-level atomic compare-and-set을 사용할지
- [ ] DB 미확인을 enum `UNKNOWN`으로 둘지 별도 fact status로 둘지. Agent snapshot 표현은 `status=UNKNOWN, value=null`
- [ ] API에 있지만 CASE에 없는 `entity_type`, `building_use_type`, `previous_support_history` 저장 위치
- [ ] Hero Scenario에 있지만 현재 API/DB에 없는 `lease_end_date`, `transfer_status`, `tax_status`의 v1 포함 여부. 합의 전 판단에 사용 금지
- [ ] `lease_status`, `restoration_scope`, `demolition_required`의 canonical enum
- [ ] 절차 master의 `step_code`, data version, `decision_authority`, 조건 operator, 공식 Evidence 연결
- [ ] `support_program_id`/`wiki_uuid`/기존 `support_item_id` 명칭과 resolver
- [ ] 지원 비교 `match_status`와 실제 신청 `application_status`의 물리 분리
- [ ] 자연어 `RESULT_SUBMITTED`가 지원 신청상태도 바꿀지, 명시적 신청상태 API만 사용할지
- [ ] Evidence 저장소/resolver, ID, lineage, 보존 정책
- [ ] Blocker/Next Action 상세, Review subject/proof, run/trace 연결을 저장할 위치
- [ ] `conflict_ref` 구현 방식, `/results/confirm` version/CAS, 보존 기간
- [ ] `client_event_id` idempotency 의미와 보존 기간
- [ ] 한 요청에 변경과 추가 질문이 함께 있을 때 외부 `result` 우선순위
- [ ] Local Loop·Review timeout/structured-output 재시도 기본값
- [ ] Case/절차/지원 비교/판단/History transaction과 `REPLAN_FAILED` 정책
- [ ] runtime/model/telemetry별 redaction 및 외부 LLM 전달 감사 정책
- [ ] 기존 architecture의 “Blocker 1개·Next Action 1개” 문구가 `ACTION`에만 적용되고 확인/완료 분기는 예외임을 공동 확정

### P1 — 외부 API 연결 전에 확정할 항목

- [ ] 내부 `snake_case` → HTTP `camelCase` adapter mapping
- [ ] `viewState`, Decision 상세 필드, 예외별 discriminated response
- [ ] FE fact label과 상태 변환 주체
- [ ] 외부로 공개할 Evidence URL·설명 범위
- [ ] offset 없는 기존 datetime 예시를 timezone 포함 계약으로 갱신

### v1에서 보류

- `equipment_item_candidates`와 집기 처리 저장 모델
- 세무·철거 보조 Agent
- 스트리밍 진행 이벤트
- Agent의 Wiki 자동 수정
- 지원 금액 필드

## 20. 최소 contract 검증 기준

- [ ] 모든 하위 결과의 run/case/snapshot이 현재 실행과 같다.
- [ ] `based_on_candidate_ids`는 실제 `READY_FOR_REVIEW` overlay의 부분집합이다.
- [ ] Supervisor/source result/decision/mutation/Evidence의 current-run call ID 집합이 §11의 폐쇄 규칙대로 정확히 같다.
- [ ] snapshot facts는 field별 unique이며 모든 확정 사실에 Evidence가 있다.
- [ ] 모든 Evidence 참조가 trigger, snapshot 또는 source result 안에서 해석된다.
- [ ] 같은 Evidence ID의 내용/hash가 서로 다르면 거부한다.
- [ ] 정보분석 결과의 span이 redacted input에 실제 존재하고 whitelist 밖 field를 거부한다.
- [ ] `CONFLICT`/`REQUIRES_CONFIRMATION` 후보는 확인 proof 없이 저장하지 않는다.
- [ ] conflict resolution은 원 digest와 version에 결합되고 committed/proposed 중 하나만 선택한다.
- [ ] Review subject의 어느 값이든 변경되면 digest 검증과 저장이 실패한다.
- [ ] 위험 Review issue를 `WARNING`으로 내려 `PASS`하지 못한다.
- [ ] State Guardrail이 Review된 mutation 일부만 골라 저장하지 못한다.
- [ ] mutation candidate ID와 대상 key가 중복되지 않고, version 또는 모든 before 상태로 CAS한다.
- [ ] 모든 mutation 내용이 참조한 fact/observation/check/conflict와 §6 deep-equal하다.
- [ ] `CASE_COMPLETE`와 Case 완료 mutation은 함께만 존재하며 다른 decision에는 완료 mutation이 없다.
- [ ] Output/State Guardrail은 Review된 payload를 수정하지 않고 PASS 또는 전체 거부만 한다.
- [ ] 모든 `GroundedClaim.target_path`의 실제 문자열이 claim text와 정확히 같다.
- [ ] completion/status/freshness/professional discriminator의 조건부 불변식을 거부 테스트로 검증한다.
- [ ] 현실 실행 Evidence 없이 절차를 `COMPLETED`로 바꾸지 못한다.
- [ ] 지원금 결과에 `ELIGIBLE`이 있거나 stale 근거로 positive/negative 확정을 하면 거부한다.
- [ ] 절차조회 결과에 우선순위·선택·Next Action 필드가 있으면 extra field 검증으로 거부한다.
- [ ] 절차 관련 Action에는 사용된 `ProcedureStepEvaluation`, 지원 관련 문구에는 사용된 `SupportCheck`가 있다.
- [ ] Review 없이 새 도메인 문장, Blocker, Next Action을 외부로 내보내지 않는다.
- [ ] 조회만으로 지원 신청 row를 생성·변경하지 않는다.
- [ ] 인증 토큰, 주소, 계약서 원문, 민감 입력이 trace에 남지 않는다.
- [ ] 기술 실패를 도메인상 해당 없음이나 Case 완료로 바꾸지 않는다.

## 21. BE에 우선 요청할 shared DTO

P0 합의 뒤 BE shared 경계에 우선 필요한 schema는 다음과 같습니다.

1. `CaseSnapshot`, `CaseFact`, `ProcedureProgress`, `SupportApplicationSummary`, `SupportMatchSummary`
2. `EvidenceRecord`와 Evidence resolver 계약
3. `SupervisorRunInput`, `ConfirmedConflictResolution`, `ProcedureProgressObservation`
4. `ReviewSubject`, `ReviewProof`, `MutationSet`
5. 목표 `AgentRunOutcome` 네 variant. 현재 standalone은 `REVIEWED_PLAN | CONFLICT | SAFE_FAILURE`만 구현하고 `NO_CHANGE`는 보류
6. `OutputGuardrailProof`, `StateGuardrailProof`, `GuardrailRejection`, `ConcurrencyConflictDetail`, `PersistReviewedPlanCommand`, `PersistResult`
7. 외부 API 결과와 `viewState`용 discriminated response DTO

정보분석·지원금·절차조회·Review의 모델 출력 schema는 AI 영역에서 정의하되, BE shared DTO 경계를 임의 `dict`로 받지 않도록 함께 import 가능한 계약으로 확정합니다.
