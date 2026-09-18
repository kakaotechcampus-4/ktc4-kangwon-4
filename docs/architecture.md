# RE:BORN Agent 아키텍처

> 소유: AI
>
> 기준일: 2026-09-15
>
> 이 문서의 책임: 현재 Agent 실행 구조, 목표 구조, 구성요소별 책임과 데이터 전달 방향

이 문서는 **누가 무엇을 호출하고 어떤 결과를 다음 단계에 전달하는지** 설명한다. 정확한 필드와 검증 규칙은 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md)를 따른다.

## 1. 먼저 보는 결론

- 현재 실행에는 LangGraph의 `StateGraph`를 사용한다.
- `AgentGraph`는 `StateGraph`를 구성하고 실행하는 프로젝트 내부 Python 클래스다. 별도 Agent가 아니다.
- Agent는 Supervisor, 정보분석, 지원금의 3개다.
- Tool은 절차조회, Review, 기업마당 공고조회의 3개다.
- 기업마당 공고조회 Tool은 구현과 단위 테스트는 끝났지만 현재 전체 실행 흐름에는 연결되지 않았다.
- 현재 호출 순서는 Supervisor가 정하지 않는다. `AgentGraph` 코드가 실행 이유와 앞 단계 결과에 따라 제한된 경로를 선택한다.
- 목표는 Supervisor가 필요한 Agent·Tool을 선택하는 구조지만, 이 동적 계획 기능은 아직 구현되지 않았다.
- 실제 사용자 Case 조회·저장과 DB 처리는 현재 Agent 실행 범위에 없다.
- Lang 계열 프레임워크 중 현재 실행에 직접 사용하는 것은 LangGraph다. LangChain 실행 코드는 아직 없다. Langfuse는 credential이 설정된 경우에만 metadata를 전송한다.

### 이 문서에서 자주 쓰는 말

- **실행 이유(trigger):** Case 생성, 사용자 결과 제출, 지원금 재평가처럼 Agent 실행을 시작한 이유
- **실행(run):** 입력 하나를 받아 최종 결과 하나를 반환할 때까지의 전체 과정
- **Case snapshot:** 한 번의 실행이 기준으로 삼는 특정 시점의 Case 읽기 상태
- **Evidence:** 판단이 어떤 사용자 입력이나 공식 원문에 근거했는지 추적하는 기록
- **digest:** Review한 내용이 이후 바뀌지 않았는지 확인하는 SHA-256 값
- **검수된 계획 후보:** Review를 통과한 AI 결과. DB 저장 완료나 현실 업무 완료를 뜻하지 않음

## 2. 현재 구현된 실행 구조

현재 `AgentGraph`는 실행 이유에 따라 시작점을 정하고, 각 Agent·Tool의 반환값으로 다음 호출 입력을 만든다. Agent와 Tool끼리는 서로 직접 호출하지 않는다.

```text
CASE_CREATED | RESULT_SUBMITTED
  → 절차조회 Tool
  → 정보분석 Agent
      ├─ 기존 확정 사실과 새 입력이 충돌함 → CONFLICT
      └─ 충돌 없음
           → 지원금 Agent
           → Supervisor Agent
           → Review Tool
                ├─ PASS   → ReviewProof → REVIEWED_PLAN
                ├─ REVISE → 권고된 앞 단계부터 재실행
                └─ 실패·상한 소진 → SAFE_FAILURE

SUPPORT_REFRESH
  → 지원금 Agent → Supervisor Agent → Review Tool
```

### 최종 결과의 의미

#### `REVIEWED_PLAN`

Review가 정확히 같은 Case snapshot, 선행 결과와 Supervisor 초안을 검수해 통과시킨 결과다. **검수된 계획 후보**이며 저장 완료 결과가 아니다.

#### `CONFLICT`

서비스나 Agent 프로세스를 종료하지 않는다. 기존에 확정된 Case 사실과 새 입력이 충돌할 때 잘못 덮어쓰지 않도록 **현재 실행만** 끝내고 사용자 확인이 필요하다고 알린다.

사용자 확인을 받아 충돌 값을 적용하고 다시 실행하는 경로는 아직 없다.

#### `SAFE_FAILURE`

구성요소 오류, 검증 실패, Review 재작업 상한 소진 또는 한 실행의 LLM 호출 총량 상한 소진을 성공처럼 반환하지 않는 안전 실패 결과다. 호출 총량 상한을 넘은 경우는 `LOOP_LIMIT_REACHED`로 끝낸다.

#### `NEEDS_MORE_INFO`

최상위 오류가 아니라 Supervisor가 만드는 decision의 한 종류다. 현재 정보만으로 안전한 다음 행동을 정할 수 없을 때 Blocker와 사용자 질문을 만든다. Review를 통과하면 `REVIEWED_PLAN` 안에 포함된다.

## 3. 구성요소별 책임

### 3.1 실행기

#### LangGraph `StateGraph`

- **구분:** 외부 프레임워크가 제공하는 그래프 구성 객체
- **책임:** 실행 단계와 조건 분기 수행, 실행 상태 전달

#### 프로젝트 클래스 `AgentGraph`

- **구분:** 현재 standalone 실행기. 별도 Agent가 아님
- **책임:** `StateGraph` 구성·실행, 다음 호출 입력 구성, 결과 수집, Review 재작업, 반복 상한, 실행 시작 시 LLM 호출 총량 counter 초기화와 안전 실패 처리
- **하지 않는 일:** 실제 사용자 Case 조회·저장, 인증, DB 동시성 제어
- **현재 전제:** LLM 호출 총량 counter는 client와 공유하는 단일 객체다. 한 프로세스가 여러 실행을 동시에 처리하는 구성은 아직 전제하지 않는다.

#### `TraceSink`

- **책임:** 실행 ID, 호출 ID, 구성요소, 상태, 지연 시간, 시도 횟수와 오류를 받을 수 있는 추적 경계
- **현재 상태:** 기본값은 아무 곳에도 전송하지 않는 `NullTraceSink`다. `LANGFUSE_PUBLIC_KEY`와 `LANGFUSE_SECRET_KEY`가 모두 설정되면 `LangfuseTraceSink`로 바뀐다. 두 키가 있어도 SDK import나 client 생성이 실패하면 조용히 `NullTraceSink`로 남는다. 전송이 켜졌을 때 구성요소별 상태·지연 시간·시도 횟수·model·token 수를 전송한다. prompt 원문, evidence와 사용자 입력은 전송 대상에 포함하지 않는다. 비용 금액은 계산하지 않는다.

### 3.2 Agent

#### 정보분석 Agent

- **받는 내용:** 비식별 사용자 입력, Case snapshot, 절차조회 결과
- **반환하는 내용:** 사실 변경 후보, 절차 진행 관측, 공식 절차 분석 결과, 충돌, 누락 정보, 사용자 질문 후보
- **하지 않는 일:** 인터넷 조회, 검색 제목으로 절차 ID 생성, Case 직접 변경

#### 지원금 Agent

- **받는 내용:** Case 사실, 아직 저장되지 않은 사실 후보, 생성 시 주입된 `ReviewedSupportCatalog`
- **반환하는 내용:** 지원사업별 조건 비교, 추가로 확인할 Case 정보와 불확실성
- **하지 않는 일:** raw 공고 수집, 실제 자격·선정·수급 확정, 신청 상태 변경
- **현재 제한:** `CHECK_SPECIFIC` 입력은 처리할 수 있지만 `AgentGraph`가 해당 경로를 만들지 않는다.

#### Supervisor Agent

- **받는 내용:** 현재 실행 경로에서 수집된 Procedure·Info·Support 결과와 Case snapshot. `SUPPORT_REFRESH`에서는 Support 결과만 받을 수 있음
- **반환하는 내용:** 현재 decision, Blocker, Next Action, 사용자 질문, 검수 전 변경 후보와 근거가 연결된 문장
- **하지 않는 일:** 현재 하위 Agent·Tool 선택, Evidence 생성, Review 우회, DB 저장
- **현재 제한:** `CASE_COMPLETE` 타입은 있지만 정상 실행에서 도달할 수 없다.

### 3.3 Tool

#### 절차조회 Tool

- **받는 내용:** 폐업 절차 조회어, 기준일, 공식 출처만 허용하는 정책
- **반환하는 내용:** 직접 가져온 공식 원문, 검색 처리 요약, 경고와 공식 문서 Evidence
- **하지 않는 일:** 원문 의미 분석, 사용자에게 적용되는 절차 판단, 실제 완료 여부 판단

#### Review Tool

- **받는 내용:** Case snapshot, 선행 결과, 각 결과의 digest, Supervisor 초안
- **반환하는 내용:** `PASS` 또는 `REVISE`, 판정 이유, 문제 위치, 누락 Evidence와 권고 재작업 대상
- **하지 않는 일:** 새 근거 검색, 초안 직접 수정, 결과 저장

#### 기업마당 공고조회 Tool

- **받는 내용:** 검색어와 최대 결과 수
- **반환하는 내용:** 기업마당 API의 검수 전 raw 공고 후보와 공식 API Evidence
- **현재 상태:** 독립 호출과 단위 테스트는 가능하지만 `AgentGraph`와 catalog 발행 흐름에는 연결되지 않음
- **하지 않는 일:** raw 공고 자동 승인, 지원 자격 판정

## 4. 구성요소 사이의 데이터 전달

### 4.1 절차조회 결과를 정보분석에 전달

1. 절차조회 Tool이 공식 URL을 찾고 원문을 직접 가져온다.
2. Tool은 원문과 Evidence가 들어 있는 `ProcedureLookupResult`를 반환한다.
3. `AgentGraph`가 이 결과와 호출 ID를 `InfoAnalysisInput`에 넣는다.
4. 정보분석 Agent가 사용자 Case 문맥에서 원문 의미를 분석한다.

검색 결과의 제목과 짧은 설명은 URL을 찾는 데만 사용한다. 공식 원문을 직접 가져오기 전에는 Evidence가 아니다.

### 4.2 지원사업 공고와 지원금 판단을 분리

- 현재 standalone 지원금 판단은 합성 `ReviewedSupportCatalog`를 사용한다.
- 기업마당 Tool은 실제 API에서 raw 공고 후보를 가져올 수 있다.
- raw 공고를 검수 catalog로 발행하는 과정이 없어 두 기능은 아직 연결하지 않았다.

이 경계를 두는 이유는 공고 문구를 바로 자격조건으로 단정하거나 미검수 자료가 확정 결과로 승격되는 것을 막기 위해서다.

### 4.3 Supervisor 초안을 Review에 전달

1. `AgentGraph`가 선행 결과에 호출 ID와 output digest를 묶는다.
2. Supervisor가 선행 결과를 종합해 `SupervisorDraft`를 만든다.
3. `AgentGraph`가 Case snapshot, 선행 결과와 초안을 하나의 `ReviewSubject`로 묶는다.
4. Review Tool이 `PASS` 또는 `REVISE`와 이유를 반환한다.
5. `PASS`이면 `AgentGraph`가 같은 검수 대상을 가리키는 `ReviewProof`를 만든다.

초안이나 선행 결과가 바뀌면 digest도 달라지므로 이전 Review 결과를 재사용할 수 없다.

## 5. 목표 구조와 현재 구조의 차이

### 목표: Supervisor가 호출 계획을 결정

- Supervisor가 Case를 먼저 해석하고 필요한 Agent·Tool만 선택한다.
- 정보분석 Agent와 지원금 Agent는 Supervisor가 호출할 수 있는 하위 Agent로 제공한다.
- 절차조회 Tool은 필요할 때 선택한다.
- Supervisor가 결과 충분성, 사용자 질문과 재호출 대상을 결정한다.
- LangGraph 실행기는 허용된 구성요소, 호출 횟수와 전체 실행 시간 안에서 계획을 수행한다.
- 모든 정상 초안은 Review Tool을 반드시 거친다.

### 현재: `AgentGraph` 코드가 실행 경로를 결정

- Case 생성·결과 제출은 절차조회부터 시작한다.
- 지원금 재평가는 지원금 Agent부터 시작한다.
- Review가 `REVISE`를 반환하면 `AgentGraph`가 권고 대상을 재실행 경로로 바꾼다.
- Supervisor는 Blocker와 Next Action 초안은 만들지만 호출 계획은 만들지 않는다.
- 호출별 timeout, LangGraph 반복 제한과 실행당 LLM 호출 횟수 상한은 있지만 전체 실행 시간 제한은 없다. 호출 횟수 상한은 시간이 아니라 횟수만 막는다.

따라서 현재 구현을 목표 아키텍처가 완료된 상태로 설명하지 않는다. 목표 완료에는 Supervisor planning schema, 제한된 router, Review 뒤 재계획, 전체 실행 시간 제한과 회귀 테스트가 모두 필요하다.

## 6. 재시도와 재작업

LLM이 의미상 잘못된 결과를 내서 다시 생성하는 것과 HTTP 요청 자체가 실패해 다시 전송하는 것은 별도다. 다만 두 가지 모두 한 실행의 LLM 호출 총량 상한을 함께 소비한다.

### 의미 결과 재생성

- **정보분석:** 최초 시도를 포함해 최대 3회
- **지원금:** 최초 시도를 포함해 총 3회
- **Supervisor:** 최초 시도를 포함해 최대 3회. 모두 실패해도 안전한 누락 정보 질문이 있으면 결정론적 `NEEDS_MORE_INFO`를 만들 수 있음
- **Review:** 기본 총 2회, 설정 가능 범위 1~3회

위 횟수는 구성요소별 상한이다. 실행당 LLM 호출 총량 상한이 먼저 소진되면 이 횟수에 도달하기 전에 중단된다.

### 외부 요청 재전송

- **Agent LLM 요청:** 기본 재시도 2회, 설정 가능 범위 0~4회, 요청별 기본 timeout 45초. 정보분석·지원금·Review는 공유 client를 쓰고, `SUPERVISOR_*` 환경변수가 설정되면 Supervisor만 다른 provider·model의 전용 client를 쓴다. 두 client 모두 같은 기본값을 쓰며, 재전송도 실행당 호출 총량 상한을 소비한다.
- **Review provider 요청:** 의미 결과 한 번마다 기본 재시도 1회, 설정 가능 범위 0~2회
- **절차 검색·원문 조회:** 요청마다 기본 재시도 1회, 설정 가능 범위 0~4회, 요청별 기본 timeout 8초, 전체 조회 기본 timeout 60초

### 실행당 LLM 호출 총량

- 한 실행에서 쓸 수 있는 LLM 호출 총 횟수는 기본 40회다. 이 숫자는 구성요소별 시도가 아니라 **실제 HTTP 호출 수**를 센다. 의미 시도 한 번이 HTTP 재시도까지 포함하므로, 구성요소별 상한을 모두 소진하면 기본 설정에서 57회가 나온다(정보분석 3×3 + 지원금 3×3 + Review 3라운드 각각 Supervisor 3×3 + Review 2×2). 재작업이 정보분석·지원금까지 되돌리면 더 커진다.
- 따라서 40회는 그 상한을 보장하는 값이 아니라 **그보다 낮게 잡은 비용 상한**이다. 구성요소별 상한이 남아 있어도 예산이 먼저 끊을 수 있고, 그것이 의도다.
- 정보분석·지원금·Supervisor·Review가 하나의 counter를 공유한다. Supervisor가 다른 provider·model을 쓰더라도 같은 counter를 쓴다.
- 의미 결과 재생성과 외부 요청 재전송 모두 실제 HTTP 호출 직전에 1회씩 소비한다.
- `AgentGraph`가 실행 시작 시 counter를 되돌리므로 상한은 실행 단위다.
- 상한을 넘으면 결과를 더 만들지 않고 `LOOP_LIMIT_REACHED` 코드의 `SAFE_FAILURE`로 끝낸다.
- 횟수 제한이며 시간 제한이 아니다.

### Review 재작업

수정은 최대 2회이며 최초 Review를 포함한 총 Review 횟수는 최대 3회다.

- Procedure 문제: Procedure부터 다시 실행
- Info 문제: Info부터 다시 실행
- Support 문제: Support부터 다시 실행
- Supervisor 문제 또는 대상 없음: Supervisor부터 다시 실행

각 경로는 필요한 뒤 단계를 다시 거쳐 Review로 돌아간다. 상한 소진이나 예외는 `SAFE_FAILURE`로 반환한다.

## 7. 현재 코드가 강제하는 안전 조건

- 선언되지 않은 입력 필드와 timezone 없는 시각을 거부한다.
- 숫자·문자열·boolean의 잘못된 암시적 변환을 제한한다.
- UUID와 생성 시각처럼 코드가 책임지는 값은 LLM이 만들지 않는다.
- 한 실행 안에서 Case snapshot이 바뀌었는지 digest로 확인한다.
- LLM 형식 검증 뒤 의미와 출처 연결을 다시 검증한다.
- 최신성이 오래됐거나 확인되지 않은 Evidence로 기한·자격·법률·절차를 확정하지 않는다.
- 공식 웹 원문만으로 사용자의 실제 절차 진행을 `COMPLETED`로 바꾸지 않는다.
- 사용자 입력이나 검색 결과 제목으로 새로운 canonical ID를 만들지 않는다.
- Review를 통과하지 않은 초안과 변경 후보를 `REVIEWED_PLAN`으로 반환하지 않는다.
- 한 실행의 LLM 호출 총 횟수가 상한을 넘으면 계속 생성하지 않고 안전 실패로 끝낸다.
- 외부 문서와 사용자 입력을 실행 명령이 아니라 검증이 필요한 데이터로 취급한다.

업무 판단은 Agent와 Review가 담당한다. 반면 ID, schema, digest, 출처 연결, 호출 권한과 반복 상한처럼 코드로 확실히 검사할 수 있는 조건은 코드가 강제한다.

## 8. 아직 구현되지 않았거나 연결되지 않은 것

### 구현됐지만 전체 실행에 미연결

- 기업마당 raw 공고조회 Tool의 독립 호출
- 지원금 Agent의 `CHECK_SPECIFIC` 입력 처리

### 타입만 있거나 현재 도달할 수 없음

- `ComponentRequest`, `ComponentSuccess`, `ComponentFailure`
- `CASE_COMPLETE`
- `CaseStatusChangeCandidate`
- 사용자 확인을 반영하는 `CONFIRMED_CONFLICT`

### 후속 AI 구현 대상

- 기업마당 raw 공고 검수, `ReviewedSupportCatalog` 발행과 `AgentGraph` 연결
- `AgentGraph`가 `CHECK_SPECIFIC` 입력을 만드는 실행 경로
- Supervisor 주도 동적 호출 계획과 제한된 router
- 사용자 확인 후 conflict 재실행
- 승인된 공식 출처 crawler와 RAG
- 전체 실행 시간(wall-clock) 제한 — 실행당 LLM 호출 횟수 상한만 구현했고 시간 기반 제한은 없다
- Langfuse 비용 금액 산출과 masking 정책 검증

crawler·RAG의 단계와 완료 조건은 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)를 따른다.

## 9. 완료라고 판단하는 기준

- **Agent 공개 호출 계약:** 코드, validator, 계약 테스트와 실제 호출 경로가 모두 있어야 함
- **외부 API adapter:** 코드·테스트뿐 아니라 필요한 credential을 사용한 제한 실측이 있어야 함
- **crawler·RAG:** 수집, 파싱, version, 검수, index, 검색, Evidence 연결과 평가를 모두 통과해야 함
- **Supervisor 오케스트레이션:** planning schema, 제한된 router, Review 재계획과 회귀 테스트가 있어야 함
- **Langfuse:** adapter는 구현했고, masking 정책 승인과 실제 전송 검증이 남아 있음
- **실제 사용자 Case 연동:** 인증된 읽기·쓰기, 동시성 보호, 저장과 재조회 통합 검증이 있어야 함

HTTP 200, 검색 성공, Agent 실행 성공, 실제 Case 연동 성공은 서로 다른 완료 조건으로 기록한다.

## 10. 관련 문서와 구현 근거

### 관련 문서

- **Agent·Tool의 정확한 입력·출력:** [`agent-tool-io-schema.md`](./agent-tool-io-schema.md)
- **standalone 실행법과 실제·합성 데이터:** [`agent-standalone-runtime-requirements.md`](./agent-standalone-runtime-requirements.md)
- **공식 API, crawler, RAG:** [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)
- **외부 연동 공동 검토 요청:** [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)
- **라이브러리 선언과 실제 사용 여부:** [`tech-stack.md`](./tech-stack.md)
- **DB 팀의 현재 스키마 설계:** [`schema/schema_table.md`](./schema/schema_table.md), [`schema/ERD.png`](./schema/ERD.png)

`interface-spec.md`는 이전 링크를 위한 안내 파일이다. `schema/schema_table.md`와 `ERD.png`는 `develop`에서 관리하는 DB 설계 문서이며, 실제 migration·ORM 구현 완료나 AI 내부 schema와의 필드 mapping 확정을 뜻하지 않는다. AI와 DB 사이의 차이는 외부 연동 공동 검토 요청서에서 합의한다.

### 구현 근거

- **LangGraph 실행기:** [`graph.py`](../backend/app/agent/graph.py), [`state.py`](../backend/app/agent/state.py)
- **공통 schema와 결과 타입:** [`schemas.py`](../backend/app/agent/schemas.py)
- **Agent:** [`info_agent/`](../backend/app/agent/info_agent/), [`support_agent/`](../backend/app/agent/support_agent/), [`supervisor/`](../backend/app/agent/supervisor/)
- **Tool:** [`procedure_tool/`](../backend/app/agent/procedure_tool/), [`review_tool/`](../backend/app/agent/review_tool/)
- **standalone fixture와 실행 진입점:** [`fixtures.py`](../backend/app/agent/fixtures.py), [`cli.py`](../backend/app/agent/cli.py)
- **추적 경계:** [`tracing.py`](../backend/app/agent/tracing.py)
- **테스트:** [`backend/tests/agent/`](../backend/tests/agent/)

현재 구현 사실은 코드와 테스트가 Markdown보다 우선한다. 목표 구조를 현재 구현 완료 상태와 섞어 표시하지 않는다.
