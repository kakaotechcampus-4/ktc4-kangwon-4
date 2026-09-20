# RE:BORN Agent standalone 실행 안내

> 소유: AI
>
> 기준일: 2026-09-20
>
> 내부 schema version: `agent-io/2.0`

이 문서는 **실제 Case를 export한 JSON으로 Agent를 실행하는 방법과 현재 연동 범위**를 설명한다.

- 구성요소의 정확한 필드: [`tool-io-schema.md`](./tool-io-schema.md)
- 호출 구조: [`architecture.md`](../architecture.md)
- 공식 데이터 수집 계획: [`official-data-sources.md`](./official-data-sources.md)
- 생산 연동 요구사항: [`be-integration-requirements.md`](./be-integration-requirements.md)
- 실제 API·DB 검증 현황: [`live-verification.md`](./live-verification.md)

## 1. 한눈에 보는 결론

현재 CLI는 BE에서 준비한 **실제 `AgentGraphInput`과 실제 절차 registry JSON**을 필수로 받는다.
CLI가 DB를 직접 읽거나 결과를 저장하지는 않는다. 코드 클래스명은 `AgentGraph`지만 별도 Agent가
아니라 LangGraph `StateGraph`를 구성·실행하는 프로젝트 내부 실행기다.

현재 실행의 데이터 출처는 다음과 같다.

- **실제 외부 응답:** 설정된 OpenAI-compatible LLM endpoint의 응답. Supervisor 전용 설정이 있으면 Supervisor만 다른 endpoint·model을 쓰고 정보분석·지원금·Review는 공용 설정을 쓴다
- **실제 Case 입력:** `--request`가 가리키는 BE export. 비식별 입력, snapshot, 근거를 기존 `AgentGraphInput` 계약에 맞춰 제공한다
- **실제 절차 registry:** `--procedure-steps`가 가리키는 `KnownProcedureStep[]`. DB의 실제 ID·code·표시명·별칭을 사용한다
- **공식 원문:** 미리 수집한 절차 스냅샷. 실행 중 인터넷 조회는 없으며, 현재 원문 3건은 모두 미검수여서 `UNKNOWN`으로 유지한다
- **지원사업:** 설정된 실제 카탈로그에서 검수와 조건 작성이 끝난 항목만 사용한다. 현재 수집 공고 7건 중 서비스 가능한 항목은 0건이다
- **선택적 Wiki:** `--support-wiki`를 지정하면 지원사업 ID·UUID로 실제 노트를 읽고 검수 조건을 확인한다. 운영 Wiki 형식 승인과 실제 HIT 실행 검증은 남아 있다
- **별도 수집 명령:** 기업마당 실제 API로 공고 후보를 갱신할 수 있다. 수집만으로 검수 catalog에 승격되지 않는다

fixture 생성과 demo catalog fallback은 CLI에서 제거했다. 실제 export가 없으면 실행 입력을
만들어 대체하지 않는다. CLI의 정상 결과는 해당 입력으로 분석·검수를 실행했다는 뜻이며,
실제 사용자 Case의 `read → plan → review → persist → read-back` 완료는 별도 확인해야 한다.

## 2. 지금 가능한 것과 불가능한 것

### 현재 실행되는 기능

- LangGraph 실행, Review 재작업, fail-closed `SAFE_FAILURE`
- 설정된 endpoint를 이용한 실제 LLM 분석. Supervisor는 별도 endpoint·model로 분리할 수 있고, 미설정이면 공용 설정을 그대로 쓴다
- 검수 스냅샷에서 공식 절차 원문 조회(네트워크 없음)
- 실제 검수 catalog를 이용한 지원사업 조건 비교. 검수 항목이 없으면 `NO_CANDIDATE`
- 실제 export JSON을 기존 schema로 검증한 뒤 실행하는 CLI

### 구현됐지만 현재 실행 흐름에는 연결되지 않은 기능

- `BizInfoSupportDiscoveryTool`의 기업마당 raw 공고 조회
  - 별도 adapter로 실제 API 응답을 받을 수 있다.
  - 갱신 결과는 검수 전 후보이며 Graph에서 자동 사용하거나 catalog로 자동 발행하지 않는다.
- `support_agent.rag.cli`의 미검수 공고 Chroma 색인·검색
  - 실제 공고·임베딩 API로 별도 저장·검색을 확인했다. [실행 안내](./support-retrieval.md) 참조.
  - 검수·DB 매핑·S3 확인 전 자료를 운영 Support Agent에 주입하지 않는다.

### 아직 할 수 없는 기능

- 실제 사용자 Case 조회·저장
- 인증, Case 소유권 확인, version/CAS와 transaction
- CLI에서 임의 자연어나 사업자 정보 입력
- 기업마당 raw 공고를 검수 catalog로 발행하는 pipeline
- 범용 crawler, PDF parser, 검수 corpus의 S3 확인과 운영 RAG 연결
- Langfuse 비용 금액 산출 — token 수는 전송하지만 금액으로 환산하지 않는다

## 3. 실행 전 준비

### 필수 환경

- Python 3.12
- `backend/requirements.txt`
- LLM endpoint를 호출할 수 있는 네트워크(절차조회에는 네트워크가 필요 없다)
- 저장소 루트 `.env` 또는 같은 이름의 process environment
- BE가 소유권·비식별 처리를 거쳐 export한 실제 `AgentGraphInput` JSON
- 같은 Case에서 사용할 실제 `KnownProcedureStep[]` registry JSON

정적 검사에는 Ruff 0.16.5를 별도로 설치한다. 현재 `requirements-dev.txt`에는 Ruff가 pin돼 있지 않으므로 해당 파일 설치만으로 Ruff 준비가 끝났다고 보지 않는다.

standalone은 MySQL을 읽거나 쓰지 않는다. `docker compose up -d db`는 BE의 DB 개발용이며 Agent CLI 실행 조건이 아니다. 루트 Compose에는 DB만 들어 있다.
입력 export의 DB 조회 함수와 결과 저장은 BE 담당이다. 물리 필드·enum 기준은
[`schema_table.md`](../schema/schema_table.md)이며, 누락된 ID·근거·시각을 AI가 만들어 채우지 않는다.

### LLM 설정 — 필수

process environment가 저장소 루트 `.env`보다 우선한다. 비밀값은 출력·문서·trace에 남기지 않는다.

- `CHAT_PROXY_URL`: OpenAI-compatible chat endpoint base URL
- `PROXY_TOKEN`: endpoint credential
- `OPENAI_MODEL`: endpoint가 실제 지원하는 model ID

Supervisor만 다른 provider·model로 분리할 때 다음 세 값을 설정한다. 비어 있으면 항목별로 위 공용 값으로 폴백한다. 정보분석·지원금·Review는 이 값과 무관하게 항상 공용 설정을 쓴다.

- `SUPERVISOR_CHAT_PROXY_URL`: 선택; Supervisor 전용 chat endpoint base URL
- `SUPERVISOR_PROXY_TOKEN`: 선택; Supervisor 전용 endpoint credential
- `SUPERVISOR_MODEL`: 선택; Supervisor 전용 model ID

다음 값은 선택 사항이다.

- `OPENAI_REASONING_EFFORT`: provider가 지원할 때만 전달
- `AGENT_LLM_TIMEOUT_SECONDS`: provider 시도 deadline, 기본 45초. **전체 실행 상한보다 작게 둔다** — 같거나 크면 호출 한 번이 전체 예산을 통째로 쓸 수 있다
- `AGENT_LLM_MAX_RETRIES`: provider retry 상한. retry 시도도 실행당 LLM 호출 예산을 1회로 센다
- `AGENT_LLM_RETRY_BACKOFF_SECONDS`: 첫 retry backoff, `0..60`초
- `AGENT_LLM_MAX_RESPONSE_BYTES`: 응답 크기 상한, 기본 `1,000,000` bytes

실행 단위 한도는 다음 두 값이다.

- `AGENT_MAX_LLM_CALLS_PER_RUN`: 실행 1건의 LLM 호출 총 횟수, 기본 40회. 실제 HTTP 호출을 세고 retry도 1회로 센다. 넘으면 `LOOP_LIMIT_REACHED` 사유의 `SAFE_FAILURE`
- `AGENT_RUN_DEADLINE_SECONDS`: 실행 1건의 전체 시간, 기본 60초. 넘으면 `RUN_DEADLINE_EXCEEDED` 사유의 `SAFE_FAILURE`

공용 client와 Supervisor 전용 client가 한 실행의 예산 하나를 공유한다. 예산과 시간은 실행이 시작될 때 그 실행 몫으로 새로 만들어지므로, 한 프로세스가 동시에 두 요청을 처리해도 집계가 섞이지 않는다.

두 한도의 의미와 실측 기록은 [`runtime-limits.md`](./runtime-limits.md)가 단일 출처다.

### 절차조회 설정 — 요청 경로에는 key도 네트워크도 필요 없다

사용자 요청 경로는 검수 스냅샷만 읽는다.

- `AGENT_PROCEDURE_STORE_PATH`: 선택; 비워 두면 패키지에 포함된 `backend/app/agent/procedure_tool/data/reviewed-procedures.ko-KR.json`

아래 검색 설정은 **갱신 명령에서만** 쓴다. 갱신은 **공식 registry → Kakao → Google** 순서로 공식 URL을 찾으며, registry에 등록된 문서는 검색 key 없이 직접 조회할 수 있다. 자세한 내용은 [`procedure-knowledge.md`](./procedure-knowledge.md)에 있다.

- `PROCEDURE_OFFICIAL_REGISTRY_ENABLED`: 선택, 기본 `true`; 코드 검토된 공식 URL registry 사용
- `PROCEDURE_KAKAO_REST_API_KEY`: 선택; registry miss 시 1차 URL discovery
- `PROCEDURE_GOOGLE_API_KEY`: 선택; Kakao miss 시 2차 URL discovery
- `PROCEDURE_GOOGLE_PROJECT_ID`: Google 사용 시 필수; Google Cloud project
- `PROCEDURE_GOOGLE_ENGINE_ID`: Google 사용 시 필수; 공개 웹사이트 engine
- `PROCEDURE_GOOGLE_LOCATION`: 선택, 기본 `global`; `global`, `us`, `eu` 중 하나
- `PROCEDURE_SEARCH_ALLOWED_DOMAINS`: 선택; 코드 검토된 trust root 범위 안에서 allowlist 축소
- `PROCEDURE_SEARCH_TIMEOUT_SECONDS`: 선택, 기본 `8`; 요청별 timeout
- `PROCEDURE_SEARCH_TOTAL_TIMEOUT_SECONDS`: 선택, 기본 `60`; lookup 전체 deadline
- `PROCEDURE_SEARCH_MAX_RETRIES`: 선택, 기본 `1`; 외부 요청 retry, `0..4`
- `PROCEDURE_SEARCH_RETRY_BACKOFF_SECONDS`: 선택, 기본 `0.25`; retry backoff
- `PROCEDURE_SEARCH_MAX_RESPONSE_BYTES`: 선택, 기본 `1000000`; 검색 응답·원문 크기 상한
- `PROCEDURE_SEARCH_MAX_REDIRECTS`: 선택, 기본 `3`; redirect 상한

`PROCEDURE_SEARCH_API_KEY`와 `KAKAO_CLIENT_ID`는 Kakao key의 deprecated 호환 alias다. 새 설정에서는 `PROCEDURE_KAKAO_REST_API_KEY`만 사용한다. Naver 검색 결과는 Agent 입력으로 사용하지 않는다.

### 지원사업 catalog 설정

- `AGENT_SUPPORT_CATALOG_PATH`: 선택; 비워 두면 `backend/app/agent/support_agent/data/reviewed-support.ko-KR.json`

파일이 없거나 손상되면 실행에 실패한다. 검수 항목이 없는 유효한 파일은 빈 catalog로 사용한다.
데모 지원사업으로 바꾸지 않는다. 상세 규칙은 [`support-knowledge.md`](./support-knowledge.md)를 따른다.

### 관측 설정과 아직 미연결된 설정

- `BIZINFO_API_KEY`: 별도 기업마당 discovery adapter만 사용
- `DATA_GO_KR_SERVICE_KEY`, `LAW_API_OC`: 현재 CLI 미연결
- `LANGFUSE_PUBLIC_KEY`·`LANGFUSE_SECRET_KEY`: 둘 다 있어야 전송이 켜진다. 하나라도 비거나 SDK client 생성이 실패하면 `NullTraceSink`로 남아 아무 데도 보내지 않는다
- `LANGFUSE_BASE_URL`: Langfuse 주소. Cloud는 `https://cloud.langfuse.com`, 셀프호스팅이면 그 주소. `tracing.py`가 process env 또는 저장소 루트 `.env`에서 읽어 SDK에 직접 넘긴다(SDK 자체는 `.env`를 읽지 않는다)
- RAG 관련 값: 운영 Graph의 검수 corpus·S3 연결은 미완료. 미검수 공고의 오프라인 검색은 별도 구현
  - 별도 검색 명령은 `EMBEDDING_PROXY_URL`·`PROXY_TOKEN`·`OPENAI_EMBEDDING_MODEL`을 사용한다.
    실행 전제와 명령은 [support-retrieval.md](./support-retrieval.md#실행)를 따른다.

Langfuse 설정은 현재 runtime에서 사용한다. 나머지 미연결 값은 데이터 구현 계획과 기술 상태표에 기록한다.

## 4. 실행 방법

BE가 실제 입력 파일을 준비한 뒤 저장소 루트에서 실행한다. 아래 대문자 인자는 해당 파일의
실제 경로로 바꾼다. 결과 경로는 아직 존재하지 않는 새 파일이어야 한다.

```bash
PYTHONPATH=backend backend/.venv/bin/python \
  -m app.agent.cli --live \
  --request CASE_REQUEST_JSON \
  --procedure-steps PROCEDURE_STEPS_JSON \
  --output NEW_RESULT_JSON \
  --max-llm-calls 20 \
  --deadline-seconds 120
```

| 인자 | 동작 |
|---|---|
| `--request` | 필수. 실제 `AgentGraphInput` JSON 파일, 최대 4 MiB |
| `--procedure-steps` | 필수. 실제 `KnownProcedureStep[]` JSON 파일, 최대 4 MiB |
| `--live` | 필수. 설정된 실제 LLM 호출 허용 |
| `--support-wiki` | 선택. 읽기 전용 지원사업 Wiki 폴더. 실제 DB ID·UUID와 검수 노트가 필요하며 형식은 [support-wiki.md](./support-wiki.md) 참조 |
| `--max-llm-calls` | 선택. 양의 정수 호출 예산. 생략하면 `AGENT_MAX_LLM_CALLS_PER_RUN` 사용 |
| `--deadline-seconds` | 선택. 유한한 양수, 최대 600초. 생략하면 `AGENT_RUN_DEADLINE_SECONDS` 사용 |
| `--output` | 선택. 결과 JSON을 새 파일에 권한 `0600`으로 기록. 기존 파일·symlink 덮어쓰기 거부. 생략하면 stdout |
| `--trace-id` | 선택. export의 trace ID를 덮어쓸 관측 ID. 생략하면 입력값 유지 |
| `--compact` | 선택. 줄바꿈 들여쓰기 없는 JSON 출력 |

출력 파일은 LLM 호출 전에 예약한다. 처리 중 예외가 나면 빈 파일이 남을 수 있으므로 파일 존재만으로
성공을 판단하지 않고 종료 코드와 결과의 `outcome_type`을 확인한다.
절차조회는 로컬 스냅샷을 읽으며 `--live`와 무관하게 네트워크를 쓰지 않는다.

결과는 다음 셋 중 하나다.

- `REVIEWED_PLAN`: Review를 통과한 계획 후보
- `CONFLICT`: 확정 사실과 새 입력이 충돌해 현재 run만 안전 종료
- `SAFE_FAILURE`: 구성요소 실패, Review 재작업 상한 소진, 실행당 LLM 호출 예산 소진(`LOOP_LIMIT_REACHED`) 또는 전체 시간 초과(`RUN_DEADLINE_EXCEEDED`)를 fail-closed 처리

종료 코드는 다음과 같다.

- `0`: `REVIEWED_PLAN` 또는 `CONFLICT`를 schema-valid하게 반환
- `2`: 구성 오류, provider 오류 또는 `SAFE_FAILURE`; 민감한 내부 예외는 CLI에 출력하지 않음

현재 CLI에는 자연어 단독 인자가 없다. 사용자 발화는 BE에서 비식별 처리하고 실제 `CaseSnapshot`,
Evidence와 함께 `AgentGraphInput`으로 조립해야 한다. CLI의 JSON 입력 지원은 DB export adapter나
저장 API를 구현한 것이 아니다. 실제 Case adapter의 공동 계약과 연결이 남아 있다.

### 다른 코드에서 부를 때

CLI는 얇은 껍데기이고, 실제 조립과 실행은 `app.agent.runtime`에 있다. BE 라우터처럼 외부에서 부를 때는 이쪽을 쓴다.

```python
from app.agent.runtime import build_runtime

runtime = await build_runtime(
    known_procedure_steps=...,   # 검수된 절차 단계 목록
    support_catalog=...,         # 검수된 지원사업 catalog
    procedure_store=...,         # 선택: 미리 로딩한 ReviewedProcedureStore
    support_wiki=...,            # 선택: 실제 ID/UUID를 조회하는 SupportWikiStore
)
outcome = await runtime.run_planning(request, deadline_seconds=...)
```

`build_runtime`은 프로세스마다 한 번 부른다. `run_planning`은 요청마다 부르며, 그 실행 몫의 호출 예산과 시간 상한을 스스로 만든다. `deadline_seconds`를 넘기면 호출자의 남은 시간을 그대로 쓴다.

`procedure_store`를 생략하면 기존 JSON 스냅샷을 사용한다. 주입하는 저장소는 동기식
`snapshot_version`·`records()` 인터페이스로, 요청 전에 자료를 메모리에 읽어 둬야 한다.
BE 연결 시에는 합의된 BE 조회 함수로 준비하며 Agent가 직접 SQL·ORM을 호출하지 않는다.
DB 연결이나 새 스키마를 추가한 것은 아니다. 저장소 로딩 오류를 합성 자료로 숨기지 않는다.

Wiki를 선택해 연결하면 `CHECK_SPECIFIC/REFRESH_STALE`은 요청의 정확한 ID·UUID부터 조회한다.
`DISCOVER_RELEVANT`는 기존 catalog가 제공한 참조만 조회한다. 미검수·자료 없음은
이전 catalog 조건으로 대체하지 않으며, 누락이 하나라도 있으면 `PARTIAL`로 보존한다.
Wiki miss를 Chroma·S3로 넘기는 A8 경로는 아직 없다.

프로젝트에 추가한 Vault는 [`obsidian/`](./obsidian/README.md)다. 검수 노트를 준비한 뒤
`--support-wiki docs/agent/obsidian/지원사업/검수완료`로 연결한다. 현재 실제 수집 노트는
`미검수/`에 있고, 검수 완료 지원사업은 0건이므로 파일 경로만 지정해도 HIT가 되는 것은 아니다.

## 5. 실행 모드별 데이터

### 과거 단위·계약 테스트와 smoke

기존 테스트 suite와 과거 CLI smoke에는 합성 Case·지원사업, mock 응답이 사용됐다.
이 기록은 구성요소 개발 이력이며 실제 사용자 Case·DB 저장 검증으로 세지 않는다.
현재 사용자는 dummy/mock 검증을 제외하고 실제 API·DB 확인을 요구했으므로 해당 검증을 재실행하지 않는다.

### standalone CLI

- Case와 절차 registry: 실제 BE export 파일
- 절차 자료: 공식 원문 스냅샷과 원래 검수 상태(네트워크 없음)
- 지원사업: 실제 검수 catalog. 현재 검수 0건을 그대로 유지
- LLM: 설정된 실제 endpoint
- 목적: 실제 입력의 Agent 분석·검수. CLI는 DB read/write를 수행하지 않음

### 기업마당 discovery 직접 호출

- Case와 절차 자료: 사용하지 않음
- 지원사업: 실제 API의 raw 공고 후보
- 목적: ingestion 입력 확인
- 제한: 지원 자격 판정이나 Graph 실행이 아님

### 생산 실행

현재 미구현이다. 목표는 인증된 실제 Case, 공식 source, 검수된 catalog/RAG를 연결하는 것이다.

“실제 데이터로 실행했다”는 보고에는 Case, 절차 원문, 지원사업, LLM 중 무엇이 실제인지 반드시 함께 기록한다. 외부 API의 HTTP 200은 데이터 원본 접근 확인이며 실제 Case 조립·판정·저장 완료를 뜻하지 않는다.

## 6. 검증 방법과 기록

현재 검증은 실제 입력·실제 API·DB 상태를 기준으로 기록한다.
실행 여부와 막힌 단계는 [`live-verification.md`](./live-verification.md)에서 확인한다.
실제 Case export가 준비되기 전에는 CLI 수정의 정적 상태만 다음 명령으로 확인할 수 있다.

```bash
ruff check backend/app/agent/cli.py
PYTHONPATH=backend backend/.venv/bin/python -m app.agent.cli --help
```

이번 CLI 변경은 Ruff, 소스 compile, `--help`, diff 공백 검사를 확인했다.
더미 입력·mock·pytest 실행은 하지 않았다. 이는 실제 Case 실행 성공을 의미하지 않는다.

과거 검증 기록:

- 2026-09-15 commit `350f07b`: `349 passed`
- 2026-09-16 기준: `376 passed`
- 2026-09-19 기준: `510 passed`; Ruff check·format check 통과
  - 절차 스냅샷 조회, 실행 단위 한도 격리, 결정적 claim 정책 회귀 검증 추가
- 2026-09-20 실제 입력 CLI 전환 전: `609 passed`. 현재 CLI 변경 후의 실제 동작 검증 결과가 아님

과거 live smoke 실측(소요 시간, LLM 호출 수, 구성요소별 지연)은
[`runtime-limits.md`](./runtime-limits.md) §2에 둔다. 합성 입력을 사용한 당시 기록은 현재 실제 Case
분석·저장 성공이나 지속 가용성을 입증하지 않는다.

## 7. 생산 연동 전 남은 작업

### AI 후속 작업

- 기업마당 discovery 결과를 구조화·검수해 immutable catalog로 발행
- 승인된 공식 출처용 bounded crawler와 parser/chunker 구현
- versioned corpus, vector index, retriever와 Evidence 변환 경로 연결
- Langfuse 전송 내용의 masking 정책 승인과 보존 기간 결정

### BE·AI 공동 작업

- 인증과 Case 소유권 확인
- 실제 Case snapshot adapter
- version/CAS와 transaction 기반 저장
- 실제 사용자 입력 redaction·조립 경계
- 통합 테스트와 저장 후 read-back

공식 사이트나 LLM endpoint 장애 시 standalone 성공을 보장하지 않으며 안전 실패할 수 있다. 생산 연동 완료로 판단하려면 BE 전달 문서의 공동 계약이 승인되고 실제 구현과 통합 테스트까지 끝나야 한다.

## 8. 저장소 근거

- 실제 입력 CLI·종료 코드: `backend/app/agent/cli.py`
- 조립과 실행 단위 한도: `backend/app/agent/runtime.py`, `backend/app/agent/run_scope.py`
- LLM 환경변수·retry·실행당 호출 예산: `backend/app/agent/llm.py`
- 절차 스냅샷 조회: `backend/app/agent/procedure_tool/store.py`, `backend/app/agent/procedure_tool/stored_tool.py`
- 갱신 명령과 공식 출처 trust root: `backend/app/agent/procedure_tool/refresh.py`, `backend/app/agent/procedure_tool/models.py`, `backend/app/agent/procedure_tool/tool.py`
- 현재 Graph 결과: `backend/app/agent/graph.py`, `backend/app/agent/schemas.py`
- 기업마당 별도 adapter: `backend/app/agent/support_agent/discovery_tool.py`
- DB-only Compose: `docker-compose.yml`
- 검증 suite: `backend/tests/agent/`
