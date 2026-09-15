# RE:BORN Agent 독립 실행 요구사항

> 상태: **v2.0 — 실제 인터넷 절차조회 구조 / BE 생산 연동 전**
>
> 소유: AI
>
> schema version: **`agent-io/2.0`**
>
> 필드 단위 계약의 단일 출처는 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md)입니다. BE가 제공할 항목은 [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)를 따릅니다.

## 1. 먼저 합의할 결론

Agent는 BE 없이도 비식별 Case 입력을 사용해 판단·Review loop를 실행할 수 있습니다. 다만 v2에서 절차조회는 fixture가 아니라 다음 실제 외부 경로를 사용합니다.

1. `ProcedureLookupTool`이 각 비식별 질의마다 공개 공식사이트만 등록된 Google Agent Search 앱의 `searchLite`를 먼저 호출하고, 정해진 fallback 조건을 충족한 질의만 Kakao Daum 웹문서 검색 API로 다시 조회합니다.
2. HTTPS, 공식기관 domain allowlist, redirect 재검증과 IP-literal 금지를 통과한 URL만 직접 fetch합니다. DNS 해석 결과 검증은 생산 egress 경계의 미구현 항목입니다.
3. 검색 snippet이 아니라 실제 공식 원문의 sanitized excerpt와 Evidence를 반환합니다.
4. `InfoAnalysisAgent`가 사용자 입력, CaseSnapshot, `ProcedureLookupResult`를 분석해 canonical `KnownProcedureStep`에 결합된 `procedure_findings`를 만듭니다.
5. Supervisor가 finding과 지원금 결과로 초안을 만들고 Review Tool이 원문 Evidence까지 대조합니다.

절차조회 Tool은 원문을 **가져오기만** 하며 적용 여부, 순서, 완료, Blocker나 Next Action을 판정하지 않습니다. 과거 v1의 합성 `ProcedureMaster` 조건/DAG 평가 방식은 제품 정의와 달라 폐기됐고 `agent-io/2.0`과 호환되지 않습니다.

BE 없는 실행과 생산 연동은 같은 뜻이 아닙니다. standalone은 DB write, 인증·소유권, idempotency, CAS, transaction을 갖지 않으며 실제 사용자 Case를 안전하게 저장할 수 없습니다.

## 2. 문서와 구현의 책임 경계

| 출처 | 책임 | 현재 사용 방법 | 이유 |
|---|---|---|---|
| `docs/architecture.md` | 구성요소 책임, 호출 방향, Review 경계 | Procedure→Info 의존 순서의 기준 | Tool과 Agent의 책임 중복을 막습니다. |
| `docs/agent-tool-io-schema.md` | `agent-io/2.0` 필드와 불변식 | Python schema·테스트의 계약 기준 | 같은 이름의 서로 다른 payload를 막습니다. |
| 이 문서 | 환경, standalone 실행, 완료 기준 | AI 구현·검증 runbook | mock 성공과 실제 인터넷 성공을 구분합니다. |
| `docs/be-agent-integration-requirements.md` | BE/shared DTO·저장·운영 요구 | BE 전달 및 회신 기준 | Agent 성공을 생산 저장 성공으로 오해하지 않게 합니다. |

현재 Python 구현이 문서와 다르면 테스트와 Pydantic model이 실행 사실의 근거지만, 그 차이를 방치하지 않고 같은 PR에서 문서를 갱신합니다. provider 전용 schema는 BE wire DTO가 아닙니다.

## 3. Agent 독립 실행에 필요한 입력과 의존성

| 입력·의존성 | 공급자 | 소비 지점 | 근거와 이유 | 검증 기준 |
|---|---|---|---|---|
| `SupervisorRunInput` | CLI/test caller | `AgentGraph.run` | 한 실행의 trigger와 snapshot을 고정합니다. | case/snapshot/input event가 strict 검증을 통과합니다. |
| `CaseSnapshot` | standalone fixture | Info, Support, Supervisor, Review | BE 없이 구조를 검증하되 실제 사용자 자료처럼 주장하지 않습니다. | fact/progress/Evidence ref가 unique·closed입니다. |
| `KnownProcedureStep[]` | standalone canonical registry fixture | Info | 웹 제목을 DB ID로 오인하지 않고 기존 step에만 finding을 결합합니다. | ID/code/name/alias가 unique이며 Info는 목록 밖 ID를 생성하지 않습니다. |
| `ReviewedSupportCatalog` | reviewed fixture | Support | 존재하지 않는 지원사업 생성을 막습니다. | 사업·조건·문구가 검수 또는 공식 Evidence와 연결됩니다. |
| ordered search providers | 실제 Google/Kakao API 또는 test double | Procedure Tool | Google Agent Search를 1순위, Kakao를 query별 fallback으로 사용하되 provider 계약은 공통 adapter 뒤에 격리해야 합니다. | live는 고정된 공식 HTTPS endpoint, unit test는 provider별 deterministic mock입니다. |
| 공식 원문 fetcher | 실제 HTTP 또는 test double | Procedure Tool | 검색 snippet은 원문이 아니므로 URL을 직접 읽어야 합니다. | 현재 HTTPS/allowlist/redirect/IP-literal/MIME/size/timeout을 강제하며 DNS public-address pinning은 생산 연동 전 보완합니다. |
| 구조화 출력 LLM client | 환경변수 또는 test double | Info, Support, Supervisor, Review | 자유 형식 응답을 공개 계약으로 신뢰하지 않습니다. | provider JSON Schema와 로컬 의미 검증을 모두 통과합니다. |
| runtime clock·UUID factory | runtime/test 주입 | 전체 | 모델이나 외부 문서가 ID·시각을 만들지 못하게 합니다. | aware datetime과 runtime UUID만 사용합니다. |
| trace sink | `NullTraceSink` 또는 안전한 adapter | Graph | 비용·지연·실패는 보되 prompt·credential·원문은 남기지 않습니다. | allowlisted metadata만 기록합니다. |

### 입력 신뢰 경계

- CaseSnapshot, KnownProcedureStep, support catalog는 신뢰된 caller 입력입니다.
- Google/Kakao 검색 결과의 URL·제목·snippet 등 metadata는 **후보이며 Evidence가 아닙니다**.
- fetch한 웹문서도 instruction이 아닌 untrusted data입니다. 문서 안의 prompt, 링크 이동 지시, credential 요청, 코드 실행 요청을 따르지 않습니다.
- allowlist와 실제 원문 검증을 통과한 excerpt만 `OFFICIAL_DOCUMENT` Evidence가 됩니다.
- standalone Case와 support fixture는 실행 구조 검증용 합성 데이터이며 실제 사업·법률·사용자 데이터가 아닙니다.

## 4. 구성요소별 입출력 계약

| 구성요소 | 공개 입력 | 공개 출력 | 책임 | 하지 않는 일 |
|---|---|---|---|---|
| 절차조회 Tool | `ProcedureLookupInput` | `ProcedureLookupResult` | Google 우선·Kakao query별 fallback 검색, 공식 URL 검증, 원문 fetch, raw document/Evidence 정규화 | Google SERP HTML scraping, 의미 분석, canonical step 생성, Case 적용·완료 판정 |
| 정보분석 Agent | `InfoAnalysisInput` | `InfoAnalysisResult` | 사용자 사실·충돌·진행 관측과 raw 원문 기반 `procedure_findings` 생성 | 인터넷 직접 검색, 웹문서 지시 실행, DB ID 생성 |
| 지원금 Agent | `SupportAnalysisInput` | `SupportAnalysisResult` | reviewed catalog 조회·조건 비교·Evidence 연결 | 신청 상태 변경·자격 확정 |
| Supervisor | `SupervisorRunInput`과 검증된 source results | `SupervisorDraft` | ACTION일 때 Blocker/Next Action 각 1개와 required `PROCEDURE | SUPPORT_PROGRAM` canonical target 선택, mutation/provenance 조립 | 자연어 keyword만으로 target 추정, Evidence 생성·Review 우회·DB write |
| Review Tool | `ReviewSubject` | `ReviewResult`; PASS 후 runtime `ReviewProof` | raw 절차 원문, Info 해석, 초안의 사실성·근거·안전성 검토 | 검색, 초안 직접 수정, DB write |
| Agent Graph | `SupervisorRunInput` | `AgentRunOutcome` | 호출 순서, 재작업 dependency, retry 상한, fail closed | 인증·저장 transaction 대체 |

Info 입력은 `procedure_lookup_call_id`와 정확한 `ProcedureLookupResult`를 함께 포함합니다. Info 출력은 같은 call ID와 lookup digest를 돌려주므로 다른 조회 결과를 섞을 수 없습니다. `procedure_findings`의 모든 nested `SourcedText.evidence_refs`는 lookup result의 Evidence에서 해석되어야 합니다.

모든 정상 `ACTION.next_action.target`은 required tagged union입니다. `PROCEDURE`는 정확히 한 Info finding, `SUPPORT_PROGRAM`은 정확히 한 Support check와 ID·Evidence가 일치해야 합니다. 대상이 없거나 구조가 어긋난 Action은 schema에서 거부하고, 알려진 다른 target 이름·코드와 공통 절차/지원 행동 신호의 혼합은 Supervisor와 Review가 결정적으로 거부합니다. 자유문장 전체 의미는 schema만으로 증명할 수 없으므로 나머지 의미 불일치는 독립 LLM Review가 검사합니다. BE는 자연어에서 대상을 추론하지 않고 검수된 `target`과 `ReviewProof`만 권한 경계로 사용합니다.

## 5. 현재 standalone 실행 흐름

아래 고정 의존 순서는 자연어 Case 생성·결과 제출 실행의 first pass 기준입니다. 기존 `SUPPORT_REFRESH` trigger는 새 사용자 입력이나 절차 해석 없이 검수된 지원정보만 갱신하므로 현재 runtime에서 Support부터 시작합니다. 이 예외는 웹 절차 근거가 필요한 자연어 계획에 적용하지 않습니다.

```text
SupervisorRunInput
  → 절차조회 Tool
      → Google Agent Search searchLite
          └─ 해당 query의 fallback 조건 충족 → Kakao Daum 웹문서 검색
      → HTTPS·공식기관 allowlist·redirect 검증
      → 실제 공식 원문 fetch
      → raw documents + Evidence
  → 정보분석 Agent
      → 사용자 입력 + snapshot + lookup result 분석
      ├─ 확인 필요 충돌 있음 → CONFLICT
      └─ canonical procedure_findings + 사실/누락/불확실성
  → 지원금 Agent
  → Supervisor 초안
  → Review Tool
      ├─ PASS → ReviewProof → REVIEWED_PLAN
      ├─ REVISE → dependency상 가장 앞선 구성요소부터 재실행
      └─ 실패/상한 소진 → SAFE_FAILURE
```

하위 구성요소가 서로 호출하지 않습니다. Graph/Supervisor가 Procedure 결과를 Info 입력에, Info finding의 관련 canonical step을 Support 입력에 전달합니다.

Review 재작업 순서는 다음과 같습니다.

| 문제 소유자 | 재실행 범위 | 이유 |
|---|---|---|
| `PROCEDURE_TOOL` | Procedure → Info → Support → Supervisor | 원문이 바뀌면 모든 해석과 선택이 달라집니다. |
| `INFO_AGENT` | Info → Support → Supervisor | raw lookup은 재사용할 수 있지만 의미 분석 이후는 다시 만들어야 합니다. |
| `SUPPORT_AGENT` | Support → Supervisor | 절차 원문과 Info 결과는 그대로 사용할 수 있습니다. |
| `SUPERVISOR` | Supervisor | source 결과가 충분하고 선택·표현만 잘못된 경우입니다. |

Info가 충돌을 반환해도 그 전에 수행한 Procedure 호출은 trace에 남습니다. 다만 Support·Supervisor·Review를 실행하지 않고 `CONFLICT`로 닫습니다.

## 6. 절차 인터넷 조회 안전조건

1. `lookup_goal=BUSINESS_CLOSURE`, `locale=ko-KR`, `source_policy=OFFICIAL_ONLY`만 허용합니다.
2. 1순위 Google 호출은 `POST https://{api-host}/v1/projects/{project}/locations/{location}/collections/default_collection/engines/{engine}/servingConfigs/default_search:searchLite`와 `X-Goog-Api-Key`를 사용합니다. `global`은 `discoveryengine.googleapis.com`, `us | eu`는 regional API host만 허용합니다. `searchLite`가 허용하는 공개 웹사이트 검색 앱만 대상으로 하며 project/location/engine은 credential이 아닌 검증된 runtime 설정입니다.
3. Google 설정이 완전하면 각 query에서 Google을 먼저 시도합니다. retry 후 기술 실패, 0건, 또는 공식기관 allowlist 후보 0건이면 그 query만 `GET https://dapi.kakao.com/v2/search/web`로 fallback합니다. Google 세 필드가 모두 미설정이면 Kakao-only direct 실행이 가능하고, 일부만 설정된 경우에는 구성 오류로 거부합니다. 다른 query의 Google 성공까지 Kakao로 중복 조회하지 않습니다.
4. 검색어는 확정 snapshot 값 또는 redacted 입력의 제한된 키워드가 선택한 정적 문자열만 사용하며 사용자 원문·주소를 외부 검색어에 복사하지 않습니다.
5. Google/Kakao 검색결과 HTML을 crawl하지 않습니다. 특히 `google.com/search` SERP HTML 요청·parsing은 금지하며 공식 JSON API 응답만 URL 발견 metadata로 사용합니다.
6. Google은 `PROCEDURE_GOOGLE_API_KEY`, `PROCEDURE_GOOGLE_PROJECT_ID`, `PROCEDURE_GOOGLE_ENGINE_ID`와 선택 `PROCEDURE_GOOGLE_LOCATION`을 사용합니다. Kakao는 `PROCEDURE_KAKAO_REST_API_KEY`를 우선하며 과거 `PROCEDURE_SEARCH_API_KEY`, `KAKAO_CLIENT_ID`는 deprecated alias입니다.
7. Google이 미설정이고 Kakao만 설정됐다면 Kakao가 이번 실행의 첫 provider이며 `provider_order=[KAKAO_DAUM_WEB]`, `fallback_query_count=0`으로 기록합니다. Google을 실제 시도한 뒤 Kakao로 넘긴 경우에만 fallback입니다. 두 provider 모두 사용할 수 없거나 모든 provider 시도가 기술 실패하면 component failure로 fail closed하며 fixture나 빈 결과로 대체하지 않습니다.
8. 후보 URL은 HTTPS, 표준 port, 공식기관 hostname allowlist, IP-literal 금지를 만족해야 하며 redirect마다 다시 검증합니다. hostname DNS 해석 결과의 private/loopback/link-local 차단과 DNS rebinding 방어는 production egress/resolver 경계로 남아 있습니다.
9. 허용 MIME, 응답 byte 상한, connect/read timeout을 적용합니다.
10. script/style 등 실행·비가시 subtree와 form/input의 태그·속성을 제거하되 form 안의 보이는 공식 본문은 보존합니다. `main`/`article`을 우선하고 서로 다른 정적 query token이 밀집된 최대 4,000자 window만 excerpt로 남기며, hash는 전체 body bytes로 계산합니다.
11. Google/Kakao snippet은 원문 Evidence로 저장하지 않습니다. 문서에는 실제 URL을 발견한 `discovery_provider`를 기록하고 직접 fetch한 공식 원문만 Evidence로 만듭니다.
12. 발행·수정일을 검증할 수 없으면 `freshness_status=UNKNOWN`입니다.
13. finding이 참조한 Evidence 중 하나라도 unknown/stale이면 Info local Guardrail이 `relevance=UNDETERMINED` 외 값을 거부하고, provider prompt와 Review가 기한·필수서류·법적 의무의 확정형 주장을 차단합니다.

모든 논리 query가 설정된 provider chain 안의 적어도 한 well-formed 응답으로 해결됐지만 0건이거나 모든 후보가 초기 공식 출처 검증에서 제외되면 `NO_RESULTS`입니다. Google 실패 뒤 Kakao가 해당 query를 충족하면 그 query는 성공으로 계산하고 `SEARCH_PROVIDER_FALLBACK`, 기술 실패가 있었다면 `SEARCH_PROVIDER_FAILED`, provider attempt를 별도로 기록합니다. 모든 provider 이후에도 해결하지 못한 논리 query가 있으면 `SEARCH_QUERY_FAILED`입니다. fallback 후에도 일부 query 또는 fetch가 실패하면 `PARTIAL`이며, 공식 후보는 있었지만 fetch가 모두 실패한 경우에는 `documents=[]`일 수 있습니다. 전체 lookup에서 모든 provider attempt가 credential·인증·quota·timeout으로 실패하면 기술 실패이며 `NO_RESULTS`로 숨기지 않습니다.

## 7. Evidence, Review와 저장 안전조건

- `ProcedureSourceDocument`와 `OFFICIAL_DOCUMENT` Evidence는 canonical URL, excerpt, retrieved time, freshness와 content hash가 1:1로 같아야 합니다.
- Info는 Evidence를 새로 발급하지 않고 lookup Evidence를 참조해 `SourcedText`를 만듭니다.
- 공식 원문 누락은 Procedure Tool, 원문에 없는 해석·잘못된 canonical mapping은 Info Agent, 근거 있는 finding 중 잘못된 행동 선택은 Supervisor 문제입니다.
- 인터넷 자료는 “해야 할 절차”의 정보이지 사용자가 “실제로 완료했다”는 Evidence가 아닙니다.
- 웹문서만으로 `procedure_progress` mutation이나 `CASE_COMPLETE`를 만들 수 없습니다.
- 완료 저장에는 사용자 입력, 전문가 확인 또는 공식 처리 결과처럼 현실 실행을 증명하는 별도 Evidence가 필요합니다.
- Review subject와 proof는 trigger, snapshot, raw source, Info finding, 초안 전체 digest에 결합됩니다.
- standalone `REVIEWED_PLAN`은 BE 저장 허가가 아닙니다.

## 8. 실행 환경과 실행 방법

### 환경변수

| 변수 | 필수 조건 | 용도 |
|---|---|---|
| `CHAT_PROXY_URL` | live LLM | structured-output endpoint |
| `PROXY_TOKEN` | live LLM | LLM credential |
| `OPENAI_MODEL` | live LLM | endpoint 지원 모델 |
| `PROCEDURE_GOOGLE_API_KEY` | Google primary | Agent Search `searchLite` API key; `X-Goog-Api-Key` header로만 전송 |
| `PROCEDURE_GOOGLE_PROJECT_ID` | Google primary | 공개 웹사이트 검색 앱의 Google Cloud project ID |
| `PROCEDURE_GOOGLE_ENGINE_ID` | Google primary | 공개 웹사이트 검색 app/engine ID |
| `PROCEDURE_GOOGLE_LOCATION` | 선택 | Agent Search location `global | us | eu`, 기본 `global` |
| `PROCEDURE_KAKAO_REST_API_KEY` | Kakao fallback | Kakao Daum 검색 REST API 키 |
| `PROCEDURE_SEARCH_API_KEY` | deprecated Kakao alias | 기존 배포 호환 전용; 새 배포 사용 금지 |
| `KAKAO_CLIENT_ID` | deprecated Kakao alias | OAuth와 검색 credential 의미가 섞인 기존 호환 경로 |
| `PROCEDURE_SEARCH_ALLOWED_DOMAINS` | 선택 | comma-separated 공식기관 host suffix allowlist. 코드에서 검토된 root와 그 하위 host로만 좁힐 수 있음 |
| `PROCEDURE_SEARCH_TIMEOUT_SECONDS` | 선택 | 각 provider 검색과 공식 원문 fetch 요청별 timeout, 기본 8초 |
| `PROCEDURE_SEARCH_TOTAL_TIMEOUT_SECONDS` | 선택 | 검색과 모든 공식 원문 fetch를 합한 전체 timeout, 기본 30초 |
| `PROCEDURE_SEARCH_MAX_RETRIES` | 선택 | retryable 외부 오류 재시도 횟수 `0..4`, 기본 1 |
| `PROCEDURE_SEARCH_RETRY_BACKOFF_SECONDS` | 선택 | retry backoff, 기본 0.25초 |
| `PROCEDURE_SEARCH_MAX_RESPONSE_BYTES` | 선택 | provider 검색 JSON과 공식 원문 각각의 응답 상한 `1024..10000000`, 기본 1,000,000 bytes |
| `PROCEDURE_SEARCH_MAX_REDIRECTS` | 선택 | redirect 상한 `0..10`, 기본 3 |
| `OPENAI_REASONING_EFFORT` | 선택 | 지원 provider에 한한 reasoning 설정 |
| `AGENT_LLM_TIMEOUT_SECONDS` | 선택 | LLM timeout |
| `AGENT_LLM_MAX_RETRIES` | 선택 | provider retry 상한 |
| `AGENT_LLM_RETRY_BACKOFF_SECONDS` | 선택 | retry backoff |

key 값, Authorization header, 내부 endpoint, 실제 사용자 원문은 문서·출력·trace에 남기지 않습니다. Google/Kakao key는 별도 서버 secret로 주입하고 API 제한·rotation을 운영 설정으로 관리합니다. Google project/engine도 allowlist된 형식만 받고 `global | us | eu`에 대응하는 승인된 Discovery Engine API host만 조립하며 사용자 제공 endpoint를 허용하지 않습니다. 기본 원문 allowlist는 `go.kr`, `gov.kr`, 국세청·홈택스·국가법령정보센터·찾기쉬운 생활법령정보·4대사회보험·소상공인시장진흥공단·소상공인24·기업마당의 공식 host suffix입니다. 환경변수는 이 코드 검토 registry의 root 또는 더 구체적인 하위 host만 선택할 수 있어 trust root를 넓히지 못합니다. 새 root는 코드 변경과 보안/업무 승인을 거쳐 추가하며, 사용자 입력으로 실행 중 확장하지 않습니다.

### 재현 명령

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install \
  -r backend/requirements.txt \
  -r backend/requirements-dev.txt

PYTHONPATH=backend backend/.venv/bin/python \
  -m pytest -q -W error backend/tests/agent

backend/.venv/bin/ruff check backend/app/agent backend/tests/agent
backend/.venv/bin/ruff format --check backend/app/agent backend/tests/agent

PYTHONPATH=backend backend/.venv/bin/python \
  -m app.agent.cli --live --compact --trace-id local-live-smoke
```

자동 테스트는 mock Google/Kakao search provider와 mock fetcher를 주입하므로 network와 credential을 사용하지 않습니다. live smoke는 실제 검색 quota·비용과 LLM 비용을 사용할 수 있으므로 `--live`를 명시한 경우에만 실행합니다. Google 설정이 없으면 Kakao fallback을 사용할 수 있지만 두 provider credential이 모두 없으면 즉시 실패하며 mock/fixture로 전환하지 않습니다.

## 9. 데이터 모드별 현재 상태

| 모드 | Case | 절차 자료 | 지원사업 | 용도 |
|---|---|---|---|---|
| unit/contract test | 합성 fixture | mock Google primary/Kakao fallback 결과 + mock fetch 원문 | 합성 reviewed catalog | 결정론적 CI, 외부 호출 없음 |
| standalone live | 비식별 합성 fixture | 실제 Google 우선·Kakao query별 fallback 검색 + 실제 공식 원문 fetch | 합성 reviewed catalog | 인터넷 조회와 전체 Graph opt-in smoke |
| BE 생산 연동 | 인증된 BE snapshot | 실제 Google 우선·Kakao query별 fallback 검색 + 공식 원문 fetch | canonical DB/Wiki/공식 원문 | 미구현 |

standalone live의 “실제 데이터”는 인터넷의 공식 절차 원문을 뜻합니다. Case와 support catalog까지 운영 데이터라는 뜻은 아닙니다. 실제 사용자 Case read/write는 BE 연동 전에는 수행하지 않습니다.

## 10. 검증 근거와 완료 기준

다음을 모두 만족해야 “v2 Agent 자체 동작 가능”으로 보고합니다.

- [ ] `agent-io/2.0` public/provider/local schema가 strict 검증과 JSON Schema 생성을 통과합니다.
- [ ] Google/Kakao parser가 URL discovery metadata만 사용하고 snippet을 Evidence로 만들지 않으며 Google SERP HTML을 요청하지 않습니다.
- [ ] 각 query에서 Google이 먼저 호출되고 허용된 조건에서만 Kakao fallback이 실행되며 provider attempt와 문서 `discovery_provider`가 일치합니다.
- [ ] HTTPS, allowlist, redirect, IP-literal, MIME, size, 요청별·전체 timeout 거부 테스트가 있습니다. DNS private-address/rebinding은 생산 egress 검증 항목입니다.
- [ ] raw document와 Evidence의 URL/excerpt/time/freshness/hash가 1:1입니다.
- [ ] `COMPLETE | PARTIAL | NO_RESULTS`와 기술 실패가 counter에 맞게 구분됩니다.
- [ ] Procedure→Info→Support→Supervisor→Review 호출 순서와 call/digest 연결을 검증합니다.
- [ ] Info가 lookup 원문에 없는 단계·기관·서류·기한·URL을 만들 수 없습니다.
- [ ] Info가 canonical `KnownProcedureStep` 밖의 DB ID/code를 만들 수 없습니다.
- [ ] stale/unknown source로 확정 주장을 만들지 않습니다.
- [ ] 웹 Evidence만으로 progress mutation과 `CASE_COMPLETE`를 만들지 않습니다.
- [ ] 정상 초안은 Review를 우회할 수 없습니다.
- [ ] 실패와 retry 소진은 미검토 결과 대신 `SAFE_FAILURE`입니다.
- [ ] Agent test, Ruff check와 format check가 통과합니다.
- [ ] live smoke 결과를 mock 테스트와 구분해 실제 공식 URL·조회시각·문서 수만 PR에 기록합니다.
- [ ] standalone 경로에 BE/DB write capability가 없습니다.

실제 test 수와 live smoke 결과는 실행한 commit의 PR 검증 섹션에 기록합니다. 과거 v1의 `155 passed`나 합성 master smoke는 v2 완료 근거로 재사용하지 않습니다.

## 11. BE 연동 전에 남은 경계

- 인증된 Case snapshot assembler와 canonical field/enum registry
- canonical procedure step ID/code/name/alias registry와 인터넷 finding 매핑 fixture
- support registry와 Evidence 저장·resolver
- Google 공개 웹사이트 검색 app/engine 생성과 API key 제한·secret 주입, Kakao fallback key 주입, provider별 quota/rate-limit/비용/cache 관측
- 공식 domain allowlist 변경 승인과 보안 runbook
- hostname DNS 해석 결과의 private range 차단, DNS rebinding 방어와 production egress 정책
- PlanningCoordinator, 인증·소유권, idempotency, version/CAS
- Output/State Transition Guardrail과 atomic persistence
- production conflict ref/TTL/CAS와 cross-language Review digest vector
- 외부 response/viewState adapter

BE는 ProcedureMaster나 인터넷 검색 내용을 작성하지 않습니다. AI가 Google/Kakao provider 순서·조회와 원문 fetch/분석을 소유하고, BE/인프라는 Google 공개 공식사이트 검색 앱을 생성·관리하며 두 provider credential과 안전한 네트워크 경계를 제공합니다. BE는 canonical 진행상태 식별자와 안전한 저장·운영 경계를 제공합니다.

## 12. AI가 유지해야 하는 문서 산출물

| 문서 | 소유 | 갱신 시점 | 이유 |
|---|---|---|---|
| `docs/architecture.md` | AI, 경계는 BE 공동 검토 | 책임이나 호출 방향 변경 | Tool 조회와 Info 해석을 분리합니다. |
| `docs/agent-tool-io-schema.md` | AI 제안, shared 경계 공동 승인 | schema version·field 변경 | 입출력 계약의 단일 출처입니다. |
| 이 문서 | AI | 환경·실행·완료 기준 변경 | mock과 live, standalone과 production을 구분합니다. |
| `docs/be-agent-integration-requirements.md` | AI 제안, BE 회신 | BE 책임·shared 경계 변경 | BE가 검색 내용을 구현해야 한다는 오해를 막습니다. |
| provider/local schema 테스트 | AI | 검색/LLM projection 변경 | 외부 payload를 직접 신뢰하지 않게 합니다. |

비밀값, 실제 사용자 원문, 운영 endpoint, access token은 어떤 문서·fixture에도 넣지 않습니다.

## 13. 공식 외부 근거

- [Google Agent Search `searchLite` REST API](https://docs.cloud.google.com/generative-ai-app-builder/docs/reference/rest/v1/projects.locations.collections.engines.servingConfigs/searchLite)
- [Google Agent Search 웹사이트 데이터 준비](https://docs.cloud.google.com/generative-ai-app-builder/docs/prepare-data)
- [Google Cloud API key 인증](https://docs.cloud.google.com/docs/authentication/api-keys-use)
- [Kakao Daum 검색 REST API 개발 가이드](https://developers.kakao.com/docs/ko/daum-search/dev-guide)
- [Kakao REST API 시작하기](https://developers.kakao.com/docs/ko/rest-api/getting-started)
- [Kakao 앱 키 설정](https://developers.kakao.com/docs/ko/app-setting/app)
- [Kakao 쿼터 안내](https://developers.kakao.com/docs/ko/getting-started/quota)

Google 공식 가이드상 `searchLite`는 공개 웹사이트 검색 앱에 한해 API key 인증으로 사용할 수 있고, 보안을 강화하려면 OAuth/IAM 기반 `search`가 권장됩니다. RE:BORN v2는 공개 공식사이트 URL만 포함한 앱과 `X-Goog-Api-Key`를 사용하며 Google 검색 화면 HTML을 scraping하지 않습니다. Kakao는 query별 2순위 fallback입니다. 두 provider의 결과 metadata는 원문 보장이 아니므로 allowlist 검증 뒤 실제 URL을 다시 fetch합니다. 쿼터·비용·API 지원 범위는 변경될 수 있으므로 숫자를 완료 보장으로 문서화하지 않고 운영 시 공식 페이지를 다시 확인합니다.
