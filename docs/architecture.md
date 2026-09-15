# RE:BORN Agent 아키텍처

> 소유: AI
>
> 기준일: 2026-09-15
>
> 이 문서의 책임: **구성요소의 책임, 호출 방향, 실행 경계**

이 문서는 필드·JSON·HTTP·DB 컬럼을 정의하지 않는다. 현재 코드 구조와 앞으로 만들 구조도 한 문장 안에서 섞지 않는다.

## 1. 문서 지도

| 질문 | 단일 기준 문서 |
|---|---|
| 현재 Agent/Tool의 정확한 입출력 필드는 무엇인가? | [`agent-tool-io-schema.md`](./agent-tool-io-schema.md) |
| BE 없이 어떻게 실행하고 무엇이 실제·합성 데이터인가? | [`agent-standalone-runtime-requirements.md`](./agent-standalone-runtime-requirements.md) |
| 공식 API, 크롤링, RAG를 어떤 순서로 구현하는가? | [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md) |
| BE가 검토·구현해야 할 shared DTO, HTTP, 저장 조건은 무엇인가? | [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md) |
| dependency 버전과 실제 사용 여부는 무엇인가? | [`tech-stack.md`](./tech-stack.md) |

`interface-spec.md`와 `schema/schema_table.md`는 기존 링크를 보존하기 위한 이전 안내 파일이다. HTTP와 DB 요구사항을 그 파일들에 다시 추가하지 않는다.

## 2. 상태 표기

| 표기 | 의미 |
|---|---|
| `[CURRENT_AI]` | 현재 저장소의 Agent 코드와 테스트로 확인된 구조 |
| `[TYPE_ONLY]` | 타입은 있지만 현재 Graph에서 생성·도달하지 않는 분기 |
| `[NOT_WIRED]` | 구현체는 있으나 현재 사용자 요청 Graph에 연결되지 않음 |
| `[PLANNED_AI][NOT_IMPLEMENTED]` | AI가 구현할 목표이나 현재 코드는 없음 |
| `[PROPOSED_SHARED][NOT_APPROVED]` | AI·BE·FE 공동 승인 전 제안 |
| `[AGREED_SHARED]` | 승인자·날짜·계약 PR 또는 ADR이 기록된 공동 계약 |

현재 이 문서의 `[AGREED_SHARED]` 항목은 **0개**다.

## 3. `[CURRENT_AI]` 현재 실행 경계

현재 제품 서버가 아니라 persistence-free Python Agent 코어가 구현돼 있다.

```text
schema-valid AgentGraphInput
  → AgentGraph (LangGraph)
      ├─ CASE_CREATED | RESULT_SUBMITTED
      │    → Procedure → Info → Support → Supervisor → Review
      └─ SUPPORT_REFRESH
           → Support → Supervisor → Review

Review PASS                       → REVIEWED_PLAN
Info의 confirmed fact 충돌       → CONFLICT
예외·재작업 상한 소진            → SAFE_FAILURE
```

현재 구조가 의미하는 것은 다음과 같다.

- `AgentGraph`가 trigger별 첫 노드와 고정 의존 순서를 선택한다.
- Supervisor는 이미 수집된 결과를 받아 초안을 만든다. 하위 Agent/Tool을 직접 호출하지 않는다.
- 하위 구성요소끼리 직접 호출하지 않는다. 앞 단계 결과는 Graph가 다음 단계 입력에 넣는다.
- 정상 Supervisor 초안은 항상 Review를 거친다. Info가 조기 반환하는 `CONFLICT`는 Supervisor 초안이 아니므로 예외다.
- Graph는 인증, 실제 Case 조회, DB 저장, transaction, CAS를 수행하지 않는다.
- 현재 CLI는 비식별 합성 Case와 합성 reviewed support catalog를 조립한다. 실제 범위는 runbook에서 구분한다.
- 현재 `SUPPORT_REFRESH`는 주입된 같은 catalog의 지정 program을 Support부터 재평가하는 trigger다. 외부 API·crawler·RAG로 catalog 자체를 갱신하지 않는다.

## 4. `[CURRENT_AI]` 구성요소 책임

| 구성요소 | 현재 책임 | 하지 않는 일 |
|---|---|---|
| `AgentGraph` | 호출 순서, 결과 전달, Review 재작업, 반복 상한, safe failure | 업무 근거 생성, 인증, DB 저장 |
| Supervisor Agent | Procedure·Info·Support 결과에서 결정 초안 생성; `ACTION`이면 Blocker와 Next Action 각 1개 선택 | 하위 구성요소 직접 호출, Evidence 생성, Review 우회 |
| 정보분석 Agent | redacted 입력·snapshot·절차 원문을 함께 분석해 사실 변경 후보, 누락, 충돌, 불확실성, canonical procedure finding 생성 | 인터넷 검색, 웹 제목으로 step 생성, Case 직접 변경 |
| 지원금 Agent | 주입된 immutable `ReviewedSupportCatalog`를 Case 사실과 비교하고 Evidence 연결 | raw 공고 자동 승격, 자격·수령 확정, 신청 상태 변경 |
| 절차조회 Tool | 공식 URL 선택·발견, 안전한 원문 fetch, 문서·Evidence 정규화 | 원문 의미 분석, 적용 절차·완료 여부·우선순위 결정 |
| Review Tool | source digest·provenance·Case 문맥·초안의 독립 검토 | 새 검색, 초안 직접 수정, 저장 |
| `BizInfoSupportDiscoveryTool` | 기업마당 API에서 raw 후보와 `OFFICIAL_API` Evidence 생성 | `[NOT_WIRED]` Graph 주입, reviewed catalog 발행, 자격 판정 |
| `TraceSink` | metadata-only event 경계; 기본 구현은 `NullTraceSink` | Langfuse 비용 전송·보존 정책 제공 |

정확한 클래스 필드와 조건부 불변식은 schema 문서만을 기준으로 한다.

## 5. `[CURRENT_AI]` 데이터 흐름과 신뢰 경계

### 5.1 절차조회와 정보분석

```text
ProcedureLookupInput
  → 절차조회 Tool
  → 공식 원문 documents + Evidence
  → Graph가 같은 call ID와 함께 InfoAnalysisInput에 주입
  → 정보분석 Agent가 Case 문맥에서 procedure_findings 생성
```

절차조회 Tool이 정보분석 Agent에서 파생되거나 정보분석 Agent를 호출하는 구조가 아니다. Tool은 인터넷에서 폐업 관련 공식 원문을 가져오고, Agent가 그 결과를 분석한다. 검색 provider의 title·snippet은 URL 발견 metadata일 뿐 Evidence가 아니다.

### 5.2 지원금

```text
현재 사용자 요청 Graph: 합성 ReviewedSupportCatalog → Support Agent

별도 discovery 경로: 기업마당 API → raw candidate + Evidence
                                      └─ Graph에는 아직 연결하지 않음
```

raw 공고와 검수 catalog를 분리하는 이유는 공고 문구만으로 사용자 자격을 확정하거나 잘못된 공고를 자동 승격하지 않기 위해서다. 수집·검수·RAG 연결 목표는 데이터 구현 계획에서 관리한다.

### 5.3 Supervisor와 Review

Procedure·Info·Support 결과는 각 call ID와 digest를 가진 `ReviewSourceResult`로 묶인다. Graph는 이 결과와 snapshot·revision context를 하나의 `SupervisorAgentInput`으로 전달한다. Supervisor 초안과 source result는 immutable `ReviewSubject`가 되고, Review는 그 subject의 digest를 확인한다. 초안이 바뀌면 새 subject를 만들며 이전 Review를 재사용하지 않는다.

## 6. 지원 지식과 RAG의 아키텍처 경계

`[CURRENT_AI]` Support Agent는 주입된 immutable `ReviewedSupportCatalog`만 읽는다. 기업마당 raw discovery adapter는 `[NOT_WIRED]`이고, Chroma package는 manifest에만 있으며 corpus·index·retriever는 없다.

`[PLANNED_AI][NOT_IMPLEMENTED]` 목표는 승인된 공식 원문을 수집·검수해 versioned catalog/corpus를 발행하고, Chroma index와 retriever가 원문 Evidence까지 역추적되는 결과만 Support Agent에 제공하는 것이다. 수집 허용범위, 구현 단계, 평가 수치는 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)를 단일 기준으로 한다.

## 7. `[CURRENT_AI]` 재시도와 재작업

| 경계 | 현재 상한 | 동작 |
|---|---:|---|
| Info 의미·grounding | 총 3회 | schema 또는 canonical source 검증 실패 시 해당 Agent 안에서 재생성 |
| Support 의미·grounding | 총 3회 | catalog ID·조건·Evidence 검증 실패 시 재생성 |
| Supervisor 초안 | 총 3회 | decision·claim·provenance 검증 실패 시 재생성 |
| Review 출력 | 총 2회 | Review 자체 출력 계약 실패 시 재생성 |
| Procedure 외부 요청 | 기본 재시도 1회 | 전체 lookup deadline 안에서 일시적 실패만 재시도 |
| Graph Review 재작업 | 최대 2회 | 원인상 가장 앞선 구성요소부터 다시 실행 |

Review가 `REVISE`를 반환하면 Graph는 검증된 issue target의 의존 순서를 따른다.

| 원인 | 재실행 범위 |
|---|---|
| Procedure | Procedure → Info → Support → Supervisor → Review |
| Info | Info → Support → Supervisor → Review |
| Support | Support → Supervisor → Review |
| Supervisor 또는 target 없음 | Supervisor → Review |

상한 소진이나 예외는 성공처럼 포장하지 않고 `SAFE_FAILURE`로 끝낸다.

## 8. `[CURRENT_AI]` 코드가 강제하는 안전 조건

- 모든 public Pydantic schema는 strict, `extra="forbid"`이며 naive datetime을 거부한다. UUID·시각 같은 runtime 필드는 provider 출력 schema에서 제외하고 구성요소 코드가 주입한다.
- Case snapshot은 실행 중 immutable하게 취급하고 시작·종료 digest를 비교한다.
- LLM 출력은 provider 형식 검증 뒤 구성요소별 의미·provenance 검증을 다시 거친다.
- unknown/stale Evidence로 확정 claim을 만들지 않는다.
- 웹 원문만으로 절차 완료 상태나 `CASE_COMPLETE`를 만들지 않는다.
- Review되지 않은 초안은 `REVIEWED_PLAN`으로 반환하지 않는다.
- 외부 문서와 사용자 입력은 명령이 아니라 untrusted data로 취급한다.

별도 업무 Rule 엔진은 두지 않는다. 판단은 Agent와 Review가 하되, ID·schema·digest·provenance·호출 권한·반복 상한처럼 결정적으로 검증 가능한 안전 조건은 코드가 강제한다.

## 9. 목표 구조 — 현재 구현과 혼동 금지

### 9.1 `[PLANNED_AI][NOT_IMPLEMENTED]` Agent 오케스트레이션

- Supervisor가 snapshot과 실행 상태를 보고 필요한 구성요소 호출 계획을 만든다.
- LangGraph router가 허용된 dependency와 반복 상한 안에서 그 계획을 실행한다.
- 동적 호출 계획 schema와 router가 구현돼야 `[CURRENT_AI]`로 바뀐다.

### 9.2 `[PLANNED_AI][NOT_IMPLEMENTED]` 공식 데이터·크롤링·RAG

- 검토된 공식 출처를 수집하고 parser/chunker/version/hash를 거쳐 corpus와 index를 만든다.
- 검수된 support catalog와 Evidence resolver를 Graph에 연결한다.
- 상세 단계와 완료 조건은 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)에서 관리한다.

### 9.3 `[PLANNED_AI][NOT_IMPLEMENTED]` 관측성

- 현재 `TraceSink` 경계에 Langfuse adapter를 구현한다.
- prompt·사용자 입력·credential을 전송하기 전에 AI·BE·보안/PM이 masking, retention, access policy를 승인해야 한다.
- adapter가 실제 token·cost·latency를 전송하고 테스트와 운영 확인을 통과하기 전에는 “Langfuse 비용 추적 사용 중”으로 표시하지 않는다.

### 9.4 `[PROPOSED_SHARED][NOT_APPROVED]` 생산 연결

```text
인증된 요청
  → BE가 소유권을 확인하고 immutable CaseSnapshot 조립
  → AgentGraph
  → REVIEWED_PLAN | CONFLICT | SAFE_FAILURE
  → BE Guardrail + version/CAS + atomic persistence
  → 저장 후 read-back 응답
```

인증·개인정보·canonical ID·idempotency·DB transaction·HTTP 응답은 공동 계약이며 아직 승인·구현되지 않았다. 제안 내용과 승인 기준은 BE 단일 전달 문서에서만 관리한다.

## 10. 구현 완료의 판정 기준

| 범위 | 완료라고 말할 조건 |
|---|---|
| 현재 Agent 내부 계약 | 코드 존재 + contract/unit test 통과 + 실제 호출 경로 존재 |
| 외부 API adapter | 코드·테스트 + 필요한 credential로 제한 실측; HTTP 200과 실제 Case 연결은 별도 기록 |
| 크롤링/RAG | 수집·파싱·버전·검수·index·retrieval·Evidence 연결과 평가가 모두 통과 |
| shared 계약 | AI·BE·필요 시 FE/PM 승인 기록 + 구현 + 통합 acceptance test |
| 생산 연동 | 인증된 실제 Case read/write, CAS/transaction, Review 결과 저장과 read-back 검증 |

## 11. 근거

| 설명 | 저장소 근거 |
|---|---|
| Graph 노드·routing·상한 | `backend/app/agent/graph.py`, `backend/app/agent/state.py` |
| Agent/Tool 책임 | `backend/app/agent/supervisor/`, `info_agent/`, `support_agent/`, `procedure_tool/`, `review_tool/` |
| strict schema·digest | `backend/app/agent/schemas.py`, `guardrails.py`, `projection.py` |
| standalone fixture·진입점 | `backend/app/agent/fixtures.py`, `backend/app/agent/cli.py` |
| metadata trace 경계 | `backend/app/agent/tracing.py` |
| 동작 검증 | `backend/tests/agent/` |

문서보다 현재 코드와 테스트가 우선한다. shared 계약은 승인 뒤 생성되는 OpenAPI/공유 JSON Schema 및 실제 migration·모델이 Markdown 제안보다 우선한다.
