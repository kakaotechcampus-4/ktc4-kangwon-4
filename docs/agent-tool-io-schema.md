# RE:BORN Agent/Tool 내부 입출력 스키마

| 항목 | 내용 |
|---|---|
| 계약 버전 | `agent-io/2.0` |
| 기준일 | 2026-09-15 |
| 범위 | 현재 Python 코드로 구현된 standalone Agent/Tool 내부 계약 |
| 제외 범위 | BE HTTP DTO, DB 모델·migration, 인증·인가, 운영 저장, 외부 Guardrail 계약 |

이 문서는 **현재 AI 런타임 안에서 실제로 생성·검증·소비하는 Agent/Tool 입출력**의 단일 설명서다. 실행 가능한 최종 권위는 [`backend/app/agent/schemas.py`](../backend/app/agent/schemas.py)와 각 구성요소의 Pydantic 모델·validator이며, 이 문서는 그 코드를 사람이 검토할 수 있도록 같은 경계를 정리한다.

BE가 구현하거나 AI와 공동 승인해야 하는 HTTP/shared DTO와 저장 불변식은 [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)만 따른다. 전체 호출 구조는 [`architecture.md`](./architecture.md), 실행법·환경변수·데이터 모드는 [`agent-standalone-runtime-requirements.md`](./agent-standalone-runtime-requirements.md), 외부 공식 데이터/API와 크롤링·RAG 계획은 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)를 따른다. 이 문서에는 해당 내용을 중복 정의하지 않는다.

## 0. 먼저 보는 핵심 용어

| 용어 | 이 문서에서의 뜻 |
|---|---|
| snapshot | 한 번의 실행이 기준으로 삼는 특정 시점의 Case 읽기 상태 |
| fact | Case에서 관리하는 구조화된 사실 값 |
| catalog | 검수됐다고 가정하고 지원금 Agent에 주입하는 지원사업 목록 |
| Evidence | 주장·후보가 어떤 입력이나 공식 원문에 근거했는지 추적하는 레코드 |
| provenance | 어떤 run·호출·snapshot·Evidence에서 결과가 나왔는지 나타내는 출처 연결 정보 |
| digest | 내용 변경을 검출하기 위해 canonical JSON에 계산한 SHA-256 값 |
| provider | LLM 또는 외부 검색/API처럼 구성요소가 호출하는 외부 제공자 |

## 1. 리뷰 전에 알아야 할 상태 기준

이 문서의 연결 상태는 **현재 feature 브랜치의 standalone Python 실행 경로**를 기준으로 한다. BE API·DB 연동 완료 또는 최종 Agent 아키텍처 승인을 뜻하지 않는다. 기존 영문 내부 상태 코드는 리뷰 시 의미를 다시 해석해야 하므로 사용하지 않고, 아래 한국어 상태를 직접 적는다.

| 문서 표기 | 판단 기준 |
|---|---|
| 현재 실행 흐름에 연결됨 | 구현·검증됐으며 현재 standalone LangGraph 실행 중 실제 생성·호출·소비된다. |
| 일부 입력만 연결됨 | 공개 메서드는 여러 입력 variant를 처리하지만 현재 실행기가 그중 일부만 생성한다. |
| 구현됨 · 실행 흐름 미연결 | 구현과 단위 테스트는 있지만 현재 app/LangGraph 호출 경로가 없다. |
| 타입만 정의됨 | Pydantic 타입과 validator는 있지만 정상 실행에서 생성·소비되지 않는다. |

따라서 “코드에 타입이 있다”, “독립 단위 테스트가 통과한다”, “standalone 실행에서 호출된다”, “실제 사용자 Case와 연동됐다”는 서로 다른 상태다.

### 빠른 검토 순서

1. 아래 §2에서 Agent와 Tool의 역할·직접 입출력·연결 상태를 확인한다.
2. §3~4에서 모든 schema에 공통으로 적용되는 strict type, Evidence, Case snapshot 규칙을 확인한다.
3. §5~10에서 각 Agent와 Tool의 필드·조건부 불변식을 확인한다.
4. §11에서 Agent가 아닌 LangGraph 실행 경계와 최종 결과를 확인한다.
5. §12에서 타입·기능별 현재 실행 상태를 확인한다.

## 2. Agent·Tool별 직접 입출력 스키마

각 Agent와 Tool의 공개 메서드는 **입력 Pydantic schema 객체 하나**를 받고, 정상 처리 시 **반환 schema 객체 하나**를 돌려준다. 생성자 dependency, LLM provider 내부 draft, LangGraph 내부 state, DB 저장 모델은 이 직접 입출력에 섞지 않는다.

구성요소 오류는 반환 schema가 아니라 typed exception으로 전달한다. LangGraph 실행 경계는 이를 검수되지 않은 결과가 섞이지 않는 `SafeFailureOutcome`으로 변환한다. 현재 `ComponentRequest`/`ComponentSuccess`/`ComponentFailure` envelope는 타입만 정의돼 있고 공개 호출에는 사용하지 않는다.

### 2.1 Agent

| Agent | 역할 | 현재 호출 위치 | 연결 상태 |
|---|---|---|---|
| 정보분석 Agent<br/>`InfoAnalysisAgent.analyze()` | 비식별 사용자 입력, Case snapshot, 공식 절차 원문을 해석해 사실 변경·절차 진행 관측·충돌·누락 정보·질문 **후보**를 만든다. Case를 직접 변경하지 않는다. | `AgentGraph`의 `info_analysis` node | 현재 실행 흐름에 연결됨<br/>`CASE_CREATED`, `RESULT_SUBMITTED`에서 호출 |
| 지원금 Agent<br/>`SupportAgent.analyze()` | Case와 미저장 fact 후보를 주입된 검수 지원사업 catalog와 비교한다. raw 공고를 직접 검색하거나 실제 수급 자격을 확정하지 않는다. | `AgentGraph`의 `support_analysis` node | 일부 입력만 연결됨<br/>`DISCOVER_RELEVANT`, `REFRESH_STALE`은 연결; `CHECK_SPECIFIC`은 미연결 |
| Supervisor Agent<br/>`SupervisorAgent.draft()` | 앞 단계 결과를 종합해 Blocker, Next Action, 변경 후보와 근거를 포함한 **검수 전 초안**을 만든다. 현재는 실행 순서를 정하거나 하위 Agent·Tool을 직접 호출하지 않는다. | `AgentGraph`의 `supervisor` node | 현재 실행 흐름에 연결됨<br/>Info conflict로 끝나지 않은 경로에서 호출 |

| Agent | 직접 입력 schema·핵심 필드 | 직접 반환 schema·핵심 필드 |
|---|---|---|
| 정보분석 | [`InfoAnalysisInput`](#61-입력-infoanalysisinput)<br/>`input`, `case_snapshot`, 허용 field, canonical 절차 step, 절차조회 결과·call ID, Review feedback | [`InfoAnalysisResult`](#62-출력-infoanalysisresult)<br/>fact·progress·procedure 후보, conflict, missing field, 사용자 질문, uncertainty, Evidence, snapshot·source provenance |
| 지원금 | [`SupportAgentInput`](#73-입력-supportagentinput)<br/>`lookup_goal`별 요청, `planning_context`, 관련 절차 step, 기준일, Review feedback | [`SupportAnalysisResult`](#74-출력-supportanalysisresult)<br/>program별 criterion 비교 결과, `support_checks[].unknown_field_paths`, uncertainty, 검색 요약, catalog Evidence·provenance |
| Supervisor | [`SupervisorAgentInput`](#91-입력-supervisoragentinput)<br/>`trigger`, `case_snapshot`, 선행 결과와 digest, fact overlay, draft version, Review feedback, 이전 초안 | [`SupervisorDraft`](#92-출력-supervisordraft)<br/>`decision`, 검수 전 `mutations`, `grounded_claims`, 사용한 source call ID |

`ReviewedSupportCatalog`는 `SupportAgent.analyze()`의 호출별 입력이 아니라 Agent 생성 시 주입하는 dependency다. 현재 standalone에서는 합성 fixture를 주입한다.

### 2.2 Tool

| Tool | 역할 | 현재 호출 위치 | 연결 상태 |
|---|---|---|---|
| 절차조회 Tool<br/>`ProcedureLookupTool.lookup()` | 폐업 절차 관련 공식 URL을 찾고 원문을 직접 가져와 문서와 Evidence로 정규화한다. Case 적용 여부나 절차 완료 여부는 판단하지 않는다. | `AgentGraph`의 `procedure_lookup` node | 현재 실행 흐름에 연결됨<br/>`CASE_CREATED`, `RESULT_SUBMITTED`에서 Info보다 먼저 호출 |
| Review Tool<br/>`ReviewTool.review()` | snapshot, 선행 결과, Supervisor 초안을 provenance·근거·안전 규칙에 따라 검수한다. 초안을 직접 수정하지 않는다. | `AgentGraph`의 `review` node | 현재 실행 흐름에 연결됨<br/>Supervisor 초안 뒤 필수 호출 |
| 기업마당 공고조회 Tool<br/>`BizInfoSupportDiscoveryTool.discover()` | 기업마당 API 응답을 검수 전 raw 공고 후보와 공식 API Evidence로 정규화한다. 지원 자격 판정이나 검수 catalog 발행은 하지 않는다. | 현재 app 호출자 없음 | 구현됨 · 실행 흐름 미연결<br/>현재 저장소 호출자는 단위 테스트뿐이며 독립 직접 호출은 가능 |

| Tool | 직접 입력 schema·핵심 필드 | 직접 반환 schema·핵심 필드 |
|---|---|---|
| 절차조회 | [`ProcedureLookupInput`](#52-입력-procedurelookupinput)<br/>조회 query, 기준일, `OFFICIAL_ONLY` 정책, 결과 상한, 기준 snapshot ID, Review feedback | [`ProcedureLookupResult`](#53-출력-procedurelookupresult)<br/>직접 fetch한 공식 문서, provider별 검색 요약, warning, `OFFICIAL_DOCUMENT` Evidence, snapshot provenance |
| Review | [`ReviewSubject`](#101-입력-reviewsubject)<br/>trigger, snapshot, 선행 결과와 digest, Supervisor 초안, subject digest, Review attempt | [`ReviewResult`](#102-출력-reviewresult)<br/>`PASS`/`REVISE`, 판정 이유, issue, 누락 Evidence, 권고 재작업 대상 |
| 기업마당 공고조회 | [`SupportNoticeDiscoveryInput`](#81-입력-supportnoticediscoveryinput)<br/>keyword, 최대 결과 수 | [`SupportNoticeDiscoveryResult`](#82-출력-supportnoticediscoveryresult)<br/>provider, raw 공고 후보, `OFFICIAL_API` Evidence, 원본·중복·절단 건수 |

`ReviewProof`는 Review Tool의 반환값이 아니다. 실행기가 exact `PASS`와 동일한 subject/run/snapshot/digest를 확인한 뒤에만 생성한다.

### 2.3 LangGraph 실행 경계 — Agent/Tool 아님

`LangGraph`는 외부 프레임워크이고 `StateGraph`는 그 프레임워크가 제공하는 그래프 구성 객체다. `AgentGraph`는 이번 feature 브랜치에서 `StateGraph`를 구성·compile·실행하도록 만든 **프로젝트 내부 Python 클래스명**이다. 새로운 Agent도 아니고 LangGraph의 다른 이름도 아니다.

| 실행 경계 | 역할 | 직접 입출력 | 현재 연결 상태 |
|---|---|---|---|
| `AgentGraph.run()` | 현재 고정 실행 순서, 단계 간 결과 전달, Review 재작업, 반복 상한, fail-closed 처리 | [`AgentGraphInput`](#111-입력-agentgraphinput) → [`AgentGraphOutput`](#112-출력-agentgraphoutput) | 현재 실행 흐름에 연결됨<br/>standalone CLI/test 한정; 실제 사용자 Case read/write 경로는 없음 |

`AgentGraphOutput`은 `ReviewedPlanOutcome | ConflictOutcome | SafeFailureOutcome` union이다. 여기서 Python 호출이 schema 객체를 반환했다는 사실과 업무 계획이 성공했다는 의미는 다르다.

### 2.4 직접 계약과 내부 보조 schema 구분

| 분류 | schema 예시 | 의미 |
|---|---|---|
| 실행기 직접 계약 | `AgentGraphInput`, `AgentGraphOutput` | 한 번의 전체 실행 요청과 최종 결과. Agent/Tool 자체의 입출력은 아니다. |
| Agent/Tool 직접 계약 | 위 §2.1~2.2의 입력·반환 schema | 각 공개 메서드가 직접 받거나 반환하는 객체다. |
| 생성자 dependency·공통 context | `ReviewedSupportCatalog`, `CaseSnapshot`, `EvidenceRecord`, `KnownProcedureStep`, `PlanningContext`, `ReviewSourceResult` | 호출을 구성하거나 출처를 연결하는 보조 모델이다. 그 자체가 독립 Agent/Tool 결과는 아니다. |
| provider 내부 형식·local draft | `InfoProviderOutput`, `SupportProviderOutput`, `SupervisorModelOutput`, `ReviewProviderOutput` 등 | LLM 구조화 출력을 제한하고 local guardrail을 적용하기 위한 구현 내부 모델이다. |
| Supervisor 안의 변경 후보 | `FactChangeCandidate`, `ProcedureProgressChangeCandidate`, `SupportMatchUpdateCandidate` | `SupervisorDraft.mutations` 안의 검수 전 후보이며 DB 반영 결과가 아니다. |
| 검수 증명 | `ReviewProof` | Review Tool 출력이 아니라 실행기가 matching `PASS` 뒤 만든다. |

### 2.5 현재 standalone 실행 흐름

아래 순서는 **현재 feature 브랜치의 구현 사실**이다. 기존 목표 아키텍처처럼 Supervisor가 필요한 Agent·Tool을 선택하는 동적 planning은 아직 구현되지 않았다. 목표와 현재 구현의 차이는 [`architecture.md`](./architecture.md)에서 별도로 비교한다.

```text
CASE_CREATED | RESULT_SUBMITTED
  AgentGraphInput
    → ProcedureLookupInput → ProcedureLookupResult
    → InfoAnalysisInput     → InfoAnalysisResult
        ├─ conflicts 있음 → ConflictOutcome → 현재 run만 종료(사용자 확인 필요)
        └─ conflicts 없음
             → SupportAgentInput
             → SupportAnalysisResult
             → SupervisorAgentInput → SupervisorDraft
                  └─ decision = ACTION | NEEDS_MORE_INFO(추가 질문)
             → ReviewSubject → ReviewResult
                  ├─ PASS   → ReviewProof → ReviewedPlanOutcome
                  ├─ REVISE → 지정 dependency부터 재실행(최대 2회 수정)
                  └─ 실패/소진 → SafeFailureOutcome

SUPPORT_REFRESH
  AgentGraphInput
    → RefreshSupportInput → SupportAnalysisResult
    → SupervisorAgentInput → SupervisorDraft
    → ReviewSubject → ReviewResult
         ├─ PASS   → ReviewProof → ReviewedPlanOutcome
         ├─ REVISE → 지정 dependency부터 재실행
         └─ 실패/소진 → SafeFailureOutcome
```

핵심 소유권은 다음과 같다.

- 절차조회 Tool은 공식 원문과 Evidence를 가져오며 의미 판단을 하지 않는다.
- 정보분석 Agent는 사용자 입력과 절차조회 결과를 해석해 사실 후보·현실 진행 관측·canonical 절차 finding을 만든다.
- 지원금 Agent는 주입된 검수 catalog와 Case 사실을 비교한다.
- Supervisor만 Blocker·Next Action·Decision 초안을 만들지만, 현재 하위 호출 순서는 정하지 않는다.
- Review Tool은 초안과 근거 package를 검수하지만 초안을 수정하지 않는다.
- Agent/Tool/Graph 어디에도 DB 쓰기 또는 HTTP endpoint가 없다.

근거: [`graph.py`](../backend/app/agent/graph.py), [`state.py`](../backend/app/agent/state.py), [`test_graph.py`](../backend/tests/agent/test_graph.py).

## 3. 공통 직렬화·검증 규칙

### 3.1 기본 규칙

`schemas.py`의 `AgentSchema`를 상속한 모델은 다음을 강제한다.

- JSON/Python 필드명은 `snake_case`다.
- 선언되지 않은 필드는 `extra="forbid"`로 거부한다.
- 할당 시점과 기본값도 검증한다.
- `StrictStr`, `StrictInt`, `StrictBool`을 사용한 값은 문자열 숫자, `0/1` boolean 같은 암시적 coercion을 허용하지 않는다.
- 표에서 `T | null`은 key가 존재하고 값이 `null`일 수 있다는 뜻이다.
- 목록은 값이 없을 때 `[]`이며 `null`이 아니다.
- `PositiveStrictInt`는 strict integer `> 0`, `NonNegativeStrictInt`는 strict integer `>= 0`이다.
- `UpperSnakeCode`는 정규식 `^[A-Z][A-Z0-9_]*$`를 만족한다.
- `JsonPointer`는 RFC 6901 escape 형태를 허용하는 `/...` 경로다.
- `Digest`는 `sha256:` 뒤에 소문자 64자리 hex가 오는 문자열이다.
- `RuntimeDateTime`과 모든 aware datetime은 timezone 정보가 있어야 한다.
- `RuntimeUUID`·`RuntimeDateTime` 표시는 문서화 metadata다. 새 ID와 시각은 provider 출력에서 제외하고 구성요소 코드가 생성·주입한다. Review provider가 기존 source `target_call_id`를 선택하는 예외는 있지만, runtime이 JSON Pointer의 실제 owner와 다시 대조해 component/call ID를 결정적으로 재결합한다.

`StrictScalar`는 `strict string | strict integer | strict boolean | date | null`, `NonNullStrictScalar`는 여기서 `null`을 제외한 타입이다. JSON의 `date`는 `YYYY-MM-DD`로 직렬화한다.

### 3.2 현재 사용: canonical digest

`canonical_digest(model)`은 Review source·subject와 conflict 무결성에 사용한다.

1. 선언된 model field만 읽는다.
2. 명시한 제외 필드를 제거한다.
3. enum은 value, UUID는 문자열, date는 ISO date로 바꾼다.
4. datetime은 UTC, microsecond 6자리, `Z` suffix로 정규화한다.
5. dict key는 정렬하고 array 순서는 유지한다.
6. 공백 없는 UTF-8 JSON으로 직렬화하며 float/NaN은 거부한다.
7. SHA-256을 계산해 `sha256:<64-hex>`를 반환한다.

근거: [`schemas.py`](../backend/app/agent/schemas.py)의 `canonical_digest`, [`test_schemas.py`](../backend/tests/agent/test_schemas.py).

### 3.3 현재 사용: `InvocationMeta`

Graph가 각 하위 호출과 Review provenance에 생성한다. 현재 `parent_call_id`는 Graph에서 항상 `null`이다.

| 필드 | 타입 | 의미·생성자 |
|---|---|---|
| `schema_version` | literal `agent-io/2.0` | Graph가 현재 내부 계약 버전을 고정 |
| `run_id` | runtime UUID | Graph가 전체 실행마다 생성하는 ID |
| `call_id` | runtime UUID | Graph가 각 구성요소 호출마다 생성하는 ID |
| `parent_call_id` | runtime UUID \| null | 상위 호출 연결용 예약 필드; 현재 Graph는 항상 null 생성 |
| `case_id` | positive strict integer | Graph가 입력 snapshot의 Case ID를 복사 |
| `component` | `SUPERVISOR \| INFO_AGENT \| SUPPORT_AGENT \| PROCEDURE_TOOL \| REVIEW_TOOL` | Graph가 호출 대상과 일치하는 component를 기록 |
| `attempt` | positive strict integer | Graph가 같은 역할의 현재 호출 차수를 기록 |
| `requested_at` | aware datetime | Graph clock이 실제 호출 직전에 생성 |
| `trace_id` | non-empty string \| null | Graph가 `AgentGraphInput.trace_id`를 복사; 판단에는 사용하지 않음 |

### 3.4 타입만 정의됨: component envelope

아래 타입은 구현되어 있지만 현재 Graph와 구성요소 메서드는 사용하지 않는다. 코드에는 `ComponentResult` alias도 없다.

| 모델 | 필드 |
|---|---|
| `ComponentRequest[T]` | `meta: InvocationMeta`, `input: T` |
| `ComponentSuccess[T]` | `execution_status: SUCCESS`, `meta`, `output: T`, `warnings: ComponentWarning[]` |
| `ComponentFailure` | `execution_status: ERROR`, `meta`, `error: ComponentError` |
| `ComponentWarning` | `code: UpperSnakeCode`, `message: string`, `target_path: JsonPointer \| null` |
| `ComponentError` | `code`, `message_code`, `retryable`, `failed_dependency`, `retry_after_ms` |

`ComponentError.code` 허용값은 `INVALID_INPUT | SCHEMA_VALIDATION_FAILED | SNAPSHOT_UNAVAILABLE | SOURCE_UNAVAILABLE | TIMEOUT | RATE_LIMITED | UPSTREAM_ERROR | LOOP_LIMIT_REACHED | INTERNAL_ERROR`다.

## 4. 공통 입력 기반 스키마

### 4.1 현재 사용: `RedactedInput`

| 필드 | 타입 | 불변식 |
|---|---|---|
| `input_event_id` | non-empty string | trigger의 event ID와 교차검증 |
| `source_type` | `USER_INPUT \| EXPERT_CONFIRMATION` | 현재 타입이 허용하는 값 |
| `redacted_text` | non-empty string | 정보분석에 전달되는 텍스트 |
| `redactions` | `Redaction[]` | 겹치지 않고 text 범위 안이어야 함 |
| `submitted_at` | aware datetime | 입력 시각 |

`Redaction`은 `type`, `placeholder`, `start_offset`, `end_offset`을 갖는다.

- `type`: `ADDRESS | NATIONAL_ID | ACCOUNT | TOKEN | OTHER`
- `0 <= start_offset < end_offset`
- `redacted_text[start_offset:end_offset] == placeholder`
- 정렬했을 때 span끼리 겹칠 수 없다.
- 원래 민감값을 담는 필드는 없다.

정보분석 runtime이 만드는 `VerifiedTextSpan`은 `input_event_id`, `text`, `start_offset`, `end_offset`을 갖고 `end_offset - start_offset == len(text)`를 만족한다. 추가로 Info Agent가 해당 `text`가 입력에 실제 존재하는 exact span인지 확인한다.

### 4.2 현재 사용: `EvidenceRecord`

| 필드 | 타입 | 의미·생성자 |
|---|---|---|
| `evidence_id` | non-empty opaque string | 결과 producer가 Evidence를 참조하기 위해 생성하는 고유 ID |
| `source_type` | `USER_INPUT \| EXPERT_CONFIRMATION \| REVIEWED_WIKI \| OFFICIAL_DOCUMENT \| OFFICIAL_API \| CALCULATION_RESULT \| SYSTEM_RECORD` | producer가 실제 원천 종류를 허용 enum으로 기록 |
| `source_ref` | non-empty string | 원본 입력 event, 공식 URL, API 공고 ID 등 원천 식별자 |
| `source_version` | non-empty string \| null | 원천의 개정·catalog·API version; 확인할 수 없으면 null |
| `locator` | non-empty string | 원문에서 excerpt를 다시 찾을 수 있는 span, 문서 위치 또는 API 경로 |
| `excerpt` | non-empty string | 해당 판단에 실제 사용한 최소 근거 구간 |
| `parent_evidence_refs` | string[] (각 요소 non-empty) | 검수 Wiki·가공 결과가 어느 원본 Evidence에서 왔는지 나타내는 lineage |
| `published_at` | aware datetime \| null | 원천 게시 시각; producer가 확인하지 못하면 null |
| `retrieved_at` | aware runtime datetime | producer가 입력·원문을 읽은 시각 |
| `freshness_status` | `CURRENT \| STALE \| UNKNOWN` | producer 또는 검수 catalog가 판정한 최신성 상태 |
| `content_hash` | `sha256:<64-hex>` \| null | 원문 내용 변경 검출용 hash; 계산할 수 없는 source는 null |

하나의 Evidence는 자기 자신을 parent로 가리킬 수 없고 parent 목록은 중복될 수 없다. 각 결과 producer는 자신이 반환한 참조의 closure를 더 강하게 검사한다. 검색 provider의 title/snippet은 이 타입으로 승격되지 않으며, 절차조회 Tool이 직접 fetch한 공식 원문만 해당 Tool의 `OFFICIAL_DOCUMENT`가 된다.

### 4.3 현재 사용: 안정 참조

| 모델 | 필드 | 식별 의미 |
|---|---|---|
| `ProcedureStepRef` | `procedure_step_id: positive int`, `step_code: UpperSnakeCode` | caller가 공급한 canonical 절차 참조 |
| `SupportProgramRef` | `support_program_id: positive int`, `wiki_uuid: UUID` | 검수 catalog 안 지원사업 참조 |
| `KnownProcedureStep` | `procedure_step`, `step_name`, `utterance_aliases[]` | Info가 발화·문서를 기존 절차에 연결할 때만 사용 |

인터넷 문서 제목·URL 또는 LLM 문자열은 새 `procedure_step_id`, `step_code`, `support_program_id`, `wiki_uuid`를 만들 수 없다.

### 4.4 현재 사용: Case fact registry

| `field_path` | `value_type` | 허용값/제약 |
|---|---|---|
| `business_type` | `STRING` | 길이 1 이상 string |
| `franchise_status` | `BOOLEAN` | strict boolean |
| `employee_count` | `INTEGER` | strict integer `>= 0`, boolean 금지 |
| `lease_status` | `ENUM` | `ACTIVE \| TERMINATION_NOTIFIED \| TERMINATED \| OWNED` |
| `entity_type` | `ENUM` | `SOLE_PROPRIETOR \| CORPORATION` |
| `building_use_type` | `ENUM` | `NEIGHBORHOOD_LIVING \| OTHER` |
| `previous_support_history` | `ENUM` | `NONE \| RECEIVED` |
| `restoration_status` | `ENUM` | `NOT_STARTED \| IN_PROGRESS \| COMPLETED` |
| `restoration_scope` | `ENUM` | `AGREEMENT_REQUIRED \| TENANT_ALL \| LANDLORD_ALL \| SHARED \| NOT_REQUIRED` |
| `restoration_scope_detail` | `STRING` | 길이 1 이상 string |
| `demolition_required` | `ENUM` | `REQUIRED \| NOT_REQUIRED` |
| `planned_closure_date` | `DATE` | 유효한 `YYYY-MM-DD` 또는 date |

`CaseFact`:

| 필드 | 타입 | 불변식 |
|---|---|---|
| `field_path` | `CaseFieldKey` | snapshot 안 unique |
| `value_type` | `STRING \| INTEGER \| BOOLEAN \| DATE \| ENUM` | registry와 일치 |
| `value` | `StrictScalar` | `UNKNOWN`이면 null |
| `status` | `CONFIRMED \| UNKNOWN` | 상태/value/evidence를 함께 검증 |
| `evidence_refs` | non-empty string[] | `CONFIRMED`이면 1개 이상, `UNKNOWN`이면 `[]` |
| `updated_at` | aware datetime \| null | 현재 상태의 갱신 시각 |

`CONFIRMED`는 non-null 값과 Evidence가 필요하고, `UNKNOWN`은 `value=null`, `evidence_refs=[]`여야 한다.

### 4.5 현재 사용: `CaseSnapshot`

현재 모델의 key는 아래 8개가 전부다.

| 필드 | 타입 | 의미·생성자 |
|---|---|---|
| `snapshot_id` | runtime UUID | caller가 한 번의 Case 읽기 상태를 식별하도록 생성 |
| `case_id` | positive strict integer | 이 snapshot이 설명하는 Case ID |
| `case_version` | positive strict integer \| null | caller가 알고 있는 동시성 version; standalone fixture는 null 가능 |
| `case_status` | `IN_PROGRESS \| COMPLETED` | snapshot을 만든 시점의 Case 상태 |
| `facts` | `CaseFact[]` | 해당 시점의 canonical Case 사실 목록 |
| `procedure_progress` | `ProcedureProgress[]` | 해당 시점의 canonical 절차별 현재 진행 상태 |
| `evidence_records` | `EvidenceRecord[]` | facts와 progress가 참조하는 snapshot 내부 근거 목록 |
| `captured_at` | aware runtime datetime | caller가 이 읽기 상태를 조립한 시각 |

`ProcedureProgress`는 다음 필드를 갖는다.

| 필드 | 타입 | 불변식 |
|---|---|---|
| `procedure_step` | `ProcedureStepRef` | snapshot 안 `procedure_step_id` unique |
| `status` | `NOT_STARTED \| IN_PROGRESS \| COMPLETED` | `COMPLETED`이면 Evidence 1개 이상 |
| `evidence_refs` | non-empty string[] | snapshot Evidence ID만 참조 |
| `updated_at` | aware datetime | 필수 |

Snapshot 전체에서 fact `field_path`, progress `procedure_step_id`, Evidence ID는 각각 unique다. fact/progress가 참조하는 모든 Evidence ID는 같은 `evidence_records` 안에서 해석되어야 한다. Graph는 실행 시작 시 deep copy와 digest를 만들고 종료 시 snapshot이 변하지 않았는지 다시 확인한다.

## 5. 절차조회 Tool

현재 연결 상태: `CASE_CREATED`, `RESULT_SUBMITTED` 실행 흐름에 연결됨.

### 5.1 역할과 호출 경계

Graph가 입력을 만들고 `ProcedureLookupTool.lookup()`이 raw 공식문서 결과를 반환한다. Tool은 다음을 반환하지 않는다.

- canonical 절차 단계 판단
- Case 적용 가능성 또는 완료 상태
- Blocker, Next Action, priority
- 사용자 Case 변경 후보

이 의미는 다음 단계의 정보분석 Agent가 판단한다. 검색 provider·원문 수집 전략의 운영 내용은 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)에만 둔다.

### 5.2 입력 `ProcedureLookupInput`

`AgentGraph`가 이 model 하나를 만들어 `lookup(request)`에 전달한다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `lookup_goal` | literal `BUSINESS_CLOSURE` | Graph가 폐업 절차 조회 목적을 고정 | 다른 목적 문자열 거부 |
| `search_queries` | string[] `1..4` | Graph가 raw 사용자 문장 대신 canonical fact와 안전한 고정 문구로 생성 | trim 후 빈 값·중복 금지; Tool에서 각 200자 이하, ASCII U+0000–U+001F와 민감정보 금지 추가 검사 |
| `as_of` | date | 자연어 trigger는 `submitted_at.date()`, refresh는 trigger `as_of`; 결과 provenance에 복사 | 유효한 date 필수; 현재 검색 필터·freshness 계산에는 미사용 |
| `locale` | literal `ko-KR` | Graph 고정 | 다른 locale 거부 |
| `source_policy` | literal `OFFICIAL_ONLY` | Graph 고정 | 검증된 공식 domain 이외 출처 사용 금지 |
| `max_results_per_query` | strict integer `1..10` | Graph는 5 생성 | boolean·문자열 숫자·범위 밖 값 거부 |
| `based_on_snapshot_id` | runtime UUID | Graph가 `AgentGraphInput.case_snapshot.snapshot_id`를 복사 | UUID 형식 필수; 결과가 동일 ID를 반환해야 함 |
| `review_feedback` | `ReviewIssue[]` | Graph가 최초 `[]`, 재작업 시 직전 Review 문제를 전달 | 선언되지 않은 issue 필드 거부; 현재 query·조회 동작에는 미사용 |

Graph는 raw 사용자 문장을 query에 복사하지 않는다. 확인된 Case fact와 제한된 키워드가 미리 정의된 정적 query를 선택하게 하고, 중복 제거 후 최대 4개로 자른다.

### 5.3 출력 `ProcedureLookupResult`

`ProcedureLookupTool`이 provider 조회와 공식 원문 fetch를 마친 뒤 이 model 하나를 반환한다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `completion_status` | `COMPLETE \| PARTIAL \| NO_RESULTS` | Tool이 query/fetch 집계로 계산 | 문서·실패 개수와 §5.4 상태 규칙이 일치해야 함 |
| `lookup_id` | runtime UUID | Tool runtime이 조회마다 새로 생성 | UUID 형식 필수 |
| `documents` | `ProcedureSourceDocument[]` | Tool이 허용 domain에서 직접 fetch하고 정규화한 공식 원문 | document ID·URL unique, 모든 문서에 대응 Evidence 필요 |
| `search_summary` | `ProcedureSearchSummary` | Tool이 provider별 시도·성공·실패·fetch 수를 집계 | provider 순서와 모든 count 관계 검증 |
| `warnings` | `ProcedureLookupWarning[]` | 일부 provider/fetch 실패 등 비치명 상태를 Tool이 기록 | code는 upper snake, message는 non-empty |
| `evidence_records` | `EvidenceRecord[]` | Tool이 각 fetched 문서마다 생성 | 문서와 1:1, `OFFICIAL_DOCUMENT`, URL·excerpt·hash·시각 일치 |
| `based_on_snapshot_id` | runtime UUID | Tool이 요청값을 그대로 복사 | 입력 `based_on_snapshot_id`와 같아야 함 |
| `as_of` | date | Tool이 요청값을 그대로 복사 | 입력 `as_of`와 같아야 함 |

`ProcedureSourceDocument`:

| 필드 | 타입/의미 |
|---|---|
| `document_id` | runtime UUID, result 안 unique |
| `title` | non-empty string |
| `authority_name` | 검증된 domain의 기관 표시명 |
| `canonical_url` | absolute HTTPS URL, credential/fragment/명시 port/IP literal 금지 |
| `source_domain` | canonical URL과 같은 lowercase hostname |
| `excerpt` | string `1..6000`; 현재 producer는 최대 4000자 |
| `published_at` | aware datetime \| null; 현재 producer는 null |
| `retrieved_at` | aware runtime datetime |
| `freshness_status` | `CURRENT \| STALE \| UNKNOWN`; 현재 producer는 `UNKNOWN` |
| `content_hash` | fetch body의 SHA-256 digest |
| `evidence_ref` | 같은 결과의 Evidence ID |
| `search_query` | 이 URL을 찾은 입력 query |
| `discovery_provider` | `OFFICIAL_SOURCE_REGISTRY \| KAKAO_DAUM_WEB \| GOOGLE_AGENT_SEARCH` |

`ProcedureProviderSearchSummary`:

| 필드 | 타입 |
|---|---|
| `provider` | `ProcedureSearchProvider` |
| `attempted_query_count` | non-negative strict integer |
| `successful_query_count` | non-negative strict integer |
| `failed_query_count` | non-negative strict integer |
| `provider_result_count` | non-negative strict integer |

`successful_query_count + failed_query_count == attempted_query_count`다. 성공 query가 0개이면 provider result도 0개여야 한다.

`ProcedureSearchSummary`:

| 필드 | 타입 |
|---|---|
| `provider_order` | `ProcedureSearchProvider[]`, `1..3` |
| `provider_summaries` | `ProcedureProviderSearchSummary[]`, `1..3` |
| `fallback_query_count` | non-negative strict integer |
| `requested_query_count` | positive strict integer |
| `successful_query_count` | non-negative strict integer |
| `failed_query_count` | non-negative strict integer |
| `provider_result_count` | non-negative strict integer |
| `official_candidate_count` | non-negative strict integer |
| `fetched_document_count` | non-negative strict integer |
| `rejected_result_count` | non-negative strict integer |
| `fetch_failure_count` | non-negative strict integer |
| `searched_at` | aware runtime datetime |

Provider 순서는 구성된 provider만 포함하면서 `OFFICIAL_SOURCE_REGISTRY → KAKAO_DAUM_WEB → GOOGLE_AGENT_SEARCH` 상대 순서를 보존한다. registry를 사용하지 않을 때는 Kakao 또는 Google부터 시작할 수 있다. `provider_summaries`는 `provider_order`와 같은 순서·길이다.

주요 집계 불변식:

- `successful_query_count + failed_query_count == requested_query_count`
- 첫 provider는 모든 query를 시도한다.
- 뒤 provider의 attempt 수는 앞 provider보다 많을 수 없다.
- `fallback_query_count`는 두 번째 provider attempt 수와 같다.
- provider별 result 합은 전체 `provider_result_count`와 같다.
- `official_candidate_count + rejected_result_count == provider_result_count`
- `fetched_document_count + fetch_failure_count <= official_candidate_count`
- provider-level 정상 응답이 최소 하나 있어야 결과 객체를 만든다.

`ProcedureLookupWarning`은 `code: UpperSnakeCode`, `message: non-empty string`만 갖는다.

### 5.4 결과/Evidence/상태 불변식

- document ID와 canonical URL은 각각 unique다.
- `fetched_document_count == len(documents)`다.
- `len(documents) == len(evidence_records)`이며 각 document에 정확히 하나의 Evidence가 대응한다.
- 대응 Evidence는 `OFFICIAL_DOCUMENT`, 같은 URL/excerpt/published/retrieved/freshness/hash를 가져야 한다.
- document의 `discovery_provider`에는 실제 성공한 provider 응답과 결과가 있어야 한다.
- `COMPLETE`: document가 1개 이상이고 query/fetch 실패가 없다.
- `NO_RESULTS`: document·실패·공식 후보가 모두 0인 정상 조회다.
- `PARTIAL`: query 또는 fetch 실패가 최소 하나 있다.
- 모든 provider가 기술적으로 실패하면 결과가 아니라 `ProcedureLookupRequestError`를 던진다.

근거: [`procedure_tool/tool.py`](../backend/app/agent/procedure_tool/tool.py), [`procedure_tool/models.py`](../backend/app/agent/procedure_tool/models.py), [`test_procedure_tool.py`](../backend/tests/agent/test_procedure_tool.py).

## 6. 정보분석 Agent

현재 연결 상태: `CASE_CREATED`, `RESULT_SUBMITTED` 실행 흐름에 연결됨.

역할: 비식별 입력과 `CaseSnapshot`, 절차조회 Tool이 가져온 공식 원문을 함께 해석한다. 출력은 사실 변경·절차 진행·충돌·추가 질문의 **후보**이며, Case 저장이나 실제 절차 완료 처리가 아니다.

### 6.1 입력 `InfoAnalysisInput`

`AgentGraph`가 이 model 하나를 만들어 `analyze(request)`에 전달한다. Info 호출 ID도 model 내부 필드이므로 별도 keyword 인자는 없다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `input` | `RedactedInput` | Graph가 `CASE_CREATED`/`RESULT_SUBMITTED` trigger의 비식별 입력을 복사 | event ID·redaction span 무결성 검증 |
| `case_snapshot` | `CaseSnapshot` | Graph가 `AgentGraphInput.case_snapshot`을 전달 | snapshot 내부 unique·Evidence closure 검증; Tool 결과 snapshot과 일치해야 함 |
| `allowed_field_paths` | unique `CaseFieldKey[]`, min 1 | Graph가 전체 `CASE_FIELD_SPECS` key를 제공 | 빈 목록·중복·registry 밖 값 거부 |
| `known_procedure_steps` | `KnownProcedureStep[]` | Graph constructor에 주입된 canonical step 목록 | step ID·code·정규화 name·모든 alias가 전체 목록에서 unique |
| `source_call_id` | runtime UUID | Graph가 이번 Info `InvocationMeta.call_id`를 복사 | UUID 형식 필수; conflict·mutation provenance에 그대로 사용 |
| `procedure_lookup_call_id` | runtime UUID | Graph가 직전 Procedure `InvocationMeta.call_id`를 복사 | UUID 형식 필수; 결과 provenance와 Review source에서 다시 대조 |
| `procedure_lookup_result` | `ProcedureLookupResult` | Graph가 직전 Tool 출력을 전달 | `based_on_snapshot_id`가 입력 snapshot ID와 같아야 함 |
| `review_feedback` | `ReviewIssue[]` | Graph가 최초 `[]`, 재작업 시 직전 Review 문제를 전달 | issue schema 검증; 재작업이 아니면 빈 목록 |

입력 불변식:

- `procedure_lookup_result.based_on_snapshot_id == case_snapshot.snapshot_id`
- allowed field는 unique다.
- known step의 `procedure_step_id`, `step_code`, 정규화한 `step_name`은 각각 unique다.
- 모든 step name과 alias를 casefold/trim한 표현도 전체 목록에서 unique다.
- 같은 run에서 Graph가 보관한 Procedure call ID와 결과 digest는 이후 Supervisor/Review에서 다시 결합한다.

### 6.2 출력 `InfoAnalysisResult`

`InfoAnalysisAgent`가 provider 의미 후보를 local guardrail로 검증하고 runtime provenance를 결합해 이 model 하나를 반환한다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `completion_status` | `COMPLETE \| NEEDS_USER_INPUT \| PARTIAL` | Agent runtime이 검증된 분석 상태를 확정 | `NEEDS_USER_INPUT`이면 missing field와 question이 모두 필요 |
| `fact_candidates` | `FactCandidate[]` | provider 사실 후보를 runtime이 registry·exact span·Evidence와 결합 | candidate ID unique, field/type/value·SET/CLEAR 일치, Evidence closure 필요 |
| `procedure_progress_observations` | `ProcedureProgressObservation[]` | 사용자 문장의 실제 수행 관측을 runtime이 canonical step에 결합 | observation ID unique, known step·exact span·Evidence 필요; 웹 Evidence만으로 생성 금지 |
| `procedure_findings` | `ProcedureFinding[]` | 공식 절차 원문의 의미를 Agent가 canonical step에 연결 | finding ID·step unique, Evidence freshness·본문 포함·source call 규칙 검증 |
| `conflicts` | `ConflictCandidate[]` | 현재 confirmed fact와 다른 명시적 입력을 Agent가 분리 | ref·candidate ID unique, snapshot/version/call ID·digest 무결성 검증 |
| `missing_fields` | `MissingField[]` | downstream 결정을 막는 unknown fact를 Agent가 표시 | field unique; `NEEDS_USER_INPUT`이면 최소 1개와 연결 question 필요 |
| `uncertainties` | `Uncertainty[]` | 모호성·낮은 신뢰·source 한계를 Agent가 보존 | enum code, JSON Pointer, Evidence ref 검증 |
| `question_candidates` | `QuestionCandidate[]` | missing fact 해소 질문을 runtime이 생성 | question ID unique, 최소 한 field를 해소해야 함 |
| `evidence_records` | `EvidenceRecord[]` | runtime이 사용자·전문가 입력의 exact span Evidence를 생성 | Evidence ID unique; fact/progress 참조는 이 목록에서, procedure finding·uncertainty의 공식 ref는 같은 Review package의 `ProcedureLookupResult`에서 해석 |
| `parser_version` | runtime-injected non-empty string | Agent 설정의 deterministic parser/guardrail version | 빈 값 금지; provider 생성 금지 |
| `based_on_snapshot_id` | runtime UUID | Agent가 입력 snapshot ID를 복사 | 입력 snapshot과 같아야 함 |
| `based_on_procedure_lookup_call_id` | runtime UUID | Agent가 입력 Procedure call ID를 복사 | 입력 call ID와 같아야 함 |
| `based_on_procedure_lookup_digest` | digest | Agent가 입력 Procedure 결과의 canonical digest를 계산 | 실제 입력 결과 digest와 같아야 함 |

`NEEDS_USER_INPUT`이면 `missing_fields`와 `question_candidates`가 모두 1개 이상이어야 한다. candidate ID, observation ID, finding step/ID, question ID, Evidence ID는 각 범위에서 unique다. fact와 progress observation의 Evidence 참조는 이 결과의 `evidence_records`에서 해석되어야 한다.

### 6.3 사실·진행·질문 후보

`FactCandidate`:

| 필드 | 타입 |
|---|---|
| `candidate_id` | runtime UUID |
| `operation` | `SET \| CLEAR` |
| `field_path` | `CaseFieldKey` |
| `value_type` | `FactValueType` |
| `value` | `StrictScalar`; SET은 non-null, CLEAR는 null |
| `source_span` | `VerifiedTextSpan` |
| `source_evidence_refs` | string[] min 1 |
| `confidence_bps` | strict integer `0..10000` |
| `requires_confirmation` | strict boolean |
| `reason_summary` | non-empty string |

field/type/value는 §4.4 registry와 맞아야 한다. 같은 값의 재진술은 생략한다. 이미 `UNKNOWN`인 값을 다시 CLEAR하는 출력도 생략한다. 기존 `CONFIRMED` 값과 다른 SET/CLEAR는 일반 fact candidate가 아니라 `ConflictCandidate`로 분리한다.

`ProcedureProgressObservation`:

| 필드 | 타입 |
|---|---|
| `observation_id` | runtime UUID |
| `procedure_step` | 입력 known step의 `ProcedureStepRef` |
| `observed_status` | `IN_PROGRESS \| COMPLETED` |
| `source_span` | `VerifiedTextSpan` |
| `source_evidence_refs` | string[] min 1 |
| `requires_confirmation` | strict boolean |
| `reason_summary` | non-empty string |

step 이름/alias와 상태 표현이 같은 사용자 exact span에 명시돼야 한다. 부정형은 진행 또는 완료 관측으로 인정하지 않는다. 웹문서는 실제 수행 관측의 source가 될 수 없다.

`MissingField`:

| 필드 | 타입 |
|---|---|
| `field_path` | `CaseFieldKey` |
| `reason_summary` | non-empty string |
| `blocks` | `PROCEDURE_LOOKUP \| SUPPORT_ANALYSIS \| SUPERVISOR_DECISION` 목록, min 1 |
| `question_candidate_id` | runtime UUID \| null |

`QuestionCandidate`은 `question_id`, `text`, `resolves_field_paths`(min 1), `reason_summary`를 갖는다. `MissingFieldDraft` 하나를 runtime이 같은 question ID로 두 객체에 결합한다.

`Uncertainty`:

| 필드 | 타입 |
|---|---|
| `code` | `AMBIGUOUS_INPUT \| LOW_CONFIDENCE \| CONTEXT_MISSING \| SOURCE_STALE \| SOURCE_UNAVAILABLE` |
| `target_path` | `JsonPointer` |
| `reason_summary` | non-empty string |
| `evidence_refs` | string[] |

### 6.4 `ProcedureFinding`

절차조회 raw document를 정보분석 Agent가 입력 known step에 결합한 결과다.

| 필드 | 타입/불변식 |
|---|---|
| `finding_id` | runtime UUID, result 안 unique |
| `procedure_step` | 입력 known step 중 하나 |
| `step_name` | 같은 `KnownProcedureStep.step_name` |
| `summary` | `SourcedText` |
| `relevance` | `RELEVANT \| POSSIBLY_RELEVANT \| UNDETERMINED` |
| `current_status` | `NOT_STARTED \| IN_PROGRESS \| COMPLETED \| null`; snapshot에서 복사 |
| `decision_authority` | `USER \| LANDLORD \| OFFICIAL_AGENCY \| PROFESSIONAL \| UNKNOWN` |
| `requires_confirmation` | literal `true` |
| `required_actions` | `SourcedText[]` |
| `required_documents` | `RequiredDocument[]` |
| `application_channel` | `SourcedText \| null` |
| `application_url` | `SourcedText \| null` |
| `deadline` | `SourcedText \| null` |
| `evidence_refs` | string[] min 1; 모든 상세 ref의 집합과 같음 |

`SourcedText`는 `text`, `evidence_refs`(min 1)를 갖는다. `RequiredDocument`는 `name`, `submission_stage: string | null`, `evidence_refs`(min 1)를 갖는다.

Finding 불변식:

- 한 canonical step에는 최대 한 finding만 허용한다.
- 모든 Evidence는 입력 `ProcedureLookupResult.evidence_records`에서 해석된다.
- query가 후보 step을 제한한 Evidence는 다른 step에 붙일 수 없다.
- `UNKNOWN` 또는 `STALE` Evidence가 하나라도 있으면 relevance는 `UNDETERMINED`만 허용한다.
- summary는 보수적 요약일 수 있다.
- action/channel/deadline과 문서명·제출시점은 인용 excerpt에 실제 존재할 때만 유지한다.
- application URL은 인용 Evidence의 fetched canonical source URL과 같을 때만 유지한다.
- 웹 Evidence는 `current_status`를 변경하지 않는다.

### 6.5 `ConflictCandidate`

Info Agent가 현재 확정 fact와 다른 명시적 입력을 발견하면 만든다.

| 필드 | 타입 |
|---|---|
| `conflict_ref` | non-empty string; standalone producer는 `standalone:<24-hex>` |
| `conflict_digest` | digest |
| `candidate_id` | runtime UUID |
| `snapshot_id` | runtime UUID |
| `case_version` | positive strict integer \| null |
| `field_path` | `CaseFieldKey` |
| `committed_status` | literal `CONFIRMED` |
| `committed_value` | `NonNullStrictScalar` |
| `proposed_operation` | `SET \| CLEAR` |
| `proposed_status` | SET이면 `CONFIRMED`, CLEAR이면 `UNKNOWN` |
| `proposed_value` | SET이면 non-null, CLEAR이면 null |
| `source_evidence_refs` | string[] min 1 |
| `source_call_id` | runtime UUID |

`conflict_digest`는 `conflict_ref`와 digest 자체를 제외한 전체 충돌 내용을 canonical digest로 묶는다. standalone ref의 24자리 suffix도 digest prefix에서 만든다. 내용이 바뀌면 직렬화도 실패한다.

### 6.6 provider → local → runtime 경계

| 층 | 모델 | top-level key | 생성 권한 |
|---|---|---|---|
| provider 응답 형식 | `InfoProviderOutput` | `completion_status`, `facts`, `procedure_observations`, `procedure_findings`, `missing_fields`, `uncertainties` | 의미 후보만 반환 |
| local 검증 결과 | `InfoAnalysisDraft` | provider와 같음 | registry, SET/CLEAR, completion 의미 검증 |
| 공개 runtime 출력 | `InfoAnalysisResult` | §6.2의 13개 key | ID, span, Evidence, parser version, snapshot/call/digest 주입 |

Provider nested 모델:

- `ExtractedFactModelOutput`: `operation`, `field_path`, `value_type`, `value`, `source_text`, `confidence_bps`, `requires_confirmation`, `reason_summary`
- `ProcedureObservationDraft`: `step_code`, `observed_status`, `source_text`, `requires_confirmation`, `reason_summary`
- `ProcedureFindingDraft`: `step_code`, `summary`, `relevance`, `decision_authority`, `requires_confirmation=true`, `required_actions`, `required_documents`, `application_channel`, `application_url`, `deadline`, `evidence_refs`
- `MissingFieldDraft`: `field_path`, `reason_summary`, `blocks`, `question`

LLM은 새 runtime UUID, offset, Evidence ID, digest를 생성하지 않는다. fact와 progress 관측의 `source_text`는 redacted input의 exact substring이어야 하고 runtime이 span과 `USER_INPUT`/`EXPERT_CONFIRMATION` Evidence를 생성한다. procedure finding과 uncertainty에서는 입력으로 제공된 공식 Evidence ID를 선택할 수 있지만, runtime이 allowlist와 provenance를 다시 검증한다. 모델 결과는 최초 포함 최대 1~3회(`max_local_attempts`)만 의미 검증을 반복한다. 소진 시 `InfoAnalysisGuardrailError`를 던진다.

근거: [`info_agent/agent.py`](../backend/app/agent/info_agent/agent.py), [`enrichment.py`](../backend/app/agent/enrichment.py), [`test_info_agent.py`](../backend/tests/agent/test_info_agent.py).

## 7. 지원금 Agent

현재 연결 상태: `DISCOVER_RELEVANT`, `REFRESH_STALE` 입력은 연결됨. `CHECK_SPECIFIC` 입력은 구현·테스트됐지만 현재 실행 흐름에는 연결되지 않음.

역할: Case의 확인된 사실과 미저장 fact 후보를 `ReviewedSupportCatalog`의 조건에 대조한다. 인터넷 raw 공고를 직접 읽지 않고, 지원 자격·선정·수급을 확정하지 않으며, Case나 catalog를 수정하지 않는다.

### 7.1 생성자 dependency `ReviewedSupportCatalog` — 직접 입출력 아님

`SupportAgent`는 생성 시 검수 catalog를 deep copy한다. catalog 모델 자체는 frozen outer model과 tuple collection으로 **얕은 불변**을 제공하지만 nested `AgentSchema`까지 재귀적으로 frozen인 것은 아니다. `catalog=null`이면 분석하지 않고 `SupportCatalogUnavailableError`를 던진다. 아래 catalog는 BizInfo discovery 결과와 다른 계약이다.

`ReviewedSupportCatalog`:

| 필드 | 타입 |
|---|---|
| `catalog_version` | non-empty string |
| `programs` | frozen model의 `tuple[ReviewedSupportProgram, ...]` |
| `evidence_records` | frozen model의 `tuple[EvidenceRecord, ...]` |

`ReviewedSupportProgram`:

| 필드 | 타입 |
|---|---|
| `support_program` | `SupportProgramRef` |
| `program_name` | non-empty string |
| `related_steps` | `tuple[ProcedureStepRef, ...]` |
| `criteria` | `tuple[SupportCriterionDefinition, ...]`, min 1 |
| `required_documents` | `tuple[SupportRequiredDocumentDefinition, ...]` |
| `application_channel` | `CatalogSourcedText \| null` |
| `application_url` | `CatalogSourcedText \| null` |
| `application_period` | `CatalogSourcedText \| null` |
| `source_version` | non-empty string \| null |
| `freshness_status` | `CURRENT \| STALE \| UNKNOWN` |
| `evidence_refs` | `tuple[string, ...]`, min 1 |

`SupportCriterionDefinition`은 `criterion_code`, `field_path`, `operator`, `required_values`, `evidence_refs`를 갖는다. `operator`는 `EQ | IN | GT | GTE | LT | LTE`이고 `IN` 이외에는 required value가 정확히 하나여야 한다. `CatalogSourcedText`는 `text`, `evidence_refs`; `SupportRequiredDocumentDefinition`은 `name`, `submission_stage`, `evidence_refs`를 갖는다.

Catalog 불변식:

- program ID와 wiki UUID는 각각 unique다.
- 한 program 안 criterion code와 related step `(id, code)`는 unique다.
- 모든 참조 Evidence와 parent Evidence는 catalog 안에서 해석된다.
- claim Evidence source는 `REVIEWED_WIKI | OFFICIAL_DOCUMENT | OFFICIAL_API`만 허용한다.
- `REVIEWED_WIKI` Evidence에는 직접 `OFFICIAL_DOCUMENT` 또는 `OFFICIAL_API` parent가 최소 하나 있어야 한다.

### 7.2 입력에 포함되는 공통 context `PlanningContext`

| 필드 | 타입 | 불변식 |
|---|---|---|
| `case_snapshot` | `CaseSnapshot` | 모델 자체가 frozen인 것은 아니며, Graph가 deep copy와 시작·종료 digest 비교로 논리적 read-only를 강제 |
| `fact_overlays` | `FactChangeCandidate[]` | candidate ID와 field path가 각각 unique |

Overlay는 아직 저장되지 않은 fact 변경 후보다. 지원금 Agent는 snapshot을 바꾸지 않고 overlay를 적용한 view로 criterion을 비교한다.

### 7.3 입력 `SupportAgentInput`

`SupportAgentInput`은 `lookup_goal` discriminator를 쓰는 세 request schema의 union이다. `AgentGraph`는 선택한 variant 객체 하나를 `analyze(request)`에 전달한다. 생성자에 주입되는 `ReviewedSupportCatalog`는 이 호출별 입력 schema에 포함되지 않는다.

| 상태 | 입력 variant | 목적·producer | variant 검증 |
|---|---|---|---|
| 현재 실행 흐름에 연결됨 | `DiscoverSupportInput` | 일반 Graph 흐름이 검수 catalog에서 관련 program을 탐색할 때 생성 | `lookup_goal=DISCOVER_RELEVANT`; 공통 필드만 허용 |
| 구현됨 · 실행 흐름 미연결 | `CheckSpecificSupportInput` | 명시한 검수 program만 비교하는 직접 호출용 입력; 현재 실행기는 생성하지 않음 | `lookup_goal=CHECK_SPECIFIC`; `support_programs` min 1 필수 |
| 현재 실행 흐름에 연결됨 | `RefreshSupportInput` | `SUPPORT_REFRESH` Graph 흐름이 주입된 catalog의 지정 program을 재평가할 때 생성 | `lookup_goal=REFRESH_STALE`; `support_programs` min 1 필수 |

공통 필드:

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `lookup_goal` | 위 variant별 literal | Graph 또는 독립 caller가 분석 mode를 선택 | discriminator와 실제 variant 필드가 일치해야 함 |
| `planning_context` | `PlanningContext` | Graph가 기준 snapshot과 검수 전 fact overlay를 묶어 생성 | snapshot schema, candidate ID·field path unique |
| `related_steps` | `ProcedureStepRef[]` | Graph가 관련 Info finding의 canonical step을 전달 | 각 stable ID/code schema 검증; 빈 목록 허용 |
| `as_of` | date | Graph가 자연어 trigger 날짜 또는 refresh 기준일을 전달 | 유효한 date 필수; 현재 prompt·freshness 계산에는 미사용 |
| `review_feedback` | `ReviewIssue[]` | Graph가 최초 `[]`, 재작업 시 직전 Review 문제를 전달 | issue schema 검증 |
| `support_programs` | `SupportProgramRef[]`, min 1 | `CHECK_SPECIFIC`/`REFRESH_STALE` caller가 지정 | 두 variant에서만 존재·필수; program ID/wiki UUID 형식 검증 |

Graph는 일반 trigger에서 `DiscoverSupportInput`, `SUPPORT_REFRESH`에서 `RefreshSupportInput`만 만든다. 일반 흐름의 `related_steps`는 Info finding 중 relevance가 `RELEVANT | POSSIBLY_RELEVANT`인 step이다. 현재 Tool이 생성하는 Evidence freshness는 `UNKNOWN`이므로 해당 finding은 보통 `UNDETERMINED`이고 관련 step 목록에서 제외될 수 있다. `DISCOVER_RELEVANT`에서 `related_steps=[]`이면 Support Agent는 reviewed catalog 전체 프로그램을 대상으로 선택하고, 값이 있으면 related-step 교집합이 있는 프로그램만 선택한다.

`as_of`는 Graph/schema에 전달되지만 현재 Support Agent의 prompt·freshness 계산에는 사용되지 않는다. `REFRESH_STALE`도 외부 API·crawler·RAG로 catalog를 갱신하는 동작이 아니라 **이미 주입된 같은 catalog에서 지정 program을 다시 평가**하는 경로다.

### 7.4 출력 `SupportAnalysisResult`

`SupportAgent`가 catalog, snapshot, overlay 비교를 검증하고 이 model 하나를 반환한다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `completion_status` | `COMPLETE \| NO_CANDIDATE \| PARTIAL` | Agent runtime이 선택 program과 source freshness로 계산 | check·reason·uncertainty 존재 조건과 일치해야 함 |
| `support_checks` | `SupportCheck[]` | Agent가 선택된 각 검수 program에 대해 하나씩 생성 | program ID unique; 선택 program 전체와 1:1; criterion·Evidence 일치 |
| `no_candidate_reason_code` | `UpperSnakeCode \| null` | 후보가 없을 때 runtime이 기계 판독 이유를 제공 | `NO_CANDIDATE`일 때만 non-null |
| `uncertainties` | `Uncertainty[]` | unknown fact와 stale/unknown source 한계를 Agent가 보존 | `PARTIAL`이면 최소 1개; path/ref schema 검증 |
| `search_summary` | `SupportSearchSummary` | runtime이 catalog/wiki/RAG/공식 출처 사용 사실을 기록 | 현재 `wiki_lookup=NOT_REQUESTED`, `rag_used=false`; 공식 source 여부는 Evidence로 계산 |
| `evidence_records` | `EvidenceRecord[]` | Agent가 선택 program의 검수 catalog 소유 Evidence와 parent closure를 복사 | catalog 소유 ref는 이 목록에서, Case snapshot·Info overlay ref는 같은 `ReviewSubject`의 snapshot·Info source와 합쳐 해석 |
| `based_on_snapshot_id` | runtime UUID | Agent가 `planning_context.case_snapshot.snapshot_id`를 복사 | 입력 snapshot과 같아야 함 |
| `based_on_candidate_ids` | runtime UUID[] unique | 실제 criterion 계산에 사용한 overlay ID만 runtime이 기록 | 입력 overlay의 부분집합, 중복 금지 |

`SupportCheck`:

| 필드 | 타입 |
|---|---|
| `support_program` | `SupportProgramRef` |
| `program_name` | non-empty string |
| `related_steps` | `ProcedureStepRef[]` |
| `match_status` | `POSSIBLY_RELEVANT \| NEEDS_CONFIRMATION \| NOT_RELEVANT \| STALE \| UNVERIFIABLE` |
| `criteria` | `SupportCriterionResult[]` |
| `unknown_field_paths` | unique `CaseFieldKey[]` |
| `required_documents` | `RequiredDocument[]` |
| `application_channel` | `SourcedText \| null` |
| `application_url` | `SourcedText \| null` |
| `application_period` | `SourcedText \| null` |
| `source_version` | non-empty string \| null |
| `freshness_status` | `CURRENT \| STALE \| UNKNOWN` |
| `checked_at` | aware runtime datetime |
| `reason_summary` | non-empty string |
| `evidence_refs` | string[] |

`SupportCriterionResult`:

| 필드 | 타입 |
|---|---|
| `criterion_code` | `UpperSnakeCode` |
| `case_value` | `StrictScalar` |
| `required_values` | `NonNullStrictScalar[]`, min 1 |
| `status` | `MET \| NOT_MET \| UNKNOWN` |
| `reason_summary` | non-empty string |
| `evidence_refs` | string[] min 1 |

`SupportSearchSummary`:

| 필드 | 타입 | 현재 `SupportAgent` producer 값 |
|---|---|---|
| `wiki_lookup` | `HIT \| MISS \| NOT_REQUESTED` | `NOT_REQUESTED` |
| `rag_used` | strict boolean | `false` |
| `official_source_checked` | strict boolean | 출력 Evidence에 공식 source가 있는지 계산 |
| `checked_at` | aware runtime datetime | runtime clock |

Completion·판정 불변식:

- `NO_CANDIDATE`: `support_checks=[]`, reason code non-null이다.
- `COMPLETE`: check 1개 이상, reason code null이다.
- `PARTIAL`: uncertainty 1개 이상, reason code null이다.
- criterion은 `case_value=null` iff status가 `UNKNOWN`이다.
- stale Evidence이면 match도 `STALE`; 반대도 성립한다.
- freshness가 `UNKNOWN`이면 match는 `UNVERIFIABLE`이다.
- positive match(`POSSIBLY_RELEVANT | NEEDS_CONFIRMATION`)는 CURRENT Evidence와 Evidence ref가 필요하다.
- `NOT_RELEVANT`는 CURRENT Evidence와 `NOT_MET` criterion이 최소 하나 필요하다.
- selected program 전부에 정확히 한 check를 반환하고 program ID는 중복될 수 없다.
- `based_on_candidate_ids`에는 실제 criterion 평가에 사용한 overlay ID만 넣는다.
- stale/unknown catalog Evidence는 runtime이 uncertainty를 추가하고 전체 completion을 `PARTIAL`로 낮춘다.

### 7.5 provider → local → runtime 경계

| 층 | 모델 | top-level key | 생성 권한 |
|---|---|---|---|
| provider 응답 형식 | `SupportProviderOutput` | `completion_status`, `support_checks`, `no_candidate_reason_code`, `uncertainties` | 의미 후보만 반환 |
| local 검증 결과 | `SupportAnalysisDraft` | provider와 같음 | completion, program/criterion 중복 검증 |
| 공개 runtime 출력 | `SupportAnalysisResult` | §7.4의 8개 key | catalog 값, case/required 값, freshness, 시각, Evidence, provenance 주입 |

Provider `SupportCheckModelOutput`은 `support_program`, `match_status`, `criteria`, `unknown_field_paths`, `reason_summary`, `evidence_refs`만 갖는다. nested criterion은 `criterion_code`, `status`, `reason_summary`, `evidence_refs`만 갖는다. program 표시명·신청 정보·case value·required value·freshness·checked time은 모델이 만들지 않는다.

Catalog에서 대상 program이 없으면 LLM을 호출하지 않고 runtime이 `NO_CANDIDATE/NO_REVIEWED_CATALOG_MATCH`를 만든다. 대상이 있으면 provider 출력 검증은 최초 포함 최대 3회다. 근거 밖 ID, criterion 비교와 다른 status, 과신 자격 문구, 민감정보가 있으면 `SupportAnalysisGuardrailError`다.

근거: [`support_agent/agent.py`](../backend/app/agent/support_agent/agent.py), [`support_agent/models.py`](../backend/app/agent/support_agent/models.py), [`test_support_agent.py`](../backend/tests/agent/test_support_agent.py).

## 8. 기업마당 지원 공고조회 Tool

현재 연결 상태: 구현과 단위 테스트는 완료됐지만 현재 app/LangGraph 실행 흐름과 검수 catalog 발행 경로에는 연결되지 않음.

역할: 기업마당 공고를 **검수 전 raw candidate**와 공식 API Evidence로 정규화한다. 지원 자격을 판정하지 않으며 `ReviewedSupportCatalog`로 승격하지 않는다. 현재 Graph와 `SupportAgent` constructor 사이에도 자동 연결이 없다.

### 8.1 입력 `SupportNoticeDiscoveryInput`

독립 caller가 이 model 하나를 만들어 `discover(request)`에 전달한다. 현재 `AgentGraph` producer는 없다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `keywords` | immutable string tuple, `1..8` | 독립 caller가 기업마당 공고 검색어를 제공 | 항목 `1..80`자, trim, case-insensitive unique, comma·ASCII U+0000–U+001F/U+007F·민감정보 금지 |
| `max_results` | strict integer `1..100` | caller가 반환 상한을 지정; 기본 20 | boolean·문자열 숫자·범위 밖 값 거부 |

### 8.2 출력 `SupportNoticeDiscoveryResult`

adapter가 기업마당 API 응답을 정규화하고 이 model 하나를 반환한다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `provider` | literal `BIZINFO` | adapter가 source provider를 고정 | 다른 값 거부 |
| `keywords` | 검증된 input tuple | adapter가 요청 검색어를 복사 | 입력과 동일해야 함 |
| `applied_result_limit` | strict integer `1..100` | adapter가 실제 적용한 요청 상한을 기록 | 입력 `max_results`와 adapter 설정 `max_results` 중 작은 값과 일치 |
| `provider_total_count` | non-negative integer \| null | API가 제공한 전체 건수 또는 미제공 상태 | 반환 0건 iff null; 제공 시 반환 수 이상 |
| `provider_returned_count` | non-negative integer | adapter가 받은 raw item 수를 기록 | candidate·중복·limit 집계와 일치 |
| `duplicate_count` | non-negative integer | adapter가 notice ID 중복 제거 수를 계산 | 반환 수보다 클 수 없음 |
| `result_count` | non-negative integer | adapter가 최종 unique candidate 수를 계산 | `len(candidates)` 및 §8.3 공식과 일치 |
| `truncated` | strict boolean | 전체/unique 후보가 적용 상한을 넘었는지 adapter가 계산 | 실제 누락 후보가 있을 때만 true |
| `retrieved_at` | aware datetime | adapter runtime clock | timezone 필수; 모든 Evidence와 동일 시각 |
| `candidates` | immutable `SupportNoticeCandidate[]`, max 100 | adapter가 raw 공고를 안전한 필드로 정규화 | notice ID unique, URL/domain·첨부 pair·count 검증 |
| `evidence_records` | frozen result의 `tuple[EvidenceRecord, ...]`, max 100 | adapter가 candidate마다 `OFFICIAL_API` Evidence 생성 | candidate와 1:1, ID·hash·locator·시각 일치; nested model은 재귀적 frozen 아님 |

`SupportNoticeCandidate`의 선언 필드 전체:

| 필드 | 타입/의미 |
|---|---|
| `provider` | literal `BIZINFO` |
| `notice_id` | `PBLN_...` 형식의 외부 공고 ID |
| `title` | non-empty normalized text |
| `detail_url` | 해당 notice ID를 가리키는 기업마당 HTTPS 상세 URL |
| `summary` | text \| null |
| `target` | text \| null |
| `application_period` | text \| null |
| `application_method` | text \| null |
| `application_url` | 검증된 web URL \| null |
| `jurisdiction_institution` | text \| null |
| `executing_institution` | text \| null |
| `support_area_major` | text \| null |
| `support_area_middle` | text \| null |
| `reference_contact` | text \| null |
| `hashtags` | unique immutable text tuple |
| `attachment_name` | text \| null |
| `attachment_url` | 기업마당 HTTPS URL \| null |
| `print_attachment_name` | text \| null |
| `print_attachment_url` | 기업마당 HTTPS URL \| null |
| `provider_created_at` | aware datetime \| null |
| `provider_updated_at` | aware datetime \| null |
| `view_count` | non-negative integer |
| `freshness_status` | literal 의미상 `UNKNOWN`만 허용 |
| `evidence_ref` | 같은 result의 Evidence ID |

첨부 이름/URL은 쌍으로 함께 존재하거나 함께 null이어야 한다. application URL은 metadata일 뿐 adapter가 후속 fetch하지 않는다.

### 8.3 결과 무결성

- `result_count == len(candidates)`
- Evidence 수는 candidate 수와 같다.
- `result_count == min(provider_returned_count - duplicate_count, applied_result_limit)`
- `provider_returned_count == 0` iff `provider_total_count == null`
- total이 있으면 반환 수보다 작을 수 없다.
- notice ID와 Evidence ID는 각각 unique하고 candidate ref와 Evidence ID 집합은 1:1이다.
- 각 Evidence는 `OFFICIAL_API`, freshness `UNKNOWN`, result와 같은 `retrieved_at`을 사용한다.
- Evidence locator는 candidate `detail_url`이다.
- Evidence ID는 `support:bizinfo:{notice_id}:{content-hash-hex}`다.
- source version과 content hash는 정규화 candidate digest와 같다.
- 직접 API Evidence의 parent는 `[]`, published time은 null이다.
- `truncated`는 total 또는 bounded unique count가 실제 result보다 클 때만 true다.

입력·HTTP·transport·응답 검증 같은 runtime 요청 실패는 result가 아닌 `SupportNoticeDiscoveryError` 계열 exception으로 반환된다. 이 계열의 공통 안전 metadata는 `code`, `retryable`, `status_code | null`이며 credential, raw response body, 민감 URL은 오류 문자열에 포함하지 않는다. 환경설정 실패는 별도 `SupportNoticeDiscoveryConfigurationError(ValueError)`이고 이 metadata 계약을 갖지 않는다.

근거: [`support_agent/discovery_models.py`](../backend/app/agent/support_agent/discovery_models.py), [`support_agent/discovery_tool.py`](../backend/app/agent/support_agent/discovery_tool.py), [`test_support_discovery_tool.py`](../backend/tests/agent/test_support_discovery_tool.py).

## 9. Supervisor Agent

현재 연결 상태: Info conflict로 끝나지 않은 현재 실행 흐름에서 Support 결과 뒤 호출됨. 현재 역할은 검수 전 초안 작성이며 하위 Agent·Tool 호출 계획은 세우지 않음.

역할: 이미 수집된 Procedure·Info·Support 결과를 종합해 Blocker, Next Action, 추가 질문, 변경 후보와 grounded claim을 만든다. 출력은 Review 전 초안이며 DB 저장 결과가 아니다. 기존 목표 아키텍처의 Supervisor 주도 동적 호출 계획은 현재 구현과 구분한다.

### 9.1 입력 `SupervisorAgentInput`

`AgentGraph`가 하위 결과와 revision context를 이 model 하나로 묶어 `draft(request)`에 전달한다. Graph 공개 입력인 `AgentGraphInput`과 별개의 Supervisor 전용 계약이다.

| 필드 | 타입·기본값 | 의미·producer | 검증 |
|---|---|---|---|
| `trigger` | `RunTrigger` | Graph가 현재 run의 trigger를 복사 | `trigger_type`별 exact variant와 event 무결성 검증 |
| `case_snapshot` | `CaseSnapshot` | Graph가 실행 시작 snapshot을 전달 | source의 case ID와 output snapshot ID가 모두 이 snapshot과 같아야 함 |
| `source_results` | `ReviewSourceResult[]`, min 1 | Graph가 현재 run에서 성공한 하위 결과를 digest-bound wrapper로 전달 | call ID unique, 모든 source가 정확히 한 run 소속, output type/component/digest 일치 |
| `draft_version` | positive strict integer, 기본 1 | Graph가 `revision_count + 1`로 생성 | boolean·문자열 숫자·0 이하 거부 |
| `review_feedback` | `ReviewIssue[]`, 기본 `[]` | 최초에는 빈 목록, 재작업에는 직전 Review 문제를 Graph가 전달 | issue schema 검증 |
| `fact_overlays` | `FactChangeCandidate[] \| null`, 기본 null | Graph가 Info 결과로 만든 미저장 fact 변경 후보를 전달; direct call의 null이면 Supervisor가 source에서 파생 | non-null이면 candidate ID와 field path 각각 unique |
| `previous_draft` | `SupervisorDraft \| null`, 기본 null | Graph가 Review에서 거부된 직전 draft를 revision context로 전달 | nested `SupervisorDraft` 자체 schema만 검증; 현재 source와의 digest/provenance 관계 및 직전 draft ID와의 비동일성은 별도 교차검증하지 않음 |

추가 runtime guardrail은 Info의 procedure finding이 같은 `source_results` 안 Procedure call ID와 digest에 닫혀 있는지, source가 실제 decision·mutation·claim provenance를 모두 제공하는지 확인한다.

### 9.2 출력 `SupervisorDraft`

`SupervisorAgent`가 provider 의미 초안과 deterministic mutation/provenance를 결합하고 이 model 하나를 반환한다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `decision` | `DecisionDraft` | Supervisor가 Blocker·Next Action·질문 중 허용 조합을 작성하고 runtime ID·version·시각을 주입 | discriminator별 exact 필드, target/source/Evidence/human-confirmation guardrail 검증 |
| `mutations` | `MutationSet` | runtime이 검증된 Info/Support source에서 저장 **후보**를 결정론적으로 생성 | 후보 ID·대상 unique, before/after·source provenance 일치; DB 반영 아님 |
| `grounded_claims` | `GroundedClaim[]` | provider selector를 runtime이 실제 draft path/text와 결합 | target path가 실제 노출 문자열과 exact match, 고위험 주장 Evidence·표현 검증 |
| `source_call_ids` | runtime UUID[] min 1, unique | runtime이 실제 사용한 `ReviewSourceResult.meta.call_id`를 기록 | `decision.based_on_call_ids`와 집합이 정확히 같고 모든 provenance source를 포함 |

`source_call_ids` 집합은 `decision.based_on_call_ids`와 정확히 같아야 하고, 실제 사용한 결과·Evidence·mutation provenance를 모두 포함해야 한다.

### 9.3 Decision, Blocker, Next Action

`Blocker`:

| 필드 | 타입 |
|---|---|
| `blocker_code` | `UpperSnakeCode` |
| `title` | non-empty string |
| `description` | non-empty string |
| `evidence_refs` | string[] min 1 |

`NextAction`:

| 필드 | 타입 |
|---|---|
| `action_code` | `UpperSnakeCode` |
| `sequence` | positive strict integer; runtime은 1 생성 |
| `title` | non-empty string |
| `reason` | non-empty string |
| `questions_to_ask` | non-empty string[] |
| `target` | `NextActionTarget` |
| `evidence_refs` | string[] min 1 |

`NextActionTarget`은 tagged union이다.

- `ProcedureActionTarget`: `target_kind=PROCEDURE`, `procedure_step: ProcedureStepRef`
- `SupportActionTarget`: `target_kind=SUPPORT_PROGRAM`, `support_program: SupportProgramRef`

Procedure target은 정확히 한 Info finding과 일치해야 한다. 그 finding이 confirmation-only이면 decision도 사람 확인을 요구하고 질문이 있어야 한다. Support target은 정확히 한 Support check와 일치해야 하며 `NOT_RELEVANT` check는 선택할 수 없다. 선택한 target의 Evidence와 action Evidence는 연결돼야 한다.

`DecisionDraft` 공통 필드:

| 필드 | 타입 |
|---|---|
| `decision_type` | discriminator |
| `draft_id` | runtime UUID |
| `draft_version` | positive strict integer |
| `selection_summary` | non-empty string |
| `requires_human` | strict boolean |
| `evidence_refs` | string[] min 1 |
| `based_on_call_ids` | runtime UUID[] min 1 |
| `created_at` | aware runtime datetime |

Variant:

| 상태 | variant | `blocker` | `next_action` | `questions_for_user` |
|---|---|---|---|---|
| 현재 실행에서 생성 가능 | `ActionDecisionDraft` (`ACTION`) | required | required | exact `[]` |
| 현재 실행에서 생성 가능 | `NeedsMoreInfoDecisionDraft` (`NEEDS_MORE_INFO`) | required | exact null | min 1; `requires_human=true` |
| 타입만 정의됨 | `CaseCompleteDecisionDraft` (`CASE_COMPLETE`) | exact null | exact null | exact `[]`; `requires_human=false` |

`CASE_COMPLETE` 타입은 존재하지만 `SupervisorAgent._ensure_complete_is_supported()`가 항상 `SupervisorGuardrailError`를 던진다. 현재 bounded 절차조회로 전체 완료 coverage를 증명하지 못하기 때문에 **현 Graph에서 정상 도달 불가**다.

### 9.4 Mutation schema

`MutationSet`:

| 필드 | 타입 | 현재 Graph 가능 값 |
|---|---|---|
| `fact_changes` | `FactChangeCandidate[]` | Info overlay |
| `procedure_progress_changes` | `ProcedureProgressChangeCandidate[]` | 명시적 사용자 관측 기반 |
| `support_match_updates` | `SupportMatchUpdateCandidate[]` | Support check 기반 |
| `case_status_change` | `CaseStatusChangeCandidate \| null` | 현재 항상 null |

전체 candidate ID, fact field, procedure step ID, support program ID는 각 범위에서 unique다.

`FactChangeCandidate`:

| 필드 | 타입 |
|---|---|
| `candidate_id` | runtime UUID |
| `operation` | `SET \| CLEAR` |
| `source_fact_candidate_id` | runtime UUID |
| `source_type` | `INFO_ANALYSIS \| CONFIRMED_CONFLICT` |
| `field_path` | `CaseFieldKey` |
| `value_type` | `FactValueType` |
| `before_status`, `before_value` | snapshot 상태와 값 |
| `proposed_status`, `proposed_value` | SET=`CONFIRMED/non-null`, CLEAR=`UNKNOWN/null` |
| `candidate_status` | literal `READY_FOR_REVIEW` |
| `reason_summary` | non-empty string |
| `source_evidence_refs` | string[] min 1 |
| `source_call_id` | runtime UUID \| null |
| `confirmed_conflict_ref` | non-empty string \| null |

현재 실행이 생성하는 분기는 `source_type=INFO_ANALYSIS`, `source_call_id` non-null, `confirmed_conflict_ref=null`뿐이다.

타입만 정의된 `source_type=CONFIRMED_CONFLICT` 분기는 반대로 `source_call_id=null`, `confirmed_conflict_ref` non-null이어야 한다. 그러나 이를 만드는 trigger와 Graph node가 없으므로 **현재 실행에서 도달할 수 없다**.

`ProcedureProgressChangeCandidate`:

| 필드 | 타입/불변식 |
|---|---|
| `candidate_id` | runtime UUID |
| `procedure_step` | `ProcedureStepRef` |
| `before_status` | progress status \| null |
| `proposed_status` | progress status; 반드시 이전보다 전진 |
| `reason_summary` | non-empty string |
| `execution_evidence_refs` | string[] min 1 |
| `procedure_analysis_call_id` | Info call UUID |

Info observation이 `requires_confirmation=false`이고 같은 step finding의 `current_status`가 snapshot과 일치할 때만 생성한다.

`SupportMatchUpdateCandidate`는 `candidate_id`, 전체 `support_check`, `source_call_id`를 갖는다.

타입만 정의된 `CaseStatusChangeCandidate`는 `candidate_id`, `before_status=IN_PROGRESS`, `proposed_status=COMPLETED`, `reason_summary`, `evidence_refs`를 갖는다. `CASE_COMPLETE`가 차단되므로 현재 Graph가 생성하지 않는다.

### 9.5 `GroundedClaim`

| 필드 | 타입 |
|---|---|
| `claim_id` | runtime UUID |
| `claim_type` | `SUPPORT_PROGRAM \| AMOUNT \| DATE_OR_DEADLINE \| ELIGIBILITY \| LEGAL \| TAX \| PROCEDURE` |
| `target_path` | `JsonPointer` |
| `text` | target path에 실제 있는 exact string |
| `assertion_level` | `INFORMATION \| NEEDS_CONFIRMATION` |
| `evidence_refs` | string[] min 1 |

`ELIGIBILITY`는 항상 `NEEDS_CONFIRMATION`이어야 한다. target path는 `SupervisorDraft` 안 사용자 노출 string으로 해석되고 해당 값과 `text`가 정확히 같아야 한다. 고위험 문장에는 같은 path/text의 적절한 claim이 필요하며, stale/unknown Evidence로 확정 표현을 만들 수 없다.

### 9.6 provider → local → runtime 경계

| 층 | 모델 | top-level key |
|---|---|---|
| provider 응답 형식 | `SupervisorModelOutput` | `decision_type`, `selection_summary`, `requires_human`, `evidence_refs`, `blocker`, `next_action`, `questions_for_user`, `grounded_claims` |
| local 검증 결과 | `SupervisorSemanticDraft` | provider와 같음 |
| 공개 runtime 출력 | `SupervisorDraft` | `decision`, `mutations`, `grounded_claims`, `source_call_ids` |

Provider `GroundedClaimModelOutput`은 `claim_type`, `target_kind`, `target_index`, `assertion_level`, `evidence_refs`만 고른다. Runtime이 selector를 실제 visible field에 결합해 path/text/claim ID를 주입한다. draft ID, 시각, mutation, source call ID도 runtime 소유다. 최초 포함 `max_local_attempts=1..3`이고, 모델 출력이 계속 실패해도 Info가 제공한 안전한 질문과 적절한 Evidence가 있으면 결정론적 `NEEDS_MORE_INFO` fallback을 만들 수 있다.

근거: [`supervisor/agent.py`](../backend/app/agent/supervisor/agent.py), [`claim_safety.py`](../backend/app/agent/claim_safety.py), [`test_supervisor.py`](../backend/tests/agent/test_supervisor.py).

## 10. Review Tool

현재 연결 상태: Supervisor 초안 뒤 필수 호출됨.

역할: 동일 snapshot에 묶인 선행 결과와 Supervisor 초안을 독립 검수하고 `PASS` 또는 `REVISE`를 이유와 함께 반환한다. 새 근거를 검색하거나 초안을 직접 고치지 않는다.

### 10.1 입력 `ReviewSubject`

`AgentGraph`가 검수 package 전체를 `ReviewSubject.create()`로 묶어 이 model 하나를 `review(subject)`에 전달한다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `schema_version` | literal `agent-io/2.0` | Graph/runtime이 계약 버전을 고정 | 다른 버전 거부 |
| `review_subject_id` | runtime UUID | Graph가 검수 package마다 새로 생성 | UUID 형식 필수 |
| `review_attempt` | strict integer `1..3` | Graph가 최초 1, revision마다 1씩 증가 | boolean·문자열 숫자·범위 밖 값 거부 |
| `run_id` | runtime UUID | Graph가 현재 전체 실행 ID를 전달 | 모든 source meta와 같아야 함 |
| `case_id` | positive strict integer | Graph가 snapshot case ID를 전달 | snapshot과 모든 source meta의 case ID가 같아야 함 |
| `trigger` | 현재 3개 `RunTrigger` union | Graph가 `AgentGraphInput.trigger`를 복사 | discriminator·event ID·nested input 검증 |
| `snapshot` | `CaseSnapshot` | Graph가 실행 시작 snapshot을 전달 | 모든 source output의 snapshot ID와 같아야 함 |
| `source_results` | `ReviewSourceResult[]`, min 1 | Graph가 Procedure/Info/Support 결과와 meta/digest를 결합 | call ID unique; type/component/digest/run/case/snapshot closure 검증 |
| `supervisor_draft` | `SupervisorDraft` | Graph가 직전 Supervisor 성공 출력을 전달 | source call ID 집합과 draft 사용 ID 집합이 정확히 같아야 함 |
| `subject_digest` | digest | `ReviewSubject.create()`가 자신을 제외한 package 전체의 canonical digest를 계산 | 현재 전체 내용으로 재계산한 digest와 같아야 하며 nested 변경 시 직렬화 거부 |

`ReviewSourceResult`:

| 필드 | 타입 |
|---|---|
| `meta` | `InvocationMeta` |
| `output_digest` | digest |
| `output` | `InfoAnalysisResult \| SupportAnalysisResult \| ProcedureLookupResult` |

`meta.component`는 output 타입과 일치해야 한다. source call ID는 unique이고 그 집합은 `supervisor_draft.source_call_ids`와 정확히 같다. 각 source의 run/case/snapshot도 subject와 같아야 한다. source output이 생성 후 변하면 `output_digest` 검증이 실패한다.

`subject_digest`는 자기 자신을 제외한 **trigger, snapshot, source result, Supervisor draft를 포함한 나머지 전체 field**를 §3.2 방식으로 묶는다. `ReviewSubject.create()`만 runtime digest를 주입한다. nested 객체가 바뀐 뒤 직렬화하려 해도 다시 무결성을 검사한다.

### 10.2 출력 `ReviewResult`

`ReviewTool`이 deterministic safety finding과 provider 검수 결과를 결합하고 이 model 하나를 반환한다. 이유는 `resolution_reason`과 각 issue의 `reason_summary`에 항상 포함된다.

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `reviewed_subject_id` | runtime UUID | Tool이 입력 subject UUID를 복사 | 입력과 같아야 함 |
| `reviewed_subject_digest` | digest | Tool이 검증한 입력 subject digest를 복사 | 입력과 같아야 함 |
| `verdict` | `PASS \| REVISE` | Tool이 deterministic finding을 우선해 최종 판정 | PASS/REVISE gate 조건과 일치해야 함 |
| `issues` | `ReviewIssue[]` | provider와 deterministic checker가 문제 path·owner·이유·근거를 반환 | 위험 issue는 BLOCKING, target path/ref/call owner를 runtime이 재검증 |
| `missing_evidence` | `MissingEvidence[]` | Tool이 근거가 부족한 Supervisor claim path를 기록 | non-null `/supervisor_draft/...` 경로와 unique source type 필요 |
| `recommended_rework_targets` | `SUPERVISOR \| INFO_AGENT \| SUPPORT_AGENT \| PROCEDURE_TOOL` unique 목록 | runtime이 blocking issue path의 실제 owner로 다시 계산 | 모든 blocking owner와 missing Evidence의 Supervisor owner를 정확히 포함 |
| `resolution_reason` | non-empty string | Tool이 PASS 또는 REVISE 이유를 사람이 읽도록 반환 | 빈 값 금지 |

`ReviewIssue`:

| 필드 | 타입 |
|---|---|
| `issue_code` | `CASE_MISMATCH \| UNSUPPORTED_CLAIM \| MISSING_EVIDENCE \| STALE_EVIDENCE \| OVERCONFIDENT_LANGUAGE \| INFEASIBLE_ACTION \| HUMAN_CONFIRMATION_OMITTED \| AMBIGUOUS_LANGUAGE \| PROCEDURE_CONFLICT \| CONTRACT_VIOLATION` |
| `category` | `FACTUALITY \| EVIDENCE \| PROCEDURE \| SAFETY \| ACTIONABILITY \| LANGUAGE \| CONTRACT` |
| `severity` | `BLOCKING \| WARNING` |
| `target_component` | Supervisor 또는 세 source component |
| `target_call_id` | source call UUID \| null |
| `target_path` | `JsonPointer` |
| `reason_summary` | non-empty string |
| `evidence_refs` | string[] |

`UNSUPPORTED_CLAIM`, `MISSING_EVIDENCE`, `STALE_EVIDENCE`, `PROCEDURE_CONFLICT`, `CONTRACT_VIOLATION`은 항상 `BLOCKING`이다.

`MissingEvidence`는 `claim_path: JsonPointer`, `required_source_types: EvidenceSourceType[]` unique/min 1, `reason_summary`를 갖는다. Runtime은 non-null `/supervisor_draft/...` 경로만 허용한다.

Review gate:

- `PASS`에는 blocking issue, missing Evidence, rework target이 없어야 한다.
- `REVISE`에는 blocking issue 또는 missing Evidence가 최소 하나 있어야 한다.
- warning-only 검수는 `PASS`와 빈 rework 목록이어야 한다.
- provider가 적은 component/call owner는 신뢰하지 않고 target path에서 runtime이 다시 계산한다.
- 최종 rework 목록은 모든 blocking issue owner와 missing Evidence의 Supervisor owner로 runtime이 다시 만든다.
- 모델 `PASS`도 결정론적 safety finding을 제거할 수 없다.

### 10.3 provider → local → runtime 경계

| 층 | 모델 | top-level key |
|---|---|---|
| provider 응답 형식 | `ReviewProviderOutput` | `verdict`, `issues`, `missing_evidence`, `recommended_rework_targets`, `resolution_reason` |
| local 검증 결과 | `ReviewModelOutput` | provider와 같음 |
| 공개 runtime 출력 | `ReviewResult` | subject ID/digest를 앞에 추가한 7개 key |

Provider 출력에는 subject ID와 digest가 없다. Review Tool이 입력 무결성을 먼저 검사하고 provider 출력의 path/ref/semantic을 검증한 뒤 해당 값을 주입한다. output 형식 수정 시도는 `max_output_attempts=1..3`, 각 provider 요청 재시도는 `provider_max_retries=0..2` 범위다.

### 10.4 `ReviewProof`

Review Tool의 직접 출력이 아니라 Graph가 matching `PASS` 결과 뒤에만 발급한다.

| 필드 | 타입 | 의미·생성자 |
|---|---|---|
| `review_call_id` | runtime UUID | Graph가 matching Review `InvocationMeta.call_id`를 복사 |
| `run_id` | runtime UUID | Graph가 subject와 Review 호출의 동일 run ID를 기록 |
| `case_id` | positive strict integer | Graph가 subject와 Review 호출의 동일 Case ID를 기록 |
| `snapshot_id` | runtime UUID | Graph가 Review가 실제 검수한 snapshot ID를 기록 |
| `case_version` | positive strict integer \| null | Graph가 검수한 snapshot의 Case version을 기록 |
| `review_subject_id` | runtime UUID | Graph가 `PASS`한 exact subject ID를 기록 |
| `reviewed_subject_digest` | digest | Graph가 Review 결과와 subject에 공통인 digest를 복사해 내용 변경을 차단 |
| `verdict` | literal `PASS` | Graph가 `PASS` 결과에서만 proof를 만들도록 고정 |
| `reviewed_at` | aware runtime datetime | Graph clock이 proof 발급 시각을 생성 |

Review invocation component가 `REVIEW_TOOL`이고 run/case가 subject와 같으며, result subject ID/digest가 일치할 때만 생성한다.

근거: [`review_tool/models.py`](../backend/app/agent/review_tool/models.py), [`review_tool/tool.py`](../backend/app/agent/review_tool/tool.py), [`test_review_tool.py`](../backend/tests/agent/test_review_tool.py).

## 11. LangGraph 실행기 (내부 클래스 `AgentGraph`)

현재 연결 상태: standalone CLI와 테스트에 연결됨. Agent나 Tool이 아니며 실제 사용자 Case read/write에는 연결되지 않음.

역할: LangGraph `StateGraph`의 node와 조건부 edge를 구성·실행하고, 단계 간 결과 전달·재작업 상한·안전 실패 변환을 담당한다. 도메인 전문 역할을 가진 별도 Agent가 아니다.

### 11.1 입력 `AgentGraphInput`

standalone caller 또는 향후 BE adapter가 이 model 하나를 만들어 `run(request)`에 전달한다. `trace_id`를 포함해 Graph 실행에 필요한 공개 입력이 모두 이 schema에 들어 있다.

| 필드 | 타입·기본값 | 의미·producer | 검증 |
|---|---|---|---|
| `trigger` | `RunTrigger` | caller가 전체 실행 사유와 event payload를 제공 | `trigger_type` discriminator로 정확히 한 variant 선택; 자연어 trigger의 outer/nested event ID 일치 |
| `case_snapshot` | `CaseSnapshot` | caller가 같은 시점의 Case read view를 제공 | case ID/version, fact/progress unique, Evidence reference closure, timezone 검증 |
| `trace_id` | non-empty string \| null, 기본 null | caller가 observability correlation 값을 선택적으로 제공 | 빈 문자열 거부; 판단 로직에는 사용하지 않지만 `InvocationMeta`를 통해 `ReviewSubject` package digest에는 포함 |

`RunTrigger`의 exact variant는 다음과 같다.

| 입력 variant | 필드 | producer·검증 |
|---|---|---|
| `CaseCreatedTrigger` | `trigger_type=CASE_CREATED`, `input_event_id`, `client_event_id`, `input: RedactedInput`, `submitted_at` | Case 생성 event caller가 생성; outer/nested input event ID 일치, submitted time timezone 필수 |
| `ResultSubmittedTrigger` | `trigger_type=RESULT_SUBMITTED`, 나머지는 CaseCreated와 같음 | 결과 제출 event caller가 생성; 같은 event·time 검증 |
| `SupportRefreshTrigger` | `trigger_type=SUPPORT_REFRESH`, `input_event_id`, `client_event_id`, `support_programs` min 1, `as_of` | refresh caller가 stable program ref와 기준일 제공; 자연어 `input` 필드는 허용하지 않음 |

Graph는 입력을 deep copy하고 시작 snapshot digest를 보관해 실행 중 caller 또는 component가 기준 snapshot을 바꾸지 못하게 한다.

### 11.2 출력 `AgentGraphOutput`

`AgentGraphOutput`은 `outcome_type` discriminator를 쓰는 정확히 세 typed 반환 variant의 union이다. 이 중 `SAFE_FAILURE`는 업무 계획 성공이 아니라 검수되지 않은 결과를 노출하지 않았다는 안전 실패다.

| 출력 variant | `outcome_type` | 언제 Graph가 생성하는가 | 소비자 해석·검증 |
|---|---|---|---|
| `ReviewedPlanOutcome` | `REVIEWED_PLAN` | Review가 exact subject에 `PASS`하고 Graph가 proof를 발급 | 검수된 계획 후보이며 DB 저장 완료가 아님; subject/proof 전 provenance 일치 필요 |
| `ConflictOutcome` | `CONFLICT` | Info가 confirmed Case fact와 다른 새 입력을 발견 | 서비스 종료가 아니라 해당 run을 안전 종료하고 사용자 확인을 기다림; conflict digest/snapshot 일치 필요 |
| `SafeFailureOutcome` | `SAFE_FAILURE` | component 실패, structured output 실패, Review revision 소진 | 미검수 draft/mutation을 노출하지 않는 fail-closed 결과; code·component·trace schema 검증 |

### 11.3 `ReviewedPlanOutcome`

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `outcome_type` | literal `REVIEWED_PLAN` | Graph가 검수 통과 결과 tag를 고정 | 다른 tag 거부 |
| `review_subject` | `ReviewSubject` | Graph가 Review에 전달했던 exact package를 반환 | subject 자체 digest와 모든 source closure 검증 |
| `review_proof` | `ReviewProof` | Graph가 matching `PASS` Review 호출 뒤 발급 | subject와 run/case/snapshot/version/ID/digest가 모두 일치 |

subject와 proof의 run, case, snapshot, version, subject ID, digest가 모두 일치해야 한다. 이 outcome은 검수된 AI 결과라는 뜻이며 이 문서 범위에는 저장 동작이 없다.

### 11.4 `ConflictOutcome`

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `outcome_type` | literal `CONFLICT` | Graph가 사용자 확인 대기 결과 tag를 고정 | 다른 tag 거부 |
| `run_id` | runtime UUID | Graph가 현재 실행 ID를 기록 | UUID 형식 필수 |
| `case_id` | positive strict integer | Graph가 snapshot case ID를 복사 | 입력 snapshot과 같아야 함 |
| `trigger` | `RunTrigger` | Graph가 입력 trigger를 복사 | trigger variant schema 검증 |
| `snapshot_id` | runtime UUID | Graph가 입력 snapshot ID를 복사 | 각 conflict snapshot ID와 같아야 함 |
| `case_version` | positive strict integer \| null | Graph가 입력 snapshot version을 복사 | 각 conflict version과 같아야 함 |
| `conflicts` | `ConflictCandidate[]`, min 1 | Graph가 Info 결과의 충돌을 반환 | ref·candidate ID unique, 각 digest와 snapshot/version 무결성 검증 |
| `message_code` | literal `CONFIRM_CONFLICT` | Graph가 caller의 다음 처리 code를 고정 | 다른 code 거부 |

Conflict ref와 candidate ID는 unique이고 각 conflict의 snapshot/version은 outcome과 같다. 현재 standalone `conflict_ref`는 simulation 전용이다. `ConflictOutcome`에는 별도 `evidence_records` 필드가 없으며, 이 shape를 다른 경계의 저장/확인 DTO로 간주하면 안 된다.

### 11.5 `SafeFailureOutcome`

| 필드 | 타입 | 의미·producer | 검증 |
|---|---|---|---|
| `outcome_type` | literal `SAFE_FAILURE` | Graph가 fail-closed 결과 tag를 고정 | 다른 tag 거부 |
| `run_id` | runtime UUID | Graph가 현재 실행 ID를 기록 | UUID 형식 필수 |
| `case_id` | positive strict integer | Graph가 입력 snapshot case ID를 복사 | positive strict integer |
| `trigger` | `RunTrigger` | Graph가 입력 trigger를 복사 | trigger variant schema 검증 |
| `snapshot_id` | runtime UUID | Graph가 입력 snapshot ID를 복사 | UUID 형식 필수 |
| `case_version` | positive strict integer \| null | Graph가 입력 snapshot version을 복사 | null 또는 positive strict integer |
| `failure_code` | `REVIEW_RETRY_EXHAUSTED \| COMPONENT_UNAVAILABLE \| STRUCTURED_OUTPUT_FAILED` | Graph가 exception 종류 또는 revision 소진으로 분류 | 허용 enum만 가능 |
| `message_code` | `UpperSnakeCode` | Graph가 안전한 caller-facing 기계 code를 선택 | upper snake 형식 |
| `recovery_action_code` | `RETRY \| RESUBMIT_INPUT \| CONTACT_SUPPORT \| NONE` | Graph가 안전한 후속 처리 종류를 선택 | 현재 producer는 `RETRY` 또는 `NONE`만 생성 |
| `requested_field_paths` | `CaseFieldKey[]` | 추가 입력 대상이 있을 경우 Graph가 제공하는 자리 | 현재 producer는 `[]`; registry 밖 값 거부 |
| `retryable` | strict boolean | Graph가 failure 분류에 따라 계산 | `0/1` 등 boolean coercion 거부 |
| `failed_component` | `Component \| null` | Graph가 실패 owner를 기록하거나 Graph-level 실패이면 null | 허용 component enum만 가능 |
| `trace_id` | non-empty string \| null | Graph가 입력 trace ID를 복사 | 빈 문자열 거부 |

현재 Graph producer는 recovery action으로 `RETRY` 또는 `NONE`만 만들고 `requested_field_paths=[]`를 사용한다. 구성요소의 schema/guardrail/value 오류는 `STRUCTURED_OUTPUT_FAILED`, 설정·요청·upstream 계열 오류는 `COMPONENT_UNAVAILABLE`로 분류한다. Review 수정 2회 소진 시 `REVIEW_RETRY_EXHAUSTED`다. 검수되지 않은 draft나 mutation은 포함하지 않는다.

### 11.6 Review 재작업 라우팅

- 최초 Review + 수정 후 Review 최대 2회, 총 Review attempt 최대 3회다.
- rework target이 없으면 Supervisor를 다시 실행한다.
- 여러 target이면 dependency 순서 `PROCEDURE_TOOL → INFO_AGENT → SUPPORT_AGENT → SUPERVISOR`에서 가장 이른 지점부터 실행한다.
- Procedure 재작업 시 기존 source를 모두 버린다.
- Info 재작업 시 Procedure source만 유지한다.
- Support 재작업 시 Procedure와 Info source를 유지한다.
- Supervisor 재작업 시 source를 모두 유지한다.
- 각 재실행은 새 call ID와 digest를 만들며 이전 proof를 재사용하지 않는다.

## 12. 타입·기능별 현재 실행 상태

이 표가 “코드에 존재한다”와 “현재 Graph에서 동작한다”의 구분 기준이다.

| 항목 | 상태 | 현재 사실 |
|---|---|---|
| `InvocationMeta` | 현재 실행 흐름에 연결됨 | Graph가 source/Review provenance에 실제 사용 |
| `ComponentRequest`, `ComponentSuccess`, `ComponentFailure`, `ComponentWarning`, `ComponentError` | 타입만 정의됨 | 타입은 있으나 현재 구성요소 호출은 bare payload/result/exception |
| `CASE_CREATED`, `RESULT_SUBMITTED`, `SUPPORT_REFRESH` | 현재 실행 흐름에 연결됨 | 현재 `RunTrigger`와 Graph route에 존재 |
| `CheckSpecificSupportInput` | 구현됨 · 실행 흐름 미연결 | `SupportAgent.analyze()` 직접 호출은 처리하지만 Graph가 생성하지 않음 |
| `BizInfoSupportDiscoveryTool` 입출력 | 구현됨 · 실행 흐름 미연결 | 독립 공식 API adapter 구현·테스트됨; Graph/Support catalog와 자동 연결 없음 |
| `CaseCompleteDecisionDraft` | 타입만 정의됨 | 타입은 유효하나 Supervisor가 항상 거부하여 Graph 도달 불가 |
| `CaseStatusChangeCandidate` | 타입만 정의됨 | CASE_COMPLETE에만 생성되므로 현 Graph 도달 불가 |
| `FactChangeSourceType.CONFIRMED_CONFLICT` branch | 타입만 정의됨 | validator는 있으나 확인 trigger/node가 없어 Graph 도달 불가 |
| `ReviewedPlanOutcome`, `ConflictOutcome`, `SafeFailureOutcome` | 현재 실행 흐름에 연결됨 | 현재 공개 outcome union의 전부 |

다음 항목은 이 문서의 AI 내부 스키마가 아니므로 여기서 필드 계약을 정의하지 않는다.

- BE HTTP request/response
- BE shared DTO와 field mapping
- DB table/column/migration/history
- 인증, Case 소유권, idempotency, CAS transaction
- 실제 Case snapshot resolver와 저장 command
- 외부 Output/State Guardrail
- 크롤링·RAG ingestion pipeline과 운영 데이터 최신성

필요한 경계와 결정 항목은 [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md), 실행 구조는 [`architecture.md`](./architecture.md), 데이터 수집 구현 계획은 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)에서 각각 관리한다.

## 13. 구현 근거와 변경 동기화 규칙

| 범위 | 구현 근거 | 회귀 근거 |
|---|---|---|
| 공통 schema·digest·outcome | [`schemas.py`](../backend/app/agent/schemas.py) | [`test_schemas.py`](../backend/tests/agent/test_schemas.py) |
| Graph route·revision·safe failure | [`graph.py`](../backend/app/agent/graph.py), [`state.py`](../backend/app/agent/state.py) | [`test_graph.py`](../backend/tests/agent/test_graph.py) |
| 정보분석 | [`info_agent/agent.py`](../backend/app/agent/info_agent/agent.py), [`enrichment.py`](../backend/app/agent/enrichment.py) | [`test_info_agent.py`](../backend/tests/agent/test_info_agent.py) |
| 지원금 비교·catalog | [`support_agent/agent.py`](../backend/app/agent/support_agent/agent.py), [`support_agent/models.py`](../backend/app/agent/support_agent/models.py) | [`test_support_agent.py`](../backend/tests/agent/test_support_agent.py) |
| BizInfo discovery | [`support_agent/discovery_models.py`](../backend/app/agent/support_agent/discovery_models.py), [`support_agent/discovery_tool.py`](../backend/app/agent/support_agent/discovery_tool.py) | [`test_support_discovery_tool.py`](../backend/tests/agent/test_support_discovery_tool.py) |
| 절차조회 | [`procedure_tool/tool.py`](../backend/app/agent/procedure_tool/tool.py), [`procedure_tool/models.py`](../backend/app/agent/procedure_tool/models.py) | [`test_procedure_tool.py`](../backend/tests/agent/test_procedure_tool.py) |
| Supervisor | [`supervisor/agent.py`](../backend/app/agent/supervisor/agent.py), [`claim_safety.py`](../backend/app/agent/claim_safety.py) | [`test_supervisor.py`](../backend/tests/agent/test_supervisor.py) |
| Review | [`review_tool/tool.py`](../backend/app/agent/review_tool/tool.py), [`review_tool/models.py`](../backend/app/agent/review_tool/models.py) | [`test_review_tool.py`](../backend/tests/agent/test_review_tool.py) |

Schema를 바꿀 때는 한 PR에서 다음을 함께 갱신한다.

1. 해당 Pydantic model과 deterministic validator
2. producer와 consumer
3. 정상·거부·경계 회귀 테스트
4. 이 문서의 필드 표와 상태 표기
5. BE/shared 경계에 영향이 있을 때만 별도 BE 단일 문서

타입이 추가됐지만 Graph route가 없으면 상태를 `타입만 정의됨` 또는 `구현됨 · 실행 흐름 미연결`로 기록한다. 실제 route와 회귀 테스트가 추가된 뒤에만 `현재 실행 흐름에 연결됨`으로 바꾼다.
