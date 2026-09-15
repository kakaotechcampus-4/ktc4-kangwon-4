# RE:BORN Agent standalone 실행 Runbook 및 상태

> 소유: AI
>
> 기준일: 2026-09-15
>
> 내부 schema version: `agent-io/2.0`
>
> 이 문서의 책임: **BE 없는 실행법, 환경변수, 데이터 모드, 검증 결과, 현재 한계**

구성요소의 정확한 필드는 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md), 호출 구조는 [`architecture.md`](./architecture.md), 데이터 수집 계획은 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md), 생산 연동 요구는 [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)를 따른다.

`[CURRENT_AI]`는 현재 코드·테스트가 있는 기능, `[NOT_WIRED]`는 구현체가 현재 Graph에 미연결인 기능, `[PLANNED_AI][NOT_IMPLEMENTED]`는 AI가 구현할 목표, `[PROPOSED_SHARED][NOT_APPROVED]`는 공동 승인 전 제안, `[OBSERVED_YYYY-MM-DD]`는 해당 날짜의 제한된 실호출만 뜻한다.

## 1. 결론

`[CURRENT_AI]` Agent Graph는 BE와 DB 없이 실행된다. 그러나 현재 CLI가 받는 것은 임의 자연어나 실제 사용자 Case가 아니라 코드에 고정된 비식별 fixture다.

| 범위 | 상태 | 현재 사용하는 데이터 |
|---|---|---|
| LangGraph 실행, Review, safe failure | `[CURRENT_AI]` | schema-valid fixture 입력 |
| LLM 분석 | `[CURRENT_AI]` | 설정된 OpenAI-compatible endpoint의 실제 응답 |
| 폐업 절차조회 | `[CURRENT_AI]` | 공식 registry URL에서 실행 시점에 가져온 실제 원문 |
| 지원금 분석 | `[CURRENT_AI]` | 검수됐다고 가정한 합성 `ReviewedSupportCatalog` |
| 기업마당 raw 공고 discovery | `[CURRENT_AI][NOT_WIRED]` | 별도 adapter의 실제 API 응답; CLI/Graph 판정에는 미사용 |
| 실제 사용자 Case read/write | `[PROPOSED_SHARED][NOT_APPROVED][NOT_IMPLEMENTED]` | 인증·snapshot·CAS·persistence가 없어 불가 |
| 범용 crawler·RAG | `[PLANNED_AI][NOT_IMPLEMENTED]` | corpus·index·retriever 없음 |
| Langfuse 비용 추적 | `[PLANNED_AI][NOT_IMPLEMENTED]` | 현재 기본 sink는 `NullTraceSink` |

따라서 현재 실행 결과를 “실제 Case 전체 연동 결과”라고 부르면 안 된다. **절차 원문과 LLM은 실제이고, Case와 지원금 catalog는 합성**이다.

## 2. 사전 조건

- Python 3.12
- `backend/requirements.txt`와 개발 검증 시 `backend/requirements-dev.txt` 설치
- 정적 검사 시 Ruff 0.16.5 별도 설치. 현재 `requirements-dev.txt`에는 Ruff가 pin돼 있지 않으므로 이를 설치 완료의 근거로 보지 않는다.
- 저장소 루트 `.env` 또는 동일 이름의 process environment
- 외부 호출을 허용할 네트워크

standalone은 MySQL을 읽거나 쓰지 않는다. `docker compose up -d db`는 BE의 DB 개발용이며 Agent CLI 실행 조건이 아니다. 루트 Compose에는 DB만 들어 있다.

## 3. 현재 CLI가 소비하는 환경변수

process environment가 저장소 루트 `.env`보다 우선한다. 비밀값은 출력·문서·trace에 남기지 않는다.

### 3.1 LLM — 필수

| 변수 | 필수 여부 | 의미 |
|---|---|---|
| `CHAT_PROXY_URL` | 필수 | OpenAI-compatible chat endpoint base URL |
| `PROXY_TOKEN` | 필수 | endpoint credential |
| `OPENAI_MODEL` | 필수 | endpoint가 실제 지원하는 model ID |
| `OPENAI_REASONING_EFFORT` | 선택 | provider가 지원할 때만 전달 |
| `AGENT_LLM_TIMEOUT_SECONDS` | 선택 | provider 시도 deadline |
| `AGENT_LLM_MAX_RETRIES` | 선택 | provider retry 상한 |
| `AGENT_LLM_RETRY_BACKOFF_SECONDS` | 선택 | 첫 retry backoff, `0..60`초 |
| `AGENT_LLM_MAX_RESPONSE_BYTES` | 선택 | 응답 크기 상한, 기본 1,000,000 bytes |

### 3.2 절차조회 — registry는 key 불필요

| 변수 | 필수 여부 | 의미 |
|---|---|---|
| `PROCEDURE_OFFICIAL_REGISTRY_ENABLED` | 선택, 기본 `true` | 코드 검토된 공식 URL registry 사용 |
| `PROCEDURE_KAKAO_REST_API_KEY` | 선택 | registry miss 시 1차 URL discovery |
| `PROCEDURE_GOOGLE_API_KEY` | 선택 | Kakao miss 시 2차 URL discovery |
| `PROCEDURE_GOOGLE_PROJECT_ID` | Google 사용 시 필수 | Google Cloud project |
| `PROCEDURE_GOOGLE_ENGINE_ID` | Google 사용 시 필수 | 공개 웹사이트 engine |
| `PROCEDURE_GOOGLE_LOCATION` | 선택, 기본 `global` | `global`, `us`, `eu` 중 하나 |
| `PROCEDURE_SEARCH_ALLOWED_DOMAINS` | 선택 | 코드 검토된 trust root 범위 안에서 allowlist 축소 |
| `PROCEDURE_SEARCH_TIMEOUT_SECONDS` | 선택, 기본 `8` | 요청별 timeout |
| `PROCEDURE_SEARCH_TOTAL_TIMEOUT_SECONDS` | 선택, 기본 `60` | lookup 전체 deadline |
| `PROCEDURE_SEARCH_MAX_RETRIES` | 선택, 기본 `1` | 외부 요청 retry, `0..4` |
| `PROCEDURE_SEARCH_RETRY_BACKOFF_SECONDS` | 선택, 기본 `0.25` | retry backoff |
| `PROCEDURE_SEARCH_MAX_RESPONSE_BYTES` | 선택, 기본 `1000000` | 검색 응답·원문 크기 상한 |
| `PROCEDURE_SEARCH_MAX_REDIRECTS` | 선택, 기본 `3` | redirect 상한 |

`PROCEDURE_SEARCH_API_KEY`와 `KAKAO_CLIENT_ID`는 Kakao key의 deprecated 호환 alias다. 새 설정에서는 `PROCEDURE_KAKAO_REST_API_KEY`만 사용한다. Naver 검색 결과는 Agent 입력으로 사용하지 않는다.

`BIZINFO_API_KEY`는 별도 discovery adapter가 소비하지만 현재 CLI는 소비하지 않는다. `DATA_GO_KR_SERVICE_KEY`, `LAW_API_OC`, `LANGFUSE_*`, RAG 관련 값도 현재 CLI에는 연결되지 않았다. 해당 계획은 데이터 구현 계획과 기술 상태표에만 기록한다.

## 4. 실행

저장소 루트에서 실행한다.

```bash
PYTHONPATH=backend backend/.venv/bin/python \
  -m app.agent.cli --live --compact --trace-id local-live-smoke
```

`--live`는 실제 LLM과 공식 원문 HTTP 요청을 허용한다는 명시적 플래그라 필수다. 결과는 `REVIEWED_PLAN`, `CONFLICT`, `SAFE_FAILURE` 중 하나다.

| 종료 코드 | 의미 |
|---:|---|
| `0` | `REVIEWED_PLAN` 또는 `CONFLICT`를 schema-valid하게 반환 |
| `2` | 구성 오류, provider 오류 또는 `SAFE_FAILURE`; 민감한 내부 예외는 CLI에 출력하지 않음 |

현재 CLI에는 자연어 인자가 없다. 임의 자연어를 실행하려면 이를 redaction하고 `CaseSnapshot`, Evidence, canonical step, reviewed catalog와 함께 `SupervisorRunInput`으로 조립하는 adapter가 필요하다. 실제 Case용 adapter는 BE 공동 계약과 구현 전이다.

## 5. 데이터 모드

| 모드 | Case | 절차 원문 | 지원사업 | 용도 |
|---|---|---|---|---|
| unit/contract test | 합성 | mock search/fetch 또는 registry | 합성 reviewed catalog | 결정론적 검증 |
| standalone CLI | 합성 fixture | 실제 공식 원문; 선택 search fallback | 합성 reviewed catalog | Agent core·절차 live smoke |
| BizInfo discovery | 없음 | 없음 | 실제 raw 공고 후보 | ingestion 입력 확인; 자격 판정 아님 |
| 생산 | 미구현 | 목표: 공식 sources | 목표: 검수 catalog/RAG | 인증된 실제 Case 연동 |

“실제 데이터로 실행했다”는 보고에는 어느 열이 실제인지 반드시 같이 기록한다. 외부 API의 HTTP 200은 데이터 원본 접근 확인이며, 실제 Case 조립·판정·저장 완료를 뜻하지 않는다.

## 6. 검증

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/agent

ruff check backend/app/agent backend/tests/agent

ruff format --check backend/app/agent backend/tests/agent
```

| 기준일 | 코드 기준 commit | 결과 | 범위 |
|---|---|---|---|
| 2026-09-15 | `350f07b` | `349 passed`; Ruff check·format check 통과 | mock 기반 Agent test와 정적 검사 |

unit test는 외부 credential·quota를 쓰지 않는다. live smoke는 별도이며 외부 endpoint 상태와 모델의 structured-output 품질에 영향을 받는다.

`[OBSERVED_2026-09-15]` 팀 proxy에서 확인된 `openai/gpt-4.1-mini`로 `REVIEWED_PLAN / NEEDS_MORE_INFO / PASS`까지 완료된 실행과 `REVIEW_RETRY_EXHAUSTED`로 안전 종료된 실행을 모두 관찰했다. 이는 지속 가용성이나 생산 SLO가 아니다.

## 7. 현재 한계

- 실제 사용자 Case 조회·저장, 인증·소유권, version/CAS, transaction이 없다.
- CLI가 임의 자연어와 사업자 정보를 받지 않는다.
- Support Agent는 실제 raw 공고가 아니라 합성 reviewed catalog를 사용한다.
- 기업마당 discovery 결과를 검수 catalog로 승격하는 pipeline이 없다.
- 범용 crawler, parser/chunker corpus, vector index, RAG retriever가 없다.
- Langfuse adapter가 없어 token·비용을 전송하지 않는다.
- 공식 사이트나 LLM endpoint 장애 시 성공을 보장하지 않으며 안전 실패할 수 있다.
- 현재 Info prompt의 CURRENT Evidence relevance 안내에는 `NOT_RELEVANT`가 적혀 있지만 실제 schema enum은 `POSSIBLY_RELEVANT`다. runtime validator는 schema enum을 기준으로 거부·재시도하므로 live 안정성을 위해 별도 코드 수정이 필요하다(`backend/app/agent/info_agent/agent.py`).

생산 연동이 되려면 BE 전달 문서의 공동 계약이 승인되고 구현·통합 테스트까지 완료돼야 한다.

## 8. 근거

| 내용 | 저장소 근거 |
|---|---|
| CLI 플래그·fixture·종료 코드 | `backend/app/agent/cli.py`, `backend/app/agent/fixtures.py` |
| LLM 환경변수·retry | `backend/app/agent/llm.py` |
| 절차조회 환경변수·trust root | `backend/app/agent/procedure_tool/models.py`, `tool.py` |
| 현재 Graph 결과 | `backend/app/agent/graph.py`, `schemas.py` |
| BizInfo 별도 adapter | `backend/app/agent/support_agent/discovery_tool.py` |
| DB-only Compose | `docker-compose.yml` |
| 검증 suite | `backend/tests/agent/` |
