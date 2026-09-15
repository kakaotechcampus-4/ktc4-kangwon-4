# RE:BORN Agent 아키텍처

> 소유: AI
>
> 기준일: 2026-09-15
>
> 이 문서의 책임: **목표 Agent 구조, 현재 구현 구조, 두 구조의 차이, 구성요소 책임과 호출 방향**

이 문서는 필드·JSON·HTTP·DB 컬럼을 정의하지 않는다. 정확한 Agent/Tool 필드는 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md)를 따른다.

## 1. 한눈에 보는 결론

| 질문 | 답 |
|---|---|
| 사용하는 실행 프레임워크는? | 외부 프레임워크 **LangGraph**의 `StateGraph`를 사용한다. |
| `AgentGraph`는 무엇인가? | `StateGraph`를 구성·compile·실행하는 현재 프로젝트의 Python 클래스명이다. **별도 Agent가 아니다.** |
| Agent는 몇 개인가? | Supervisor, 정보분석, 지원금의 3개다. |
| Tool은 몇 개인가? | 절차조회, Review, 기업마당 공고조회의 3개다. 단, 기업마당 공고조회는 현재 실행 흐름에 연결되지 않았다. |
| 목표 오케스트레이터는? | Supervisor Agent다. 필요한 하위 Agent·Tool 선택과 재호출 판단을 맡는다. |
| 현재 실제 호출 순서는 누가 정하는가? | 현재 feature 브랜치에서는 `AgentGraph` 클래스의 조건부 edge가 trigger별 시작점과 정상 1차 순서를 정한다. Supervisor는 초안만 만든다. |
| 목표 구조가 구현됐는가? | 아니다. 현재 고정 routing은 standalone 실행을 위한 구현 단계이며 Supervisor 주도 동적 planning은 후속 구현이다. |
| LangChain·Langfuse는 현재 쓰는가? | package는 설치 목록에 있지만 LangChain runtime import와 Langfuse 전송 adapter는 없다. 현재 실행에 직접 쓰는 관련 프레임워크는 LangGraph다. |

## 2. 문서 지도

| 알고 싶은 내용 | 기준 문서 |
|---|---|
| Agent/Tool별 정확한 입력·출력 필드와 validator | [`agent-tool-io-schema.md`](./agent-tool-io-schema.md) |
| BE 없이 실행하는 방법과 실제·합성 데이터 구분 | [`agent-standalone-runtime-requirements.md`](./agent-standalone-runtime-requirements.md) |
| 공식 API, crawler, RAG의 현재 상태와 구현 순서 | [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md) |
| 외부 연동 전에 협의할 shared DTO·저장 경계 | [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md) |
| dependency 버전과 실제 import 여부 | [`tech-stack.md`](./tech-stack.md) |

`interface-spec.md`와 `schema/schema_table.md`는 기존 링크를 보존하는 안내 파일이다. 이 문서들에 동일 계약을 다시 정의하지 않는다.

## 3. 목표 아키텍처 — Supervisor 주도

이 저장소의 기존 아키텍처 문서가 정의한 목표는 **Supervisor Agent가 전역 계획과 오케스트레이션을 소유하는 구조**다.

- Supervisor는 현재 Case와 실행 상태를 해석해 필요한 하위 Agent·Tool만 선택한다.
- 정보분석 Agent와 지원금 Agent는 Supervisor에 Agent-as-Tool 형태로 노출한다.
- 절차조회 Tool은 Supervisor가 필요할 때 호출하는 일반 Tool이다.
- 하위 Agent·Tool끼리는 서로 직접 호출하지 않는다.
- Supervisor는 결과가 충분한지 판단해 재호출·사용자 질문·종료를 결정한다.
- 모든 정상 Supervisor 초안은 선택 사항이 아니라 필수 검증 관문인 Review Tool을 거친다.
- LangGraph 실행기는 Supervisor의 계획을 허용된 dependency, 호출 횟수, 전체 deadline 안에서 실행한다.

```text
실행 입력
  → LangGraph 실행기
  → Supervisor가 현재 상태 해석·호출 계획 수립
       ├─ 필요 시 정보분석 Agent 호출
       ├─ 필요 시 지원금 Agent 호출
       └─ 필요 시 절차조회 Tool 호출
  → Supervisor가 결과 충분성 평가·검수 전 초안 작성
  → Review Tool 필수 검수
       ├─ PASS   → 검수된 계획 후보
       └─ REVISE → Supervisor가 재호출 대상 결정 후 다시 계획
```

이 목표 구조에서 Supervisor는 업무 판단과 호출 계획을 소유하고, LangGraph는 실행 상태와 안전 상한을 소유한다. “LangGraph가 있다”와 “AgentGraph가 별도 Agent다”는 같은 뜻이 아니다.

## 4. 현재 구현 — 고정 routing을 가진 standalone 실행기

현재 feature 브랜치에는 LangGraph `StateGraph`를 감싼 `AgentGraph` 클래스가 있다. 정상 1차 실행의 시작점과 순서는 이 클래스 코드가 정하며, 일부 조건에서만 분기한다.

```text
AgentGraphInput
  → LangGraph StateGraph
      ├─ CASE_CREATED | RESULT_SUBMITTED
      │    → Procedure → Info
      │         ├─ confirmed fact 충돌 → CONFLICT
      │         └─ 충돌 없음 → Support → Supervisor → Review
      └─ SUPPORT_REFRESH
           → Support → Supervisor → Review

Review PASS                    → REVIEWED_PLAN
Review REVISE                  → 지정 dependency부터 재실행
구성요소 실패·재작업 상한 소진 → SAFE_FAILURE
```

`CONFLICT`는 서비스 프로세스 종료가 아니다. confirmed Case fact와 새 명시적 입력이 충돌했을 때 잘못 덮어쓰지 않도록 **해당 run만** 끝내고 caller에게 확인 요청을 지시하는 typed 결과다. 사용자 확인 결과를 받아 적용·재실행하는 trigger와 node는 현재 없다.

현재 Graph 전체를 “항상 하나의 선형 순서”라고 표현하면 정확하지 않다. Info conflict와 구성요소 실패는 조기 종료되고, Review의 권고 target에 따라 재작업 시작점이 달라진다. 다만 정상 1차 경로와 재작업 시작점 선택은 Supervisor가 아니라 Graph 코드가 담당한다.

### 목표와 현재 구현의 차이

| 비교 항목 | 목표 구조 | 현재 feature 브랜치 |
|---|---|---|
| 전역 오케스트레이션 | Supervisor가 필요한 Agent·Tool을 선택 | Graph 코드가 trigger별 경로를 선택 |
| 최초 실행 위치 | Supervisor가 Case를 해석한 뒤 선택 호출 | Procedure 또는 Support에서 시작 |
| 하위 구성요소 노출 | Supervisor에 Agent-as-Tool/Tool로 노출 | `AgentGraph`가 runner를 직접 보유·호출 |
| Review 재작업 | Supervisor가 문제와 상태를 보고 재호출 대상 결정 | Review 권고 target을 Graph가 재실행 경로로 변환 |
| Decision 내용 | Supervisor가 decision variant별 Blocker·Next Action·질문을 결정 | Supervisor가 결정 — 목표와 일치 |
| 정상 초안 Review | 항상 필수 | 항상 필수 — 목표와 일치 |
| 전체 run deadline | 실행기가 전체 예산을 강제 | 없음 — 호출별 timeout과 LangGraph recursion limit만 있음 |
| DB·인증·저장 | Agent 실행 경계 밖 | 미구현, 실행 경계 밖 |

따라서 현재 `AgentGraph` 구현을 사용자가 확정한 최종 Agent 아키텍처로 설명하지 않는다. 목표 구조가 구현됐다고 판단하려면 Supervisor planning schema뿐 아니라 최초 호출 선택, Review 뒤 재계획, 호출 allowlist·횟수·전체 deadline을 강제하는 router와 회귀 테스트가 모두 실제 실행 경로에 추가돼야 한다.

## 5. 구성요소별 책임

### 5.1 실행 인프라

| 구현 요소 | 현재 책임 | 구분 |
|---|---|---|
| LangGraph `StateGraph` | node와 조건부 edge 실행, state 전달 | 외부 프레임워크 구성요소 |
| 프로젝트 클래스 `AgentGraph` | `StateGraph` 구성·compile, 입력 전달, 결과 수집, Review 재작업, 반복 상한, safe failure 처리 | 현재 standalone 실행기; 별도 Agent 아님 |
| `TraceSink` | run/call/component/status/latency/attempt/error metadata 경계 | 기본 구현은 `NullTraceSink`; 현재 model·token 값은 채우지 않고 cost 필드와 Langfuse 전송도 없음 |

### 5.2 Agent

| Agent | 현재 책임 | 하지 않는 일 |
|---|---|---|
| Supervisor Agent | Procedure·Info·Support 결과를 종합해 Decision과 변경 후보·grounded claim 초안 생성. `ACTION`이면 Blocker·Next Action 각 1개, `NEEDS_MORE_INFO`이면 Blocker 1개·질문 1개 이상·Next Action 없음 | 현재 하위 구성요소 선택·직접 호출, Evidence 생성, Review 우회, DB 저장; `CASE_COMPLETE`는 현재 도달 불가 |
| 정보분석 Agent | 비식별 입력·snapshot·공식 절차 원문을 분석해 사실·진행 관측·canonical 절차 finding·충돌·누락·질문 후보 생성 | 인터넷 조회, 웹 제목으로 canonical step 생성, Case 직접 변경 |
| 지원금 Agent | Case 사실과 미저장 fact 후보를 생성 시 deep-copy한 read-only `ReviewedSupportCatalog` snapshot에 비교 | raw 공고 수집, 실제 자격·선정·수급 확정, 신청 상태 변경; `CHECK_SPECIFIC` 입력은 직접 호출만 가능하고 현재 Graph는 만들지 않음 |

### 5.3 Tool

| Tool | 현재 책임 | 현재 연결 상태 | 하지 않는 일 |
|---|---|---|---|
| 절차조회 Tool | 공식 URL 선택·발견, 안전한 원문 fetch, 문서·Evidence 정규화 | 현재 Graph에서 Procedure 단계로 사용 | 원문 의미 분석, Case 적용 여부·완료 여부·우선순위 결정 |
| Review Tool | source digest·provenance·snapshot·Supervisor 초안 독립 검수, `PASS/REVISE`와 이유 반환 | Supervisor 초안 뒤 필수 사용 | 새 근거 검색, 초안 직접 수정, 저장 |
| 기업마당 공고조회 Tool | 기업마당 API에서 raw 공고 후보와 `OFFICIAL_API` Evidence 생성 | 구현·테스트됐으나 현재 Graph·catalog 발행 흐름 미연결 | raw 공고 자동 승인, 지원 자격 판정 |

## 6. 주요 데이터 흐름

### 6.1 절차조회 → 정보분석

```text
ProcedureLookupInput
  → 절차조회 Tool
  → 직접 fetch한 공식 원문 documents + Evidence
  → 실행기가 InfoAnalysisInput에 동일 call ID와 함께 주입
  → 정보분석 Agent가 Case 문맥에서 procedure finding 생성
```

절차조회 Tool은 정보분석 Agent에서 파생되지 않으며 정보분석 Agent를 호출하지도 않는다. Tool은 원문을 조회하고, Agent가 그 원문을 분석한다. 검색 결과의 title·snippet은 URL 발견 metadata일 뿐 Evidence가 아니다.

### 6.2 지원금

```text
현재 standalone: 합성 ReviewedSupportCatalog → 지원금 Agent

별도 구현: 기업마당 API → raw candidate + Evidence
                              └─ 현재 catalog·Graph와 미연결
```

raw 공고와 검수 catalog를 분리하는 이유는 공고 문구를 바로 Boolean 자격조건으로 오해하거나 미검수 자료가 확정 결과로 승격되는 것을 막기 위해서다.

### 6.3 Supervisor → Review

```text
Procedure·Info·Support 결과
  → call ID + output digest가 있는 ReviewSourceResult
  → SupervisorDraft
  → snapshot + source results + draft를 묶은 ReviewSubject
  → ReviewResult
       ├─ PASS   → 실행기가 matching ReviewProof 생성
       └─ REVISE → 이유·문제 위치·재작업 권고 대상 반환
```

`digest`는 Review가 확인한 정확한 객체가 이후 바뀌지 않았는지 검사하는 SHA-256 값이다. 초안이나 source가 바뀌면 새 subject와 새 Review가 필요하다.

## 7. 재시도와 재작업

의미 출력 재생성과 HTTP 전송 재시도는 서로 다른 층이다. 한 번의 의미 출력 시도 안에서도 일시적인 HTTP 실패가 재시도될 수 있으므로 비용과 호출량을 계산할 때 둘을 곱해 봐야 한다.

| 경계 | 기본값·허용 상한 | 정확한 동작 |
|---|---|---|
| Info local 의미 검증 | 기본·최대 총 3회 | provider schema 변환 뒤 semantic·grounding 검증 실패 시 Agent가 새 의미 출력을 요청 |
| Support local 의미 검증 | 고정 총 3회 | catalog ID·조건·Evidence semantic 검증 실패 시 Agent가 새 의미 출력을 요청 |
| Supervisor local 의미 검증 | 기본·최대 총 3회 | decision·claim·provenance 검증 실패 시 재생성; 모두 실패해도 Info의 안전한 missing-field 질문이 있으면 결정론적 `NEEDS_MORE_INFO` fallback 가능 |
| 공통 LLM HTTP 전송 | 기본 재시도 2회, 허용 0~4회 | 한 provider 요청당 기본 최대 3번 HTTP 시도; 호출별 기본 timeout 45초 |
| Review 의미 출력 | 기본 총 2회, 허용 1~3회 | Review 출력 계약 실패 시 새 의미 출력을 요청 |
| Review 전용 provider 전송 | 의미 출력마다 기본 재시도 1회, 허용 0~2회 | 한 Review 의미 출력당 기본 최대 2번 provider 요청 |
| Procedure 검색·원문 fetch | 각 요청 기본 재시도 1회, 허용 0~4회 | 각 검색 요청과 각 공식문서 fetch에 적용; 요청별 기본 timeout 8초, 전체 lookup 기본 60초 |
| LangGraph Review 재작업 | 수정 최대 2회 | 최초 Review를 포함해 총 Review round 최대 3회; 원인상 가장 앞선 구성요소부터 다시 실행 |
| 전체 Agent run | recursion limit 32 | 현재 Graph 전체 wall-clock deadline은 없음; 호출별 timeout만 존재 |

Review가 `REVISE`를 반환하면 현재 실행기는 다음 순서에서 가장 앞선 권고 target부터 재실행한다.

| 권고 target | 현재 재실행 범위 |
|---|---|
| Procedure | Procedure → Info → Support → Supervisor → Review |
| Info | Info → Support → Supervisor → Review |
| Support | Support → Supervisor → Review |
| Supervisor 또는 target 없음 | Supervisor → Review |

상한 소진이나 예외는 성공처럼 포장하지 않고 `SAFE_FAILURE`로 반환한다.

## 8. 현재 코드가 강제하는 안전 조건

- public Pydantic schema는 주요 scalar에 `StrictStr`·`StrictInt`·`StrictBool`을 사용하고, 선언되지 않은 field와 timezone 없는 datetime을 거부한다.
- UUID·시각 같은 runtime 값은 LLM 출력에서 제외하고 코드가 주입한다.
- Case snapshot은 실행 중 read-only로 취급하고 시작·종료 digest를 비교한다.
- LLM 출력은 provider 형식 검증 뒤 구성요소별 의미·provenance 검증을 다시 거친다.
- unknown/stale Evidence로 확정형 기한·자격·법률·절차 claim을 만들지 않는다.
- 웹 원문만으로 실제 절차 진행을 `COMPLETED`로 바꾸지 않는다.
- 사용자 입력이나 검색 결과 제목으로 canonical ID를 만들지 않는다.
- Review되지 않은 초안과 mutation은 `REVIEWED_PLAN`으로 반환하지 않는다.
- 외부 문서와 사용자 입력은 실행 명령이 아니라 untrusted data로 취급한다.

별도 업무 Rule 엔진은 두지 않는다. 업무 판단은 Agent와 Review가 하되, ID·schema·digest·provenance·호출 권한·반복 상한처럼 결정적으로 검증 가능한 조건은 코드가 강제한다.

## 9. AI 후속 구현

### 9.1 Supervisor 주도 오케스트레이션

- Supervisor planning 입출력 schema를 정의한다.
- 현재 실행 상태에서 필요한 Agent·Tool과 호출 이유를 Supervisor가 선택하게 한다.
- LangGraph router는 허용 dependency, 호출 횟수, deadline 안에서만 계획을 실행한다.
- Review `REVISE` 뒤 재호출 대상 최종 선택도 Supervisor 책임으로 옮긴다.
- 고정 route와 동적 route의 정상·거부·loop-limit 회귀 테스트를 만든다.

### 9.2 공식 데이터·crawler·RAG

- 승인된 공식 출처만 bounded API connector/crawler로 수집한다.
- parser·정규화·chunking 뒤 source version·hash·locator를 보존한다.
- 검수 corpus와 immutable `ReviewedSupportCatalog`를 발행한다.
- Chroma index·official-only retriever·Evidence adapter를 연결하고 retrieval 평가를 통과시킨다.

구현 순서와 완료 조건은 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)를 따른다.

### 9.3 Langfuse 관측성

- 현재 `TraceSink` 경계에 Langfuse adapter를 구현한다.
- prompt·사용자 입력·credential masking과 retention·access policy를 먼저 확정한다.
- 실제 token·cost·latency·오류·Review 반송 trace 전송과 테스트가 끝난 뒤에만 사용 중으로 표시한다.

## 10. 완료 판정 기준

| 범위 | 완료라고 말할 조건 |
|---|---|
| Agent 내부 계약 | 코드 존재 + validator/contract test 통과 + 실제 호출 경로 존재 |
| 외부 API adapter | 코드·테스트 + 필요한 credential로 제한 실측. HTTP 200과 실제 Case 연결은 별도 기록 |
| crawler/RAG | 수집·파싱·버전·검수·index·retrieval·Evidence 연결과 평가 통과 |
| Supervisor 오케스트레이션 | planning schema + bounded router + Review 재계획 경로 + 회귀 테스트 통과 |
| Langfuse | adapter + masking 정책 + token·cost·latency 실전송 검증 |
| 실제 사용자 Case 연동 | 인증된 read/write, 동시성 보호, 검수 결과 저장과 read-back 통합 검증. 현재 AI standalone 범위 밖 |

## 11. 구현 근거

| 설명 | 저장소 근거 |
|---|---|
| LangGraph import, `AgentGraph` 클래스, node·조건부 edge | [`graph.py`](../backend/app/agent/graph.py) |
| 실행 state | [`state.py`](../backend/app/agent/state.py) |
| Agent/Tool 입출력과 component enum | [`schemas.py`](../backend/app/agent/schemas.py) |
| Supervisor 현재 책임 | [`supervisor/`](../backend/app/agent/supervisor/) |
| 정보분석·지원금 책임 | [`info_agent/`](../backend/app/agent/info_agent/), [`support_agent/`](../backend/app/agent/support_agent/) |
| 절차조회·Review 책임 | [`procedure_tool/`](../backend/app/agent/procedure_tool/), [`review_tool/`](../backend/app/agent/review_tool/) |
| standalone fixture·진입점 | [`fixtures.py`](../backend/app/agent/fixtures.py), [`cli.py`](../backend/app/agent/cli.py) |
| metadata trace 경계 | [`tracing.py`](../backend/app/agent/tracing.py) |
| 현재 동작 검증 | [`backend/tests/agent/`](../backend/tests/agent/) |

현재 구현 사실은 코드와 테스트가 Markdown보다 우선한다. 목표 구조는 현재 구현 상태와 섞어 완료로 표시하지 않는다.
