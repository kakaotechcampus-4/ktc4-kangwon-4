# RE:BORN Agent 독립 실행 요구사항

> 상태: **v2.1 — `[CURRENT_AI]` standalone 구현·검증 완료 / `[PROPOSED_SHARED]` BE 생산 계약 합의 전**
>
> 소유: AI
>
> schema version: `agent-io/2.0`
>
> 필드 계약은 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md), 외부 데이터 근거는 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md), BE 요구는 [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)를 따릅니다.

이 문서의 `agent-io/2.0`은 **현재 AI standalone 내부 schema version**입니다. BE/FE shared 계약이 승인됐다는 뜻이 아닙니다. `[CURRENT_AI]`는 코드·테스트로 확인된 현재 범위, `[OBSERVED_2026-09-15]`는 그 날짜의 외부 실호출, `[PROPOSED_SHARED]`는 공동 승인 전 계약안, `[TARGET_UNIMPLEMENTED]`는 미구현 목표를 뜻합니다.

## 1. `[CURRENT_AI]` 지금 되는 것과 `[TARGET_UNIMPLEMENTED]` 아직 되지 않는 것

Agent Graph 자체는 BE 없이 실행할 수 있습니다. 다만 “실행 가능”과 “실제 사용자 Case로 서비스 가능”은 다릅니다.

| 범위 | 상태 라벨 | 코드 상태 | 실제/합성 구분 |
|---|---|---|---|
| Agent Graph 호출·Review·safe failure | `[CURRENT_AI]` | 실행 가능 | typed 입력을 받은 Agent 코어는 실제 실행 |
| standalone CLI 입력 | `[CURRENT_AI]` | 실행 가능 | `fixtures.py`에 고정된 비식별 합성 Case·canonical step 사용 |
| 폐업 절차 원문 | `[CURRENT_AI]` | 공식 URL fetch 경로 구현 | live 성공은 외부 사이트 상태에 따라 달라짐 |
| Support Agent의 catalog·판정 | `[CURRENT_AI]` | 실행 가능 | 검수됐다고 가정한 합성 catalog로 비교 |
| 기업마당 지원 공고 discovery | `[CURRENT_AI]` | Graph 밖 adapter 실행 가능 | `[OBSERVED_2026-09-15]` 실제 API raw 후보 응답 확인; 자격 판정에는 미사용 |
| 실제 사용자 Case 조회·저장 | `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` | 실행 불가 | BE 인증·snapshot·CAS·persistence 필요 |

standalone CLI와 Agent Graph는 MySQL을 읽거나 쓰지 않으므로 Docker DB를 띄울 필요가 없습니다. 현재 `docker compose`의 DB-only 구성은 BE 개발용이며 standalone 실행 의존성이 아닙니다.

현재 가능한 것:

- `CASE_CREATED`·`RESULT_SUBMITTED`의 Procedure → Info → Support → Supervisor → Review 경로 실행
- `SUPPORT_REFRESH`의 Support → Supervisor → Review 경로 실행
- 검색 API key 없이 코드 검토된 공식 문서의 실제 원문 조회
- registry miss 시 선택 Kakao→Google URL discovery fallback
- 공식 원문 excerpt/hash/Evidence 생성과 strict schema 검증
- `[CURRENT_AI]` configured `BIZINFO_API_KEY`를 소비하는 별도 raw 후보 discovery adapter. CLI/Graph에는 연결하지 않음
- `[OBSERVED_2026-09-15]` 기존 key로 기업마당 HTTP 200 raw 후보 응답 확인. 지속 가용성·생산 SLO는 아님
- `[CURRENT_AI]` LLM structured-output 호출과 fail-closed 경로 구현. live 성공 결과는 아래 날짜 한정 관찰과 구분

`[OBSERVED_2026-09-15]` 현재 팀 proxy의 `/models`에서 확인된 모델은 `openai/gpt-4.1-mini`뿐입니다. 직접 구성요소 호출과 안전 실패는 동작하지만, 전체 Graph의 복합 의미 schema는 이 모델에서 간헐적으로 `STRUCTURED_OUTPUT_FAILED` 또는 `REVIEW_RETRY_EXHAUSTED`로 안전 종료됩니다. 같은 날 최종 실호출에서도 실제 공식 원문과 LLM을 사용해 `REVIEWED_PLAN / NEEDS_MORE_INFO / PASS`가 나온 실행과 `REVIEW_RETRY_EXHAUSTED`가 나온 실행을 모두 확인했습니다. 이는 지속적 가용성이나 생산 SLO 확정이 아닙니다. 따라서 현재 상태를 “모든 자연어 요청이 안정적으로 `REVIEWED_PLAN`을 반환한다”로 보지 않으며, 생산 신뢰성을 위해 더 강한 structured-output 모델을 제공하는 endpoint와 고정 회귀 평가가 필요합니다.

현재 불가능한 것:

- CLI에 임의 자연어·실제 사업자 정보를 넣어 새 Case 생성
- BE의 실제 Case read/write, 인증·소유권 확인, CAS·transaction
- raw 기업마당 공고를 검수 없이 지원 자격 판정에 사용
- 사용자 대신 정부24·홈택스·4대보험 신고 실행
- Langfuse 비용 추적. 현재 Graph 기본 trace sink는 `NullTraceSink`
- 정형 API 실패 시 범용 crawler/RAG 자동 전환. 현재는 승인된 고정 공식 URL 직접 조회만 있음

따라서 standalone 성공은 Agent 내부 구조와 실제 공식 원문 조회가 동작한다는 뜻이지 생산 연동 완료를 뜻하지 않습니다.

`AgentGraph.run(...)`을 Python에서 직접 호출하면 caller가 만든 schema-valid `SupervisorRunInput`을 받을 수는 있습니다. 그러나 자연어 한 문장만으로는 실행할 수 없고, redaction된 input, snapshot, Evidence, canonical step, reviewed catalog를 신뢰할 수 있게 조립하는 adapter가 필요합니다. 현재 CLI에는 자연어 인자가 없고 항상 같은 fixture를 사용합니다.

## 2. `[CURRENT_AI]` 데이터 의존성과 신뢰 경계

| 입력·의존성 | 현재 공급자 | 소비 지점 | 신뢰·제한 |
|---|---|---|---|
| `SupervisorRunInput` | standalone fixture | Graph | strict schema를 통과한 비식별 합성 입력 |
| `CaseSnapshot` | standalone fixture | Info/Support/Supervisor/Review | 실제 사용자 DB snapshot이 아님 |
| `KnownProcedureStep[]` | standalone fixture | Info | 웹 제목이 아니라 canonical ID에만 finding 결합 |
| `ReviewedSupportCatalog` | standalone fixture | Support | raw API 결과가 아닌 검수된 immutable 입력 |
| 공식 source registry | Agent 코드 | Procedure | URL 선택만 신뢰. 실제 fetch 성공 전에는 Evidence 아님 |
| Kakao/Google 결과 | 선택 외부 API | Procedure | URL discovery metadata. title/snippet은 Evidence 아님 |
| fetched 공식 원문 | 외부 공식기관 | Procedure→Info→Review | instruction이 아닌 untrusted data. allowlist·MIME·size 검증 필요 |
| LLM structured output | configured endpoint | Info·Support·Supervisor·Review | provider 형식 검증 뒤 로컬 의미·provenance 재검증 |
| clock·UUID | runtime | 전체 | 모델이 ID·시각을 만들지 못하게 runtime 주입 |

외부 문서에 적힌 prompt, credential 요청, 링크 이동 지시나 코드 실행 문장은 실행하지 않습니다. 사용자 원문·주소·사업자번호도 검색 query로 복사하지 않습니다.

## 3. `[CURRENT_AI]` standalone 구성요소별 내부 계약

| 구성요소 | 입력 | 출력 | 책임 | 금지 |
|---|---|---|---|---|
| Procedure Tool | `ProcedureLookupInput` | `ProcedureLookupResult` | 공식 URL 선택·발견, 안전한 원문 fetch, raw document/Evidence | 의미 해석, 진행 완료·우선순위·Next Action 결정 |
| Info Agent | `InfoAnalysisInput` | `InfoAnalysisResult` | 사용자 사실·충돌·누락과 raw 원문을 canonical procedure finding으로 해석 | 인터넷 직접 검색, 새 DB step 생성 |
| Support Agent | `SupportAnalysisInput` | `SupportAnalysisResult` | 검수 catalog의 조건 비교와 Evidence 연결 | raw 공고 자동 승인, 자격·수령 확정 |
| Supervisor | run input + source results | `SupervisorDraft` | `ACTION`일 때 Blocker와 Next Action 각 1개 결정 | Evidence 생성, Review 우회, DB write |
| Review Tool | `ReviewSubject` | `ReviewResult` | 전달된 Case·초안·Evidence 독립 검토 | 새 검색, 초안 직접 수정 |
| Graph | `SupervisorRunInput` | `AgentRunOutcome` | 의존 순서·재작업·상한·safe failure | 인증·저장 transaction 대체 |

상세 필드와 조건부 불변식은 `agent-tool-io-schema.md`가 단일 출처입니다.

## 4. `[CURRENT_AI]` 실행 흐름

```text
비식별 SupervisorRunInput
  → ProcedureLookupTool
      → OFFICIAL_SOURCE_REGISTRY
          └─ miss: Kakao Daum 검색
                    └─ miss: Google Agent Search
      → 모든 후보 HTTPS·allowlist·redirect 재검증
      → 공식 원문 직접 fetch
      → raw documents + OFFICIAL_DOCUMENT Evidence
  → InfoAnalysisAgent
      → 사실·충돌·누락·canonical procedure findings
      ├─ 확인할 충돌 → CONFLICT
      └─ 정상 → SupportAgent
                    → Supervisor draft
                    → ReviewTool
                        ├─ PASS → REVIEWED_PLAN
                        ├─ REVISE → dependency상 앞 구성요소부터 재실행
                        └─ 상한/실패 → SAFE_FAILURE
```

Review 재작업은 원인이 Procedure이면 Procedure부터, Info이면 Info부터, Support이면 Support부터, 표현·선택 문제면 Supervisor부터 수행합니다. 하위 구성요소끼리 직접 호출하지 않습니다.

위 흐름은 **현재 코드에 고정된 실행 순서**입니다. 현재 Supervisor는 이미 수집된 source result로 초안을 만들 뿐, 첫 호출 대상을 선택하지 않습니다. Supervisor가 필요한 구성요소를 계획하고 LangGraph router가 그 계획을 실행하는 구조는 생산 목표이며, 호출 계획 schema와 동적 router는 아직 구현되지 않았습니다. `SUPPORT_REFRESH`만 새 사용자 입력과 절차 해석이 없으므로 `Support → Supervisor → Review`로 시작합니다.

기업마당 discovery adapter도 이 사용자 요청 Graph의 노드가 아닙니다. 실제 API에서 얻은 raw 후보는 별도 ingestion 입력으로만 반환되며, 검수·catalog version 발행 전에는 Support Agent에 전달되지 않습니다.

## 5. `[CURRENT_AI]` 공식 절차 조회 정책

1. `lookup_goal=BUSINESS_CLOSURE`, `locale=ko-KR`, `source_policy=OFFICIAL_ONLY`만 허용합니다.
2. `PROCEDURE_OFFICIAL_REGISTRY_ENABLED=true`가 기본입니다.
3. 현재 registry는 사업자 폐업, 커피전문점 영업 폐업, 직원이 있는 사업장의 국민연금 탈퇴 안내를 연결합니다.
4. registry는 네트워크 검색을 하지 않지만 URL만 선택합니다. 선택된 URL도 실제 fetch와 모든 안전 검증을 통과해야 Evidence가 됩니다.
5. registry miss query만 Kakao로 보내고, Kakao도 공식 후보를 찾지 못하면 Google로 보냅니다.
6. 검색 provider가 반환한 snippet은 저장 근거가 아닙니다. Google SERP HTML은 요청하지 않고 Naver 검색 결과는 AI 입력으로 쓰지 않습니다.
7. URL은 HTTPS, 표준 port, 코드 검토된 공식 host suffix, credential/fragment 없음, IP literal 아님을 만족해야 합니다. redirect마다 다시 검사합니다.
8. MIME, body byte, 요청별 timeout, 전체 deadline, retry·redirect 횟수를 제한합니다.
9. script/style과 실행 markup을 제거하고 bounded visible text만 excerpt로 만듭니다. hash는 excerpt가 아니라 전체 response body bytes 기준입니다.
10. 원문 게시·수정일을 검증하지 못하면 `published_at=null`, `freshness_status=UNKNOWN`입니다.
11. 현재는 후보 원문 fetch 실패 뒤 같은 query를 다음 search provider로 다시 찾지 않습니다. 이 경우 성공으로 꾸미지 않고 `PARTIAL`과 warning을 반환합니다.

`[TARGET_UNIMPLEMENTED]` hostname DNS 결과의 private/loopback/link-local 차단과 DNS rebinding 방어는 application allowlist만으로 완성되지 않았습니다. 생산 egress/resolver에서 추가해야 합니다.

## 6. `[CURRENT_AI]` raw discovery / `[TARGET_UNIMPLEMENTED]` 검수 catalog pipeline

기업마당 API에서 strict raw candidate와 `OFFICIAL_API` Evidence를 만드는 단계까지만 `[CURRENT_AI]`입니다. 아래 원문·첨부 수집, 조건 구조화, 사람 검수, catalog version 발행과 Graph 주입은 `[TARGET_UNIMPLEMENTED]`입니다.

`[CURRENT_AI]` 이 경로는 configured key를 받아 공고 후보와 `OFFICIAL_API` Evidence를 만드는 read-only discovery adapter입니다. `[OBSERVED_2026-09-15]` 기존 key로 기업마당 HTTP 200 응답을 확인했지만 현재 가용성이나 생산 SLO를 보장하지 않습니다.

```text
기업마당 API
  → strict raw candidate + OFFICIAL_API Evidence
  ── [CURRENT_AI] 현재 adapter 구현 경계 ──
  ── [TARGET_UNIMPLEMENTED] 아래부터 생산 pipeline ──
  → 원문·첨부·수정시각 확인
  → 조건·서류 구조화
  → 사람 또는 승인된 deterministic rule 검수
  → ReviewedSupportCatalog version 발행
  → Support Agent 주입
```

API 응답의 `세부사업별 상이`, `예산 소진시까지`를 임의 날짜로 바꾸지 않습니다. 공고 자연어에서 자동으로 `ELIGIBLE`을 만들지 않으며, 조회 자체로 지원 신청 row를 생성하지 않습니다. 자세한 API와 활용신청은 공식 데이터 소스 전략 문서를 따릅니다.

현재 discovery는 `pageIndex=1`, 호출당 최대 100건인 단일 GET이며 재시도·pagination·상세/첨부 수집은 하지 않습니다. 기술 실패는 예외의 `code`, `retryable`, `status_code`로만 전달하고 지원사업 없음이나 자격 미달로 바꾸지 않습니다.

| 오류 계열 | 예시 code | retryable |
|---|---|---|
| 입력·민감정보 | `BIZINFO_SENSITIVE_KEYWORD` | false |
| redirect·4xx | `BIZINFO_REDIRECT_REFUSED`, `BIZINFO_HTTP_ERROR` | 408/425/429만 true |
| 일시적 transport·5xx | `BIZINFO_TRANSPORT_ERROR`, `BIZINFO_HTTP_ERROR` | true |
| content type·크기·JSON/schema drift·정규화 | `BIZINFO_*_INVALID`, `BIZINFO_RESPONSE_TOO_LARGE` | false |

## 7. 환경변수 — `[CURRENT_AI]` 소비값 / `[PROPOSED_SHARED]` 준비값

### LLM live 실행

| 변수 | 조건 | 용도 |
|---|---|---|
| `CHAT_PROXY_URL` | 필수 | structured-output endpoint |
| `PROXY_TOKEN` | 필수 | LLM credential |
| `OPENAI_MODEL` | 필수 | endpoint 지원 모델 |
| `OPENAI_REASONING_EFFORT` | 선택 | reasoning 설정 |
| `AGENT_LLM_TIMEOUT_SECONDS` | 선택 | 한 provider 시도 전체 deadline |
| `AGENT_LLM_MAX_RETRIES` | 선택 | provider retry 상한 |
| `AGENT_LLM_RETRY_BACKOFF_SECONDS` | 선택 | 최초 retry backoff, `0..60`초 |
| `AGENT_LLM_MAX_RESPONSE_BYTES` | 선택 | provider 응답 상한(기본 1,000,000 bytes; 1,024~10,000,000) |

### Procedure

| 변수 | 조건 | 용도 |
|---|---|---|
| `PROCEDURE_OFFICIAL_REGISTRY_ENABLED` | 선택, 기본 true | credential 없는 공식 source registry |
| `PROCEDURE_KAKAO_REST_API_KEY` | 선택 2순위 | registry miss의 Daum URL discovery |
| `PROCEDURE_SEARCH_API_KEY` | deprecated | 기존 Kakao alias |
| `KAKAO_CLIENT_ID` | deprecated | OAuth 설정과 혼동 가능한 마지막 호환 alias |
| `PROCEDURE_GOOGLE_API_KEY` | 선택 3순위 | Google `searchLite` key |
| `PROCEDURE_GOOGLE_PROJECT_ID` | Google 사용 시 필수 | Google project |
| `PROCEDURE_GOOGLE_ENGINE_ID` | Google 사용 시 필수 | 공개 웹사이트 engine |
| `PROCEDURE_GOOGLE_LOCATION` | 선택, 기본 global | `global | us | eu` |
| `PROCEDURE_SEARCH_ALLOWED_DOMAINS` | 선택 | 코드 검토 범위 안에서 allowlist 축소 |
| `PROCEDURE_SEARCH_TIMEOUT_SECONDS` | 선택, 기본 8 | 요청별 timeout |
| `PROCEDURE_SEARCH_TOTAL_TIMEOUT_SECONDS` | 선택, 기본 60 | lookup 전체 deadline. 여러 공식 원문 순차 검증의 실측 반영 |
| `PROCEDURE_SEARCH_MAX_RETRIES` | 선택, 기본 1 | 외부 오류 retry `0..4` |
| `PROCEDURE_SEARCH_RETRY_BACKOFF_SECONDS` | 선택, 기본 0.25 | retry backoff |
| `PROCEDURE_SEARCH_MAX_RESPONSE_BYTES` | 선택, 기본 1,000,000 | JSON·원문 body 상한 |
| `PROCEDURE_SEARCH_MAX_REDIRECTS` | 선택, 기본 3 | redirect 상한 |

### 외부 공식 데이터

| 변수 | 현재 상태 | 용도 |
|---|---|---|
| `BIZINFO_API_KEY` | `[CURRENT_AI][OBSERVED_2026-09-15]` 기존 값 동작 확인 | 현재 독립 기업마당 지원 공고 discovery가 소비 |
| `DATA_GO_KR_SERVICE_KEY` | `[OBSERVED_2026-09-15]` NTS 접근 및 휴게·일반음식점 API 응답 확인 | `[TARGET_UNIMPLEMENTED]` 국세청·행안부 resolver; 현재 Graph 미연결 |
| `LAW_API_OC` | `[PROPOSED_SHARED]` 법령 resolver 도입 시 발급 필요 | `[TARGET_UNIMPLEMENTED]` 국가법령정보 API; registry-only에는 불필요 |
| `SMES_API_TOKEN` | `[PROPOSED_SHARED]` 선택 발급 후보 | `[TARGET_UNIMPLEMENTED]` 중소벤처24 지원 공고 보강 |
| `FOOD_SAFETY_KOREA_API_KEY` | `[PROPOSED_SHARED]` 선택 발급 후보 | `[TARGET_UNIMPLEMENTED]` 식품안전나라 보조 수집 |

비밀값과 Authorization header, 실제 사용자 원문·주소·사업자번호는 문서·일반 log·trace에 남기지 않습니다.

## 8. `[CURRENT_AI]` 실행과 검증

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/agent

/home/vasebull/.local/bin/ruff check backend/app/agent backend/tests/agent

PYTHONPATH=backend backend/.venv/bin/python \
  -m app.agent.cli --live --compact --trace-id local-live-smoke
```

unit test는 mock provider/fetcher를 사용하므로 외부 network·credential·quota를 쓰지 않습니다. CLI의 `--live`는 실제 LLM과 공식 원문 요청을 명시적으로 허용합니다. 실제 지원 공고 discovery는 Graph의 합성 catalog와 별도로 검증해야 합니다.

## 9. 데이터 모드별 현재·목표 상태

| 모드 | 상태 라벨 | Case | 절차 | 지원사업 | 판정 |
|---|---|---|---|---|---|
| unit/contract | `[CURRENT_AI]` | 합성 fixture | registry/mock search + mock fetch | 합성 reviewed catalog | 결정론적 CI |
| standalone CLI | `[CURRENT_AI]` | 비식별 합성 fixture | 실제 공식 registry 원문, 선택 search fallback | 합성 reviewed catalog | Agent 구조·절차 live smoke |
| support discovery | `[CURRENT_AI]` | 없음 | 없음 | 실제 기업마당 raw 후보 | ingestion 입력 검증, 자격 판정 아님 |
| BE 생산 | `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]` | 인증된 snapshot | 실제 공식 sources | 검수된 canonical catalog | 계약 승인·구현 전 |

“실제 데이터”를 보고할 때 어느 열이 실제인지 반드시 함께 말합니다. 현재 CLI 전체 성공은 실제 사용자 Case나 실제 지원 자격 결과가 아닙니다.

## 10. `[CURRENT_AI]` standalone 완료 기준

2026-09-15 standalone 범위 검증 결과입니다. 아래 항목은 BE 생산 연동 완료를 뜻하지 않으며, 실제 사용자 Case에 필요한 경계는 §11에 별도로 남깁니다.

- [x] strict public/provider/local schema와 JSON Schema 생성 통과
- [x] registry-only 조회와 registry→Kakao→Google attempt/counter 검증
- [x] HTTPS/allowlist/redirect/IP-literal/MIME/size/timeout 거부 테스트
- [x] document와 Evidence의 URL/excerpt/time/freshness/hash 1:1 검증
- [x] `COMPLETE | PARTIAL | NO_RESULTS`와 기술 실패 구분
- [x] Procedure→Info→Support→Supervisor→Review call/digest 연결
- [x] lookup에 없는 절차·기관·서류·기한·URL 생성 차단
- [x] unknown/stale source로 확정 claim 생성 차단
- [x] 웹 Evidence만으로 progress 완료나 `CASE_COMPLETE` 생성 차단
- [x] raw 지원 공고의 `ReviewedSupportCatalog` 자동 승격 차단
- [x] Review 우회와 retry 상한 초과 시 `SAFE_FAILURE`
- [x] Agent tests, Ruff check, format check 통과 (`349 passed`)
- [x] live 결과는 실제 URL이 아니라 domain·문서 수·status와 조회시각만 안전하게 기록

## 11. BE 연동 전에 남은 제안·미구현 경계

아래는 모두 구현 완료 항목이 아닙니다. 상태는 `[PROPOSED_SHARED][TARGET_UNIMPLEMENTED]`이며, “제안 소유자”가 작성한다고 바로 확정되는 것이 아니라 마지막 열의 주체가 계약을 승인해야 합니다.

| 남은 항목 | 제안 소유자 | 확정 필요 주체 | 구분 이유 |
|---|---|---|---|
| 인증된 snapshot assembler와 canonical field/enum registry | BE | AI·BE | Agent 입력값과 저장 원천이 일치해야 함 |
| canonical procedure step ID/code/name/alias registry | AI·BE | AI·BE·PM | Agent finding과 제품 절차가 같은 ID를 써야 함 |
| 사업자번호·인허가 번호의 동의·암호화·마스킹·audit resolver | BE | BE·보안/PM | 민감 식별정보의 인증·보존 경계 |
| 행안부 API response adapter | AI | AI·BE | `[OBSERVED_2026-09-15]` 목록 HTTP 200만 확인; exact 조회 계약은 없음 |
| 인증된 식별정보로 행안부 exact 조회를 중계하는 resolver | BE | AI·BE·보안/PM | Agent prompt와 raw log에 식별정보를 노출하지 않기 위함 |
| `LAW_API_OC` 기반 법령·서식 resolver | AI | AI·BE | 법령 version·시행일을 Evidence에 묶어야 함 |
| 기업마당 원문 보존·검수·catalog version 발행 pipeline | AI·데이터 운영 | AI·BE·PM | raw 공고를 지원 자격으로 자동 승격하지 않기 위함 |
| Evidence 저장/resolver와 cache·재검증 정책 | AI·BE | AI·BE | Agent evidence ID와 영속 원문을 연결해야 함 |
| DNS private-address/rebinding 방어와 production egress | Platform·AI | Platform·보안 | 외부 fetch의 SSRF·재바인딩 방어 |
| PlanningCoordinator, 인증·소유권, idempotency, version/CAS | BE | AI·BE | 실제 Case 동시성과 중복 실행 통제 |
| Output/State Transition Guardrail과 atomic persistence | BE | AI·BE | 검토 결과와 Case 변경 이력의 원자성 보장 |
| Langfuse adapter와 prompt/PII redaction·비용 보존 정책 | AI·Platform | AI·BE·보안/PM | 관측성과 개인정보 보존 범위를 함께 결정 |
| 임의 자연어·실제 Case를 받는 외부 HTTP adapter | BE | AI·BE·FE | 현재 Python 호출을 제품 API로 매핑해야 함 |
| production LLM endpoint/model과 고정 평가셋 | AI | AI·PM | semantic schema 반복 통과율과 품질 기준 필요 |

`[PROPOSED_SHARED]` 역할 경계는 AI가 source 조회·검증·해석을 소유하고, BE가 인증된 Case와 canonical ID, 개인정보·네트워크·저장 경계를 제공하는 안입니다. 공동 승인 전에는 확정 책임 분장으로 해석하지 않습니다.
