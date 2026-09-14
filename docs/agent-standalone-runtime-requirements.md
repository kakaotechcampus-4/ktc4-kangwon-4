# RE:BORN Agent 독립 실행 요구사항

> 상태: **v1.0 — 합성 fixture 기반 standalone 실행 검증 / 실데이터 adapter 미연결**
>
> 소유: AI
>
> 필드 단위 계약의 단일 출처는 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md)입니다. 이 문서는 그 계약을 BE 없이 실행하기 위해 AI 영역에 무엇이 필요하고, 어떤 조건을 만족해야 정상 동작으로 인정하는지 설명합니다. BE가 제공해야 할 항목은 [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)로 분리합니다.

## 1. 먼저 합의할 결론

현재 Agent는 BE 없이 독립 실행할 수 있습니다. 단, 독립 실행은 다음 의미로 제한합니다.

- 신뢰된 `SupervisorRunInput`, `KnownProcedureStep[]`, `ProcedureMaster`, `ReviewedSupportCatalog`를 메모리에 주입합니다.
- 정보분석 Agent, 절차조회 Tool, 지원금 Agent, Supervisor, Review Tool을 한 Graph에서 실행합니다.
- 정상 초안은 Review `PASS`를 받아야만 `REVIEWED_PLAN`으로 반환합니다.
- 충돌은 `CONFLICT`, 구성요소 실패나 검증 소진은 `SAFE_FAILURE`로 닫힙니다.
- BE API·DB·지원사업 API·Wiki·RAG·S3에는 접근하지 않습니다. `--live`에서는 설정된 chat provider에만 HTTP 요청을 보냅니다.
- 현재 CLI는 합성 fixture만 사용합니다. `--live`는 실제 LLM provider를 호출한다는 뜻이지, 실제 Case나 DB를 호출한다는 뜻이 아닙니다.

이 정의가 필요한 이유는 “LLM을 실제로 호출했다”와 “운영 데이터를 사용했다”를 혼동하지 않기 위해서입니다. 근거는 `backend/app/agent/cli.py`의 합성 fixture 고정과 `docs/agent-tool-io-schema.md` §18입니다.

## 2. 문서와 구현의 책임 경계

| 단일 출처 | 정하는 내용 | 근거 | 이유 |
|---|---|---|---|
| `/CLAUDE.md` | 제품 범위, 하지 않는 일, 개인정보와 안전 원칙 | 저장소 공통 지침 | Agent 기능이 넓어져도 제품 안전 경계를 바꾸지 않기 위해 필요합니다. |
| `docs/architecture.md` | Supervisor와 하위 Agent/Tool 책임, 호출 방향, Review 필수 경로 | §1, §3, §11 | 같은 기능을 여러 구성요소가 결정하거나 Review를 우회하지 않게 합니다. |
| `docs/agent-tool-io-schema.md` | Agent/Tool 필드, enum, 불변식, 목표 BE 계약 | §4~§21 | 문서와 코드가 서로 다른 payload를 뜻하는 문제를 막습니다. |
| `backend/app/agent/schemas.py` | 현재 실행 가능한 strict Pydantic 계약 | `AgentSchema`, 각 공개 입출력 모델 | standalone 실행에서 실제로 거부·허용되는 값을 결정합니다. |
| 이 문서 | 독립 실행 의존성, 실행 방법, 완료 기준, 한계 | 현재 구현과 검증 결과 | 실행 가능 여부와 생산 연동 완료 여부를 분리합니다. |
| `docs/be-agent-integration-requirements.md` | BE가 제공할 조회·저장·동시성·공유 DTO | 공동 계약 요청 | AI 내부 구현을 BE가 그대로 저장 모델로 사용하는 일을 막습니다. |

문서와 코드가 충돌하면 다음 순서로 처리합니다.

1. 제품 안전 원칙은 `/CLAUDE.md`를 따릅니다.
2. 현재 standalone의 실행 동작은 테스트된 Pydantic 모델과 코드가 기준입니다.
3. 생산 연동 필드는 `agent-tool-io-schema.md`의 목표 계약을 기준으로 BE와 합의합니다.
4. 합의되지 않은 필드·enum·기본값은 추정하지 않고 미지원 또는 `UNKNOWN`으로 처리합니다.

## 3. Agent 독립 실행에 필요한 입력과 의존성

| 요구사항 | 현재 공급 방식 | 근거 | 필요한 이유 | 완료 기준 |
|---|---|---|---|---|
| `SupervisorRunInput` | `build_standalone_fixture()` | `schemas.py::SupervisorRunInput`, `fixtures.py` | 한 실행의 trigger와 기준 Case를 하나로 고정해야 합니다. | 입력이 strict validation을 통과하고 입력형 trigger의 바깥 `input_event_id`와 `RedactedInput.input_event_id`가 일치하며 snapshot 자체 무결성이 성립합니다. 현재 trigger에는 Case/snapshot 참조 필드가 없습니다. |
| Graph 소유 `CaseSnapshot` copy | 합성 Case fixture | `schemas.py::CaseSnapshot`, `graph.py::run` | 실행 중 기준 Case가 바뀌면 Review 대상과 판단 기준이 달라집니다. | caller 입력을 deep copy하고 fact field, procedure step ID, Evidence record ID가 각각 unique이며 fact/progress ref가 resolve됩니다. 정상 Graph 반환 전 owned snapshot digest가 실행 전과 같습니다. Pydantic 모델 자체가 frozen인 것은 아닙니다. |
| `RedactedInput` | 합성 비식별 발화 | `schemas.py::RedactedInput`, `architecture.md` §6 | 비식별 전 원문과 credential은 넘기지 않되 exact span 검증에 필요한 전체 `redacted_text`와 redaction metadata는 LLM에 전달합니다. | 추출 span이 redacted text에 실제 존재하고 redaction offset이 유효합니다. |
| `KnownProcedureStep[]` | fixture가 `ProcedureMaster`에서 파생 | `schemas.py::KnownProcedureStep`, `fixtures.py` | 자연어 절차 언급을 자유문장이 아닌 master ID/code에 결합합니다. | 현재 fixture의 ID/code는 master와 일치합니다. 다만 runtime constructor가 두 입력을 교차검증하지는 않으므로 외부 주입 전에 별도 검증이 필요합니다. |
| `ProcedureMaster` | read-only 합성 master 주입 | `procedure_tool/models.py`, `fixtures.py` | LLM이 절차 순서와 조건을 임의 생성하지 못하게 합니다. | data version, Evidence, 선행조건 DAG, 조건 operator 검증을 통과합니다. |
| `ReviewedSupportCatalog` | read-only 합성 catalog 주입 | `support_agent/models.py`, `fixtures.py` | 존재하지 않는 지원사업이나 조건을 모델이 만들지 못하게 합니다. | 모든 사업·조건·표시문구가 검수 또는 공식 Evidence에 연결됩니다. |
| 구조화 출력 LLM client | 환경변수로 생성 | `llm.py::StructuredLLMClient.from_env` | 자유 형식 응답을 공개 계약으로 직접 신뢰하지 않기 위해 필요합니다. | provider JSON Schema와 로컬 의미 검증을 모두 통과합니다. |
| runtime clock와 UUID factory | 기본 UTC clock/UUID4 또는 테스트 주입 | `graph.py::AgentGraph` | 모델이 ID·시각·digest를 생성하면 provenance를 신뢰할 수 없습니다. | aware datetime과 runtime 생성 UUID만 공개 결과에 사용됩니다. |
| trace sink | 기본 `NullTraceSink` 또는 안전한 구현 주입 | `tracing.py`, `graph.py` | 실행 상태는 관찰하되 prompt 원문·인증 token·민감정보를 유출하지 않아야 합니다. | 계약에는 model/token count 필드가 예약됐지만 현재 Graph는 상태·지연·시도와 code/예외 class name만 채웁니다. 오류 message·원문·credential은 기록하지 않으며 usage 수집과 `error_code` allowlist는 미구현입니다. |

### 입력 신뢰 경계

`CaseSnapshot`, procedure master, support catalog는 LLM 출력이 아니라 신뢰된 caller/resolver 입력이어야 합니다. 이 값이 신뢰되지 않으면 이후 Review가 있어도 잘못된 기준 데이터 위에서 일관된 답을 만들 뿐이므로 안전성을 보장할 수 없습니다.

현재 `fixtures.py`는 실행 구조 검증을 위한 공급자이며 실제 사업·법률·Case 데이터가 아님을 파일 상단과 Evidence 문구로 명시합니다.

## 4. 구성요소별 입출력 계약

| 구성요소 | 공개 입력 | provider 최소 출력 | 로컬 의미 모델 | 공개 출력 | 근거와 이유 |
|---|---|---|---|---|---|
| 정보분석 Agent | `InfoAnalysisInput` | `InfoProviderOutput` | `InfoAnalysisDraft` | `InfoAnalysisResult` | 사용자 발화에서 선택한 형식과 runtime이 검증할 의미·Evidence 생성을 분리해야 합니다. 상세 계약은 schema 문서 §8입니다. |
| 지원금 Agent | `SupportAnalysisInput` | `SupportProviderOutput` | `SupportAnalysisDraft` | `SupportAnalysisResult` | catalog-owned 사업 ID, 신청 문구, 신청 기간과 Evidence를 runtime이 복사해 모델의 임의 생성을 막습니다. provider가 만드는 `reason_summary`는 별도 로컬 안전검사를 거칩니다. 상세 계약은 §9입니다. |
| 절차조회 Tool | `ProcedureLookupInput` | 해당 없음 | 결정론적 코드 평가 | `ProcedureLookupResult` | 정형 master의 조건과 선행관계는 LLM 추론보다 코드로 재현 가능하게 계산해야 합니다. 상세 계약은 §10입니다. |
| Supervisor | `SupervisorRunInput`과 검증된 하위 결과 | `SupervisorModelOutput` | `SupervisorSemanticDraft` | `SupervisorDraft` | 의미 선택은 모델이 하되 ID·시각·mutation·provenance는 runtime이 조립해야 합니다. 상세 계약은 §11입니다. |
| Review Tool | `ReviewSubject` | `ReviewProviderOutput` | `ReviewModelOutput` | `ReviewResult`; PASS 검증 후 Graph/runtime가 `ReviewProof` 발급 | 모델 권고를 그대로 실행 명령으로 쓰지 않고 결정론적 검사를 다시 적용하며, proof의 ID·시각·digest는 LLM이 아니라 runtime이 만들어야 합니다. 상세 계약은 §12입니다. |
| Agent Graph | `SupervisorRunInput` | 해당 없음 | `AgentGraphState` | `AgentRunOutcome` | 외부에는 검토된 결과, 확인이 필요한 충돌, 안전 실패만 노출해야 합니다. 상세 계약은 §13입니다. |

provider schema와 로컬 의미 schema를 분리하는 근거는 실제 structured-output 호출에서 형식상 유효하지만 의미상 잘못된 응답이 관찰됐기 때문입니다. provider 호환을 위해 축소한 JSON Schema는 전송 형식만 제한하고, canonical field, Evidence, freshness, provenance, 과도한 확정 표현은 로컬 코드가 최종 검증합니다.

## 5. 현재 standalone 실행 흐름

```text
SupervisorRunInput
  → 정보분석 Agent
      ├─ 확인 필요 충돌 있음 → CONFLICT
      └─ 정상
          → 절차조회 Tool
          → 지원금 Agent
          → Supervisor 초안
          → Review Tool
              ├─ PASS → ReviewProof → REVIEWED_PLAN
              ├─ REVISE → dependency상 가장 앞선 구성요소부터 재실행
              └─ 실패/상한 소진 → SAFE_FAILURE
```

현재 standalone Graph는 `CASE_CREATED`와 `RESULT_SUBMITTED`에서 정보분석→절차조회→지원금 순서로 세 구성요소를 실행합니다. `SUPPORT_REFRESH`도 정보분석 노드는 지나지만 사용자 입력이 없어 Info Agent 호출은 생략합니다. `architecture.md`의 목표 구조인 “Supervisor가 필요한 구성요소만 선택 호출”은 AI Graph/Supervisor의 후속 구현 또는 MVP 예외 합의가 필요한 동작이며, BE Coordinator 연결로 자동 해결되지 않습니다.

| 실행 불변식 | 근거 | 이유 | 확인 방법 |
|---|---|---|---|
| 충돌 시 후속 판단 중단 | `graph.py::_route_after_info` | 확인되지 않은 새 값으로 지원·절차·저장 후보를 만들면 안 됩니다. | `CONFLICT` outcome과 후속 호출 부재를 테스트합니다. |
| 모든 정상 초안 Review 필수 | `architecture.md` §1·§11, `graph.py::_compile` | Supervisor와 같은 모델을 사용하더라도 별도 검증 관문이 필요합니다. | Review 없이 `REVIEWED_PLAN`을 만들 수 없는지 테스트합니다. |
| Review 재작성 최대 2회 | `graph.py::max_review_revisions`, schema 문서 §17 | 무한 루프와 비용 폭증을 막습니다. | 초과 시 `SAFE_FAILURE`인지 테스트합니다. |
| 재작업 대상은 runtime이 계산 | `review_tool/tool.py::_finalize_result`, `graph.py::_route_after_review` | LLM의 권고 목록을 권한 있는 실행 명령으로 신뢰하지 않습니다. | Review Tool이 blocking issue와 누락 근거로 target을 다시 계산하고 Graph가 dependency 순서로 가장 앞선 지점부터 재실행합니다. |
| snapshot 보호 | `graph.py::run`의 deep copy와 digest 검사 | Review가 확인한 기준 Case가 실행 중 바뀌지 않게 합니다. | Graph가 caller 객체를 직접 사용하지 않고 정상 반환 경로에서 owned snapshot digest 불일치를 거부합니다. |
| 기술 실패 fail-closed | `graph.py::_failure`, `_build_safe_failure` | 장애를 `NOT_RELEVANT` 또는 `CASE_COMPLETE`로 오인하면 위험합니다. | 예외별 고정 failure/message code와 미검토 결과 부재를 검사합니다. |

## 6. Evidence, Review, 저장 안전조건

| 요구사항 | 근거 | 이유 | 완료 기준 |
|---|---|---|---|
| `REVIEWED_PLAN`의 확정 사실과 고위험 주장은 Evidence 참조 | schema 문서 §5·§6, `claim_safety.py`, `ReviewSubject` | 지원 자격·기한·절차를 모델 지식만으로 단정하지 않게 합니다. | Review 대상의 모든 참조가 trigger/snapshot/source result의 닫힌 Evidence 집합에서 해석됩니다. |
| 같은 Evidence ID는 같은 내용 | `schemas.py`, `review_tool/tool.py` | ID만 재사용해 다른 내용을 근거처럼 끼워 넣는 것을 막습니다. | 동일 ID의 내용/hash 충돌을 거부합니다. |
| stale/unknown 근거로 positive 판정 금지 | `SupportCheck` validator, schema 문서 §9 | 오래된 공고로 자격이나 비대상을 확정하지 않게 합니다. | `STALE`/`UNVERIFIABLE` 이외의 판정을 거부합니다. |
| Review 대상 digest 결합 | `ReviewSubject`, `ReviewProof` | Review 후 초안이나 Evidence가 바뀌었는데 이전 PASS를 재사용하지 못하게 합니다. | 대상 변경 시 proof 검증이 실패합니다. |
| `REVIEWED_PLAN`은 저장 허가가 아님 | schema 문서 §13·§14 | 인증·현재 DB 상태·동시성은 Agent가 확인할 수 없습니다. | standalone에는 persistence capability가 없고 결과만 반환합니다. |
| 실제 충돌 참조 생성 금지 | schema 문서 §18 | standalone digest prefix는 운영 서버가 복원·만료시킬 수 없습니다. | `standalone:` ref를 저장 또는 `/results/confirm`에 전달하지 않습니다. |

현재 `CONFLICT` outcome은 `source_evidence_refs`를 가지지만 Info Agent가 새로 만든 `evidence_records`를 함께 반환하지 않아 outcome 하나만으로 모든 ref를 복원할 수 없습니다. 따라서 production wire schema로 사용하지 않으며 AI가 Evidence bundle/resolver 경계를 보강해야 합니다.

## 7. 실행 환경과 실행 방법

### 환경 구분

- 공통 실행 환경: Python 3.12, `backend/requirements.txt`
- mock 기반 자동 테스트: `backend/requirements-dev.txt`; LLM 환경변수 불필요
- live CLI: `CHAT_PROXY_URL`, `PROXY_TOKEN`, endpoint가 지원하는 `OPENAI_MODEL` 필수

live CLI는 repository root `.env`를 읽고 같은 이름의 process environment가 있으면 이를 우선합니다. 선택 환경변수는 `OPENAI_REASONING_EFFORT`, `AGENT_LLM_TIMEOUT_SECONDS`, `AGENT_LLM_MAX_RETRIES`, `AGENT_LLM_RETRY_BACKOFF_SECONDS`입니다. 외부 endpoint는 loopback 개발 서버가 아니면 HTTPS여야 하며 URL에 credential, query, fragment를 넣지 않습니다.

`AGENT_LLM_MAX_RETRIES`는 HTTP/provider 재시도만 제어합니다. 의미 검증 상한은 코드에서 별도로 제한하며 현재 기본값은 정보분석 2회, 지원금 3회, Supervisor 3회, Review 출력 2회, Graph Review 재작성 2회입니다. 따라서 운영 deadline은 provider retry 하나만 보고 계산하면 안 됩니다.

`DATA_GO_KR_SERVICE_KEY`, `BIZINFO_API_KEY`, `DATABASE_URL`, JWT/Kakao, embedding, Langfuse 관련 환경변수는 현재 standalone CLI 실행에 사용되지 않습니다. 이름이 `.env`에 있다는 사실만으로 실제 데이터 연동이 완료된 것이 아닙니다.

### 재현 명령

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install \
  -r backend/requirements.txt \
  -r backend/requirements-dev.txt
backend/.venv/bin/pip install ruff==0.16.5

PYTHONPATH=backend backend/.venv/bin/python \
  -m pytest -q -W error backend/tests/agent

backend/.venv/bin/ruff check backend/app/agent backend/tests/agent
backend/.venv/bin/ruff format --check backend/app/agent backend/tests/agent

PYTHONPATH=backend backend/.venv/bin/python \
  -m app.agent.cli --live --compact --trace-id local-smoke
```

CLI는 `--live`가 없으면 실행을 거부합니다. 외부 LLM을 호출할 수 있음을 명시적으로 인지하게 하고, 실수로 과금 가능한 호출을 시작하지 않게 하기 위한 조건입니다.

| 종료 | 의미 | 정상 취급 이유 |
|---|---|---|
| exit code `0`, `REVIEWED_PLAN` | Review를 통과한 standalone 결과 | 검토된 제안까지 완성됐습니다. 저장 완료를 뜻하지 않습니다. |
| exit code `0`, `CONFLICT` | 사용자 확인이 필요한 충돌 | 위험한 자동 덮어쓰기 대신 확인 경로로 닫혔습니다. |
| exit code `2`, `SAFE_FAILURE` 또는 안전한 오류 메시지 | provider·설정·검증 실패 | 미검토 도메인 결과를 반환하지 않았으므로 fail-closed가 동작했습니다. |

## 8. 데이터 모드별 현재 상태

| 데이터 모드 | Case | 절차 | 지원사업 | LLM | 현재 상태 |
|---|---|---|---|---|---|
| 합성 standalone | 합성 fixture | 합성 master | 합성 reviewed catalog | 실제 provider 가능 | 구현·검증 완료 |
| 실데이터 주입형 | 외부 caller가 만든 snapshot | 외부 master | 외부 reviewed catalog | 실제 provider 가능 | 타입 주입점은 있으나 resolver/CLI 미구현 |
| BE 생산 연동 | 인증된 BE snapshot | versioned master | canonical DB/Wiki/공식 원문 | 실제 provider | 미구현 |

실제 기업마당 payload 점검은 Agent runtime 실행과 분리된 수동 read-only 관찰입니다. 변동 가능한 조회 건수와 source mapping은 BE 문서 §8에서만 관리합니다. 현재 Support Agent가 그 응답을 직접 사용하지 않으며, 외부 공고의 누락 필드를 임의 생성해 Graph를 통과시키지 않습니다.

## 9. 검증 근거

2026-09-15 현재 커밋 기준 검증 결과입니다. 자동 검증과 수동 smoke 기록을 구분합니다.

- 자동 테스트는 scripted/mock LLM을 사용하며 외부 Case·지원사업·LLM API를 호출하지 않습니다.
- 자동 검증: Agent 테스트 `155 passed` (`-W error`)
- 자동 검증: Ruff `0.16.5` check 통과, format check에서 36개 Python 파일 형식 일치
- 수동 compile 점검: 주요 public/provider/local schema 19종 JSON Schema 생성 통과. 현재 checked-in 테스트는 최상위 모델 8종과 `AgentRunOutcome` union을 지속 검증합니다.
- 수동 live smoke: 커밋 `cbcb71b`, 모델 `openai/gpt-4.1-mini`, 합성 Case와 실제 LLM provider를 사용한 전체 Graph 호출 성공
- 수동 live 결과: `REVIEWED_PLAN`, Review `PASS`, `review_attempt=1`, decision `ACTION`
- 수동 live 결과: Blocker 1개, Next Action 1개, source result 3개, BE/DB persistence 0건

한 번의 live 호출이 언제나 `PASS`한다는 보장은 없습니다. 외부 모델 응답이 제한된 재시도 안에 의미 검증을 통과하지 못하면 `SAFE_FAILURE`로 끝나는 것이 정상 안전 동작입니다.

## 10. standalone 완료 기준

아래 조건이 모두 충족되어야 “Agent 자체 동작 가능”으로 보고합니다.

- [x] 모든 공개 입력·출력이 strict Pydantic 검증을 사용한다.
- [x] provider용 출력과 로컬 의미 검증을 분리한다.
- [x] 정보분석, 절차조회, 지원금, Supervisor, Review가 한 Graph에서 실행된다.
- [x] 정상 초안은 Review를 우회할 수 없다.
- [x] Review 대상과 PASS proof가 digest로 결합된다.
- [x] 충돌은 자동 덮어쓰지 않고 `CONFLICT`로 반환한다.
- [x] 실패나 retry 소진은 미검토 결과 대신 `SAFE_FAILURE`로 반환한다.
- [x] 합성 fixture만으로 실제 LLM 호출을 재현할 수 있다.
- [x] Agent 테스트·lint·format이 통과한다.
- [x] standalone 경로에 BE/DB write capability가 없다.

다음 항목은 AI에 남은 후속 작업입니다.

- [ ] `KnownProcedureStep[]`와 `ProcedureMaster` constructor 교차검증
- [ ] self-contained `CONFLICT` Evidence bundle 또는 production resolver 계약
- [ ] BE shared snapshot DTO → runtime `CaseSnapshot` adapter와 목표 필드 확장
- [ ] versioned procedure master runtime adapter
- [ ] 지원사업 ingestion/catalog builder와 approved catalog runtime adapter
- [ ] Supervisor 동적 구성요소 선택 또는 MVP 고정 흐름 예외 승인
- [ ] `NO_CHANGE` runtime outcome
- [ ] 생산용 `CONFLICT_CONFIRMED` trigger/adapter
- [ ] 실제 Langfuse `TraceSink` adapter

다음 항목은 BE/shared 생산 연동 선행 조건입니다.

- [ ] 인증된 Case snapshot assembler와 read service
- [ ] canonical procedure repository/read service
- [ ] 지원사업 canonical registry, 승인 metadata, Evidence 저장·read service
- [ ] 인증·소유권·idempotency·CAS
- [ ] Output/State Transition Guardrail
- [ ] transaction ADR로 합의한 atomic persistence
- [ ] 운영 conflict confirmation ref/TTL/CAS round trip
- [ ] cross-language Review digest test vector

이 미완료 항목의 요청 내용과 승인 기준은 `be-agent-integration-requirements.md`에서 관리합니다.

## 11. AI가 유지해야 하는 문서 산출물

| 문서 | 소유 | 갱신 시점 | 이유 |
|---|---|---|---|
| `docs/architecture.md` | AI, 경계는 BE 공동 검토 | 구성요소 책임이나 호출 방향 변경 시 | 책임 중복과 Review 우회를 막습니다. |
| `docs/agent-tool-io-schema.md` | AI 제안, shared 경계는 BE 공동 승인 | schema version 변경 시 | Agent/Tool 필드 계약의 단일 출처입니다. |
| 이 문서 | AI | 실행 방식, 환경, 완료 기준 변경 시 | standalone과 생산 연동을 구분합니다. |
| provider/local schema 변경 기록과 테스트 | AI | 모델 projection 또는 guardrail 변경 시 | 외부 provider 제약과 내부 안전 규칙의 차이를 추적합니다. |
| 실제 데이터 호환성 결과 | AI/BE 공동 | source API나 shared DTO 변경 시 | 문서상 예시가 실제 payload와 다른 문제를 조기에 발견합니다. |

비밀값, 실제 사용자 원문, 운영 endpoint, access token은 어떤 문서와 테스트 fixture에도 넣지 않습니다.
