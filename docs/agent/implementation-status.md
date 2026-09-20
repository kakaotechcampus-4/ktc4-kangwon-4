# AI 티켓 구현 현황과 BE 연결 순서

> 소유: AI · 확인일: 2026-09-20
> 원본: 사용자가 전달한 2026-09-15 「RE:BORN 기능 구현 티켓 초안」
> 확인 범위: 현재 작업 브랜치, `git fetch origin` 후 원격 BE 브랜치, 실제 공식기관·LLM API와 갱신된 `.env`의 MySQL 읽기 전용 조회.

원본의 “AI 코드 없음”은 작성 당시 상태다. 현재는 standalone Agent가 구현돼 있다.
아래 번호는 원본 티켓 번호이며, **AI 내부 구현 완료와 실제 서비스 연동 완료를 구분한다.**
물리 테이블·컬럼·enum 기준은 [`schema_table.md`](../schema/schema_table.md)다.
과거 요청 문서의 새 컬럼·새 테이블 제안은 이번 작업의 구현 근거로 사용하지 않는다.

## 0. 서비스 전체가 완료됐는가

**아니다. 현재는 standalone Agent 코어이며 실제 Case API → Agent → DB 저장 → 재조회는 미연결이다.**
아래의 코드·테스트 존재는 실제 사용자 판단 품질이나 운영 저장 성공을 보장하지 않는다.

| 구성요소 | 확인된 현재 동작 | 미완료·검증 한계 |
|---|---|---|
| Supervisor | 수집된 결과로 Blocker·Next Action 초안, 재작업 | 첫 호출 순서는 Graph 고정. 자율 호출 계획과 Case 전체 완료 판정은 미완료 |
| 정보분석 | 허용 필드·근거 구간 확인, 불확실성·충돌 후보, 제한된 재시도 | 실제 BE snapshot 입력 연결·통합 검증 필요 |
| 절차조회 Tool | 메모리에 올린 파일 스냅샷 조회, 출처·검수 상태 보존 | 실제 원문 3건 모두 미검수. DB의 적용 조건·선후 관계·불가 사유 연결 필요 |
| 지원금 Agent | 주입한 catalog 조건 비교, 선택적 Wiki ID·UUID exact lookup 연결, 근거 없는 자격 확정 차단. 별도 명령에서 미검수 공고 Chroma 검색 확인 | 공고 7건 모두 미검수·조건 미작성. 실제 검수 Wiki·DB 식별자 매핑이 없어 HIT 실행 미검증. 운영 RAG·S3 조회 미연결 |
| Review Tool | 독립 검수, PASS 증명·digest 확인, 재작업 | 저장 허가·운영 안전성 검증을 대신하지 않음 |
| 가드레일 | schema·근거 참조·상태·충돌 후보·예산·일부 민감정보 검사. 실제 공식 문장에서 재현한 금액 뒤 조사 탐지 누락 수정 | 개인정보 패턴·더 넓은 표현 검증은 남음(OD-08). BE의 소유권·저장 직전 보호 미연결 |
| 테이블 저장 | 실제 MySQL 접속 성공, 11개 테이블 확인 | 기준 대비 6개 테이블·8개 컬럼 누락. Case·절차·지원사업·Case 이력 0건. 저장 함수 호출·transaction·rollback·재조회 통합 검증 없음 |

CLI의 **합성 Case와 demo catalog 자동 대체를 제거했다.** 이제 실제 요청 JSON과 절차 registry
JSON을 필수로 받고, 미검수 지원사업은 서비스 후보 0건으로 유지한다. CLI 자체에는 DB 저장 기능이 없다.
실제 API 호출·DB 조회 결과와 검증하지 못한 경로는 [`live-verification.md`](./live-verification.md)에 기록한다.
과거 609개 테스트 통과에는 알려진 한계의 현재 동작을 기록한 테스트도 포함된다.
사용자의 더미 테스트 금지 지시 이후에는 해당 테스트를 다시 실행하지 않았다.

## 1. 번호별 판정

| 번호 | 상태 | 현재 구현 근거 | 남은 완료 조건 |
|---|---|---|---|
| **C1** `[BE][AI][FE]` | **부분 완료 · 공동 협의** | AI의 Case 필드·확정 enum을 현행 테이블 정의에 맞춤. `UNKNOWN`은 AI 내부에서 `status=UNKNOWN, value=null` | DB의 `UNKNOWN`과 AI 표현 사이 변환, 삭제·NULL 처리, FE 전달 형태를 BE·FE와 확정. 공유 스키마는 수정하지 않음 |
| **C4** `[AI]` | **부분 완료** | `schemas.py`, `tool-io-schema.md`: Supervisor·Info·Procedure·Support·Review, Evidence, 검수 대상 digest 및 결과 모델 | B4 기반 절차 필요조건·불가 사유의 전달 계약과 BE 저장 DTO mapping. 삭제된 `interface-spec.md` 대신 현재 AI 계약 문서를 사용 |
| **C5** `[BE][AI]` | **공동 협의 필요** | 내부 `SAFE_FAILURE`와 저장 없는 Agent 실행, 연동 요청서의 실행 순서 제안 | 변경/판단/이력 저장의 원자성, 실패 시 DB 상태, 외부 `REPLAN_FAILED` body·HTTP 정책 |
| **C6** `[BE][AI]` | **공동 협의 필요** | `CONFLICT_CONFIRMED` 재계획, 기존 값 재확인, stale 확인 거부는 구현 | 운영용 conflict 참조 발급·저장·만료·1회 소비와 confirm API. standalone 참조를 운영 참조로 사용하지 않음 |
| **A1** `[AI]` | **구현 완료 · 실제 LLM 연결 확인** | `llm.py`, `tracing.py`: 프록시·모델 설정, 구조화 응답, metadata-only Langfuse 연결. 공용·Supervisor 설정으로 실제 공식 문서를 보내 HTTP 200 및 응답 schema 검증 | 전체 Agent 실행·지속 가용성 확인과 다름. Langfuse 실제 확인 범위는 실동작 기록 참조 |
| **A2** `[AI]` | **구현 완료** | `graph.py`, `state.py`, `runtime.py`: LangGraph 실행·종료·재작업·실행별 예산 | 티켓의 골격 범위는 충족. 첫 호출은 trigger별 고정 순서이며 자율 호출 계획은 별도 목표 |
| **A3** `[AI]` | **AI 내부 구현 완료** | `info_agent/agent.py`: exact source span, 필드 허용 목록, 불명확한 사실 확인, 제한된 재시도. 이번 작업에서 DB와 다른 필드·값 제거 | 실제 BE snapshot 입력은 C1/B7 연결 이후 검증 |
| **A4** `[AI]` | **부분 완료** | 검수 상태를 보존하는 절차 스냅샷 조회, 공식 원문 수집 명령. 이번 작업에서 `build_runtime(procedure_store=...)` 주입 지원 | B4의 실제 절차 ID·시드/규칙·출처와 연결. 파일 문서 조회만으로 DB 절차 의존성 조회가 완료된 것은 아님 |
| **A5** `[AI]` | **구현 완료** | 독립 Review 프롬프트·검수 컨텍스트, PASS 증명·digest 검증, REVISE 대상 재실행. 모든 정상 초안의 검수 강제 | 현재 의미는 최초 검수 + 최대 2회 재작업. 전체 폐업 완료 판단은 별도 coverage가 없어 차단 |
| **A6** `[AI]` | **부분 완료** | 검수 재작업·호출 예산·deadline 소진 시 검수 전 초안을 버리는 `SAFE_FAILURE`. 실패 시점의 source 결과에서 막혀 있던 Case 필드를 파생해 `requested_field_paths`에 싣고, 재시도가 답이 아닌 실패에서는 `recovery_action_code=RESUBMIT_INPUT`을 낸다. 소진 분기도 마지막 Review 지적과 재작업 대상을 버리지 않는다 | C5의 외부 실패 응답·Output Guardrail과 FE 확인 요청 연결. 파생 결과의 실제 Case 검증은 미수행. 재작업 횟수 표현은 “최초 Review + 수정 후 최대 2회”로 통일함 |
| **A7** `[AI]` | **부분 완료 · 검수·DB 매핑 필요** | 읽기 전용 Markdown Wiki adapter, 지원사업 ID·UUID exact lookup, SupportAgent/runtime/CLI 선택 연결. 프로젝트 Obsidian Vault와 실제 공식 공고 7건의 미검수 노트 추가 | 실제 사람 검수와 BE 식별자 매핑으로 HIT→비교→Review 확인. 운영 노트 형식·검수 기준 협의. Wiki miss는 PARTIAL로 보존하며 운영 RAG fallback은 미연결 |
| **A8** `[AI]` | **부분 완료 · 오프라인 검색 확인** | 실제 임베딩 API로 미검수 공고 7건·35구간 색인, Chroma 저장·재검색·공고 필터·원자료 span/hash 대조 | 검수 corpus와 BE 매핑, S3 원문·version·최신성 확인, Wiki miss의 운영 RAG 연결. 현재 Graph는 `rag_used=false` |
| **A9** `[AI]` | **부분 완료** | Info/Support의 반복 상한, 실행 시간·호출 예산, 토큰·지연·상태 trace와 동시 실행 격리. Review verdict와 실행별 판정·반송·실제 시작한 재작업 횟수 기록 추가 | 새 Review 집계의 실제 Case 검증, 반송률·비용 집계, Langfuse 대시보드 |

**AI 코드 기준으로 완료한 번호는 A1·A2·A3·A5다.** 공동 계약과 실제 사용자 Case 연결까지
끝났다는 뜻은 아니다. C4·A4·A6·A7·A8·A9는 남은 하위 작업과 실제 서비스 연결이 있다.

## 2. 이번에 진행한 AI 범위

- `lease_status`: 임대 형태인 `LEASED_PAID / LEASED_FREE / OWNED`만 확정값으로 사용한다.
  이전 `ACTIVE / TERMINATION_NOTIFIED / TERMINATED`는 임대차 해지 진행 상태이므로 새 값으로 자동 변환하지 않는다.
- `restoration_scope`: 복구 범위인 `PARTIAL / FULL / NOT_REQUIRED`를 사용한다.
  이전의 비용 부담자(`TENANT_ALL`, `LANDLORD_ALL`, `SHARED`)를 복구 범위로 바꾸지 않는다.
- `restoration_status`의 확정값에 스키마에 있는 `NOT_REQUIRED`를 포함한다.
- 테이블에 없는 `entity_type / building_use_type / previous_support_history`를 Case 필드 허용 목록에서 제거한다.
  이 정보가 필요한 지원사업은 근거 없는 자격 판단을 하지 않고 공식기관 확인 대상으로 남겨야 한다.
- 더미 테스트 금지 지시 이전에 기존 합성 입력과 추출 테스트도 위 의미에 맞췄다. 단순히 “임차 중”이라는 말로 유상/무상을 추정하거나
  “임차인 부담”이라는 말로 전체/부분 복구를 추정하는 출력을 허용하지 않는다.
  새 enum 표현에 부정·질문·미확인이 붙은 문장도 확정값 근거로 쓰지 않는다.
- 런타임이 기존 `ReviewedProcedureStore`를 주입받도록 한다. BE 데이터가 준비되면 합의된 BE 함수로
  미리 읽은 자료를 연결할 수 있다. Agent에 SQL·ORM 접근이나 새 테이블 정의를 넣지 않는다.
- [`official-closure-procedure.md`](./official-closure-procedure.md)에 공식 폐업 절차·출처·조건을 정리한다.
  이 참고 문서 작성은 운영 지식의 사람 검수나 B4 시드 발행을 대신하지 않는다.
- CLI에서 실제 `AgentGraphInput`·`KnownProcedureStep[]` 파일을 받도록 바꾸고 더미 대체를 제거했다.
  실제 입력을 임의로 만들지 않았으며, 파일 출력은 기존 파일을 덮어쓰지 않는 권한 `0600` 파일로 제한한다.
- 후속 작업으로 실제 중소벤처기업부 원문의 금액 표현 누락을 수정했다. 받은 원문을 그대로 사용해
  수정 전 미탐지 2건이 수정 후 `AMOUNT`·공식 근거 필수로 분류되는 것을 확인했다.
- A9의 Review 판정·반송·재작업 metadata를 추가했다. 코드 정적 확인만 했으며,
  실제 Case 없이 가짜 Review 이벤트를 만들어 Langfuse에 보내지 않았다.
- 로컬 `develop`을 `1a11cf1`에서 `e360ab3`로 fast-forward했다. 현재 기능 브랜치는 이미
  최신 `develop`을 포함하고 있어 추가 병합 변경 없이 기존 작업을 보존했다.
- A7의 읽기 전용 Wiki 경로를 기존 Agent 내부 모델로 연결했다. 기본 설정에서는 기존 catalog를
  유지하며, Wiki를 선택한 요청의 자료 누락을 이전 catalog 규칙으로 감추지 않는다.
  [`support-wiki.md`](./support-wiki.md)에 실제 자료 요건과 미검증 범위를 정리했다.
- 사용자가 기존 Wiki가 없다고 알려주어 [`obsidian/`](./obsidian/README.md) Vault를 새로 만들었다.
  실제 공식 API 공고는 외부 공고 ID로 미검수 상태에 보존하고, DB ID·UUID·검수자·조건은 만들지 않는다.
  공식 폐업 절차 진입점과 검수 절차도 함께 제공한다.
- A8의 오프라인 Chroma 인덱스를 추가하고 실제 공고 자료와 임베딩 API로 저장·검색했다.
  미검수 namespace에서 원래 필드의 구간과 근거를 보존하며 운영 Support Agent에는 주입하지 않는다.
  요청·응답 임베딩 모델명의 실제 표기 차이를 수정했다. [검색 구현 범위](./support-retrieval.md)를 참고한다.

enum 수정의 협의 근거는 BE `origin/feature/case-service`의 `docs/case-service.md`와
`backend/app/be/services/case_service.py`다. BE는 `schema_table.md`를 기준으로 AI의
`CASE_FIELD_SPECS`가 정리되면 변환 함수를 구현한다고 명시했다. 이번 수정은 그 AI 담당 부분이다.

## 3. BE가 만든 것과 아직 연결되지 않은 것

| 확인 위치 | 이미 있는 것 | 아직 없는 것/확인하지 못한 것 |
|---|---|---|
| 현재 작업 브랜치 및 `origin/refactor/db-schema` (`dee26f7`) | 기본 SQLModel 11개와 스키마 문서 | 문서에 정의된 17개 중 6개 모델, 일부 registry·catalog·version 컬럼 |
| 갱신된 `.env`의 실제 MySQL (2026-09-20 20:52 KST) | 연결 성공, 스키마에 해당하는 테이블 11개 | 6개 테이블·8개 컬럼 누락 및 enum 차이. Case·절차·지원사업·Case 이력 0건 |
| `origin/feature/case-service` (`e082b84`) | 소유권 조건 조회, `InternalCaseSnapshot`, 필드 변경 함수 | `to_agent_case_snapshot()`은 `NotImplementedError`. 현재 작업 브랜치에는 미병합 |
| `origin/feature/validator` (`4b34da2`) | DB 연결, JWT 인증, 인증 route, `sqlmodel` 의존성 pin | Agent 실행 route 및 전체 저장 루프는 미연결 |

코드와 현재 연결한 실제 DB에서 없는 6개는 `CASE_FIELD_HISTORY`, `SUPPORT_MATCH`, `EVIDENCE`,
`EVIDENCE_LINEAGE`, `CONFLICT_REFERENCE`, `DECISION_RECORD`다. 기존 DB를 초기화하지 않고,
현행 스키마에 이미 정의된 누락분의 migration 위치와 적용 상태를 BE와 확인한다.

CaseService가 존재해도 snapshot adapter에는 근거 참조, 절차 `step_code`, 진행상태 갱신시각,
timezone이 있는 시각이 더 필요하다. DB에 없는 출처·확인시각을 AI가 만들어 채우지 않는다.
현재 필드 변경 함수는 자체 `commit()`을 호출하므로 최종 판단·이력까지 원자 저장할 책임은 C5에서 정한다.

## 4. Agent 구현·연동까지 남은 순서

1. **C1 마무리 — BE·AI·FE:** 이번 AI 필드 정리를 바탕으로 DB `UNKNOWN` ↔ AI 미확인,
   허용 변경, nullable·삭제와 FE 응답을 확정한다. DB 컬럼·enum을 바꾸는 안은 이번 범위에 없다.
2. **B7/C4 연결 — BE·AI:** 소유권 확인을 마친 Case를 근거 포함 `CaseSnapshot`으로 변환한다.
   부족한 근거를 임의의 `SYSTEM_RECORD`로 확정 사실처럼 꾸미지 않는다.
3. **B4/A4 지식 연결 — BE·AI:** 공식 절차 문서를 팀이 검수하고 실제 절차 ID와 적용 조건·선후 관계에 연결한다.
   현재 절차 원문 3건은 모두 미검수다. 지원공고 7건도 미검수·조건 미작성이라 실제 서비스 항목은 0건이다.
4. **C5/B11/A6 — BE·AI:** DB transaction 밖에서 Agent를 실행하고, 결과 검증 후 Case·판단·근거·이력을
   합의된 단위로 저장한다. 실패 시 저장 상태와 외부 응답을 결정한다.
5. **C6/B12 — BE·AI, 응답 검토 FE:** 서버의 충돌 참조를 검증·소비하고 확인된 입력으로 재계획한다.
   사용자 선택 전 저장하지 않고, 확인 직전 필드 값이 달라지면 덮어쓰지 않는다.
6. **A7 → A8 — AI 구현, 데이터 경계 BE 협의:** Wiki UUID exact lookup에 실제 검수 자료를 연결하고,
   미검수 오프라인 검색과 분리된 검수 corpus·S3 fallback을 잇는다.
   `SUPPORT_ITEM.uuid`와 `source_file_location`을 사용하며 새 Case 자격 컬럼을 만들지 않는다.
   검수 Wiki 형식·공식 출처 확인 정책은 [`open-decisions.md`](./open-decisions.md)의 OD-01에 기록한다.
7. **A9 및 통합 검증 — AI·BE·FE:** 호출·비용·검수 반송 관측을 채우고, Case 생성 → 결과 입력 →
   Review → 저장 → 재조회, 충돌 선택 후 재계획, 안전 실패 경로를 실제 API/격리 DB에서 검증한다.

`CASE_COMPLETE`는 현재 타입만 있고 전체 적용 절차가 끝났다는 근거가 없어 Supervisor와 Review가
거부한다. 일부 절차 조회·완료만으로 Case 전체 완료를 선언하지 않는다.

## 5. 공동 협의에서 확인할 구체적인 항목

결정 대장은 [`open-decisions.md`](./open-decisions.md)이며, 아래는 C1/C5/C6의 검토 순서다.
담당자 회신 전까지 외부 DTO·HTTP status·저장 방식을 확정한 것으로 보지 않는다.

| 티켓 | 검토할 제안 | 상대 파트 확인 필요 |
|---|---|---|
| C1 | 현재 DB 값을 그대로 읽고 `UNKNOWN`만 AI 내부 미확인으로 표현. 지원하지 않는 필드·값은 거부 | BE의 읽기/쓰기 변환과 `CLEAR` 처리, FE 표시·확인 payload |
| C5 | 소유권 확인·snapshot 읽기 → transaction 밖 Agent 실행 → Review/현재 값 검증 → 허용 변경·판단·근거·이력 저장 → 재조회 | 내부 commit 소유자, 실패 시 rollback 범위, `SAFE_FAILURE` → 외부 실패 응답 |
| C6 | `CONFLICT_REFERENCE`의 opaque 참조와 만료·사용 여부로 확인. FE가 보낸 임의의 후보값을 저장하지 않음 | 실제 필드 재확인·1회 사용 보장, 만료·재전송 응답, FE가 유지할 참조 |

과거 MVP `case_version` 제외 메모보다 현행 스키마의 버전·NOT NULL 정의를 우선한다.
실제 버전을 BE에서 공급·증가·확인하는 저장 계약이 필요하며 AI가 null이나 임의 버전을 저장하지 않는다.
세부는 OD-11, 검토할 건의안은 [`be-requests.md`](./be-requests.md) §7을 본다.

## 6. 검증 범위

더미 테스트 금지 지시 이전 기록: `backend/.venv/bin/python -m pytest backend/tests/agent -q`
수정 전 **542 passed**, 당시 수정 후 **609 passed**. CLI의 실제 입력 변경 이전 결과이므로
최신 CLI 실행 성공이나 실제 저장 성공의 근거로 사용하지 않는다.

금지 지시 이후에는 pytest·mock·합성 Case를 실행하지 않았다. 실제 공식기관 API, 실제 원문을
사용한 LLM API 호출, 실제 MySQL metadata·건수 조회를 수행했다. Case 실행 CLI 변경은 Ruff·소스 compile·
`--help`로 확인했으며 실제 Case가 없어 Graph 전체 실행·DB 쓰기·재조회는 미검증이다.
별도 RAG CLI는 실제 공식 공고·임베딩 API로 Chroma 색인·검색을 실행했다. 이는 서비스 DB 저장과 다르다.
세부 결과는 [`live-verification.md`](./live-verification.md)에 있다.
AI 변경 대상은 `backend/app/agent/`, `backend/tests/agent/`, `docs/agent/`이며,
사용자가 갱신한 `.env`·`.env.example`은 수정하지 않았다.
