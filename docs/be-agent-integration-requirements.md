# RE:BORN BE → Agent 연동 요구사항

> 상태: **v2.0 제안 — `agent-io/2.0`·인터넷 절차조회 반영 / BE 계약 합의 및 구현 전**
>
> 수신: BE
>
> 작성·제안: AI, shared 경계 최종 승인: AI/BE 공동
>
> 이 문서는 BE가 Agent 생산 연동을 위해 제공해야 할 문서·DTO·함수·API·저장 경계를 정의합니다. Agent 내부 계약은 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md), BE 없는 실행 조건은 [`agent-standalone-runtime-requirements.md`](./agent-standalone-runtime-requirements.md)를 따릅니다.

## 1. 먼저 합의할 결론

Agent 내부 입출력 schema와 standalone 실행만으로 실제 Case 연동은 완료되지 않습니다. 생산 동작에는 BE가 인증된 Case snapshot, canonical procedure step registry와 support catalog를 제공하고, Review 이후 결과를 현재 DB 상태에 대해 재검증한 뒤 원자적으로 저장해야 합니다. 폐업 절차 **내용**은 BE master가 아니라 AI 소유 ProcedureLookupTool이 실제 인터넷에서 조회합니다.

BE가 이 문서를 “테이블을 그대로 추가하라는 확정 명세”로 해석해서는 안 됩니다. 먼저 §4의 P0 결정을 AI와 합의하고, 합의한 shared DTO를 코드와 OpenAPI로 고정한 뒤 구현해야 합니다.

완료 상태는 다음을 모두 만족할 때입니다.

1. BE가 소유권 검증을 거친 immutable `SharedCaseSnapshotDTO`를 만들고 AI adapter가 이를 `CaseSnapshot`으로 검증할 수 있습니다.
2. Agent가 사용하는 Case field, canonical procedure progress ID, support program, Evidence ID가 BE의 canonical row와 안정적으로 매핑됩니다.
3. ProcedureLookupTool이 Kakao 웹검색으로 발견한 URL을 HTTPS·공식기관 allowlist로 검증한 뒤 실제 원문을 fetch하고, Info Agent가 그 raw 결과를 canonical step에만 결합합니다.
4. 정상 결과는 Review, Output Guardrail, State Transition Guardrail을 모두 통과해야 저장됩니다.
5. snapshot 이후 DB가 바뀌면 version 또는 field-level CAS가 저장을 거부합니다.
6. 실제 개발 Case로 read → plan → review → guardrail → persist → read-back 통합 테스트가 통과합니다.

근거는 `docs/architecture.md` §3·§10·§11, `backend/CLAUDE.md`의 Agent↔DB 경계, `agent-tool-io-schema.md` §14·§18~§21입니다.

### 기존 문서 사용 주의

| 기존 내용 | 현재 판정 | 근거와 이유 |
|---|---|---|
| `interface-spec.md` §11의 `FactCandidate`, `SupportCheckResult` JSON | **구형 검토 예시, 구현 금지** | 현재 strict 모델에는 candidate ID, operation, value type, Evidence, structured span 등이 추가됐고 장비 항목은 v1에서 보류됐습니다. |
| `interface-spec.md` §11.3의 Supervisor·절차·Review `TBD` | **Agent 내부 계약은 해소됨** | 현재 계약은 `agent-tool-io-schema.md` §10~§12와 실행 코드에 있습니다. 외부 HTTP 매핑만 BE 합의 전입니다. |
| `architecture.md`의 Supervisor 선택 호출 | **AI 소유 목표 구조** | 자연어 Case 생성·결과 제출의 v2 first-pass dependency는 절차조회→정보분석→지원금→Supervisor입니다. 하위 구성요소가 직접 호출하는 것이 아니라 Supervisor Graph가 앞 결과를 다음 입력에 전달합니다. 새 사용자 입력·절차 해석이 없는 `SUPPORT_REFRESH`는 Support부터 시작하는 현재의 명시적 예외입니다. |
| `architecture.md`의 Safe Failure schema `TBD` | **현재 Agent 내부는 해소됨** | 현재 `SafeFailureOutcome`은 구현됐지만 외부 HTTP `REPLAN_FAILED` 매핑과 저장 정책은 BE 합의 전입니다. |

BE는 위 구형 예시를 복사하지 말고 `agent-tool-io-schema.md`의 현재 계약과 이 문서의 shared 경계부터 검토해야 합니다.

## 2. 소유권 구분

| 범위 | BE 책임 | AI 책임 | 공동 합의가 필요한 이유 |
|---|---|---|---|
| 인증·소유권 | JWT 검증, member와 Case 소유권 확인, 권한 없는 Case 비노출 | 인증정보를 모델 prompt에 전달하지 않음 | Agent는 사용자 권한의 원천이 아니므로 BE 검증을 대체할 수 없습니다. |
| Case 조회 | DB row를 일관된 snapshot으로 조립 | `CaseSnapshot` adapter와 입력 검증 | DB 구조와 Agent 최적 입력 구조가 다릅니다. |
| Planning Coordinator | application/service layer에서 인증, input guardrail, snapshot, Agent Graph 호출, 저장 순서를 조정 | AI 소유 `AgentGraph` callable과 outcome 제공 | LLM이 권한·transaction·HTTP 상태를 직접 결정하지 않게 합니다. |
| DB 접근 | `app/shared/functions/`의 단일 구현과 ADR로 합의한 atomic boundary | SQL/ORM 직접 호출 금지 | API와 Agent용 DB 로직이 두 벌로 갈라지는 것을 막습니다. |
| Agent/Tool 내부 | 호출하지 않음 | Graph, prompt, 내부 schema, retry, Review | provider 세부 모델을 BE 저장 계약으로 결합하지 않습니다. |
| 절차 조회와 진행 ID | canonical step ID/code/name/alias와 Case progress 저장·복원. Kakao key/network/Evidence 보존 운영 지원 | Kakao 웹검색, 공식 URL 검증, 원문 fetch, Info 의미 분석과 canonical mapping | BE가 검색 내용을 작성하지 않으면서도 웹 제목을 DB ID로 오인하거나 progress를 유실하지 않아야 합니다. |
| 지원사업 | repository/read service에서 canonical ID/Wiki UUID와 승인 metadata·Evidence DTO 공급 | 원문을 승인 후보로 만드는 ingestion/catalog builder, runtime adapter와 비교 | 실제 API 공고와 내부 검수 지식 사이에 LLM 자기승인이 아닌 독립 승인 단계가 필요합니다. |
| Evidence | 사용자 입력·시스템 record·인증 확인 Evidence 발급, AI runtime이 만든 공식 URL/hash Evidence 저장·복원·보존 | 절차조회 Evidence ID 생성, 승인 후보 생성, runtime claim 선택과 lineage 검사 | 생성 주체는 source별로 달라도 같은 ID의 내용과 hash가 바뀌지 않아야 합니다. |
| Review 이후 저장 | Guardrail, CAS, idempotency, transaction, History | `ReviewSubject`와 proof 생성 | Review PASS만으로 현재 DB 상태나 권한을 보장할 수 없습니다. |
| 외부 HTTP 응답 | status, camelCase DTO, 오류 및 viewState | Agent outcome을 shared DTO로 전달 | 내부 snake_case와 FE 계약을 분리해야 합니다. |

Supervisor와 하위 Agent/Tool 사이의 provider schema와 내부 호출은 AI 소유입니다. BE가 반드시 소비해야 하는 경계는 Coordinator→Agent Graph 입력/결과와 Coordinator→Guardrail/persistence 계약입니다. Agent 구성요소를 별도 서비스로 분리하기 전에는 내부 `ComponentRequest`/`ComponentResult`를 BE HTTP API로 만들 필요가 없습니다.

`ReviewedSupportCatalog`는 LLM이 자신의 추출 결과를 “검수 완료”로 승격해서 만들 수 없습니다. 인증된 도메인 담당자의 승인 또는 사전 승인된 deterministic ingestion 규칙을 거쳐야 하며, BE는 최소 `review_status`, `reviewed_by` 또는 승인 규칙 ID, `reviewed_at`, source content hash, catalog version을 보존해야 합니다.

## 3. BE가 제공해야 하는 문서 산출물

다음 산출물은 코드 구현과 함께 source control에서 검토할 수 있어야 합니다.

| 필수 산출물 | 최소 내용 | 근거 | 필요한 이유 | 승인 기준 |
|---|---|---|---|---|
| OpenAPI 명세 | 모든 Case/result/subsidy/history endpoint, auth, request/response tagged union, 오류 | `interface-spec.md` §1~§13은 현재 예시와 TBD를 포함 | 문서 예시와 실제 FastAPI 응답의 drift를 막습니다. | CI에서 생성한 OpenAPI와 snapshot을 비교하고 정상·오류 예시가 validation을 통과합니다. |
| shared DTO 문서와 코드 | §5의 타입, 필수/nullable, enum, 생성 주체, schema version | schema 문서 §4~§14·§21 | `dict`나 암묵적 변환은 누락·타입 혼동을 늦게 발견합니다. | AI/BE가 같은 fixture를 각자 deserialize하고 재직렬화 결과를 비교합니다. |
| canonical field/enum registry | field key, type, 허용 enum, 미확인 표현, deprecated 값, version | schema 문서 §6·§19, DB/API enum 불일치 | 같은 값이 `LEASED`, `LEASED_PAID`, `ACTIVE`로 갈라져 있습니다. | 하나의 versioned registry와 양방향 migration/mapping 표가 있습니다. |
| DB data dictionary와 migration | 실제 table/column/index/FK/nullability/version column | `schema_table.md`, schema 문서 §18·§19 | 목표 DTO에 있으나 물리 DB에 없는 필드가 있습니다. | migration 적용·rollback 테스트와 DTO 조립 테스트가 통과합니다. |
| 인증·소유권 정책 | JWT claim, 401/403/404 정책, member/case 조건, service-to-service 호출 | `backend/CLAUDE.md`, `interface-spec.md` §2 | 권한 없는 Case 존재 여부와 내용이 노출되면 안 됩니다. | 다른 사용자의 Case ID로 조회·저장할 수 없는 테스트가 있습니다. |
| 동시성·idempotency ADR | version 또는 field CAS, `client_event_id` 의미·보존, retry 정책 | schema 문서 §14·§19 | LLM 실행 중 Case가 바뀔 수 있고 같은 요청이 재전송될 수 있습니다. | 중복 요청은 중복 이력을 만들지 않고 stale snapshot 저장은 거부됩니다. |
| transaction ADR | 변경, Evidence, decision, History 저장 순서와 rollback/`REPLAN_FAILED` 정책 | `architecture.md` §3·§10, schema 문서 §14 | 일부만 저장되면 Review한 상태와 사용자에게 보인 상태가 달라집니다. | fault injection에서 허용되지 않은 부분 저장이 없습니다. |
| Evidence·개인정보 정책 | source type별 생성 주체, ID/locator, lineage, hash, 보존, 삭제, 외부 공개, trace redaction | schema 문서 §5·§19, `architecture.md` §6·§8 | 근거 재현성과 개인정보 최소화를 동시에 만족해야 합니다. | 모든 ref가 resolve되고 인증 token 값과 raw PII가 log·trace에 없으며 집계 token count만 허용됩니다. |
| canonical procedure registry 명세 | step ID/code/name, 발화 alias와 registry version, deprecated mapping | `schema_table.md` §3, schema 문서 §6·§8·§19 | 인터넷 제목은 안정 ID가 아니며 Case progress FK는 계속 canonical ID가 필요합니다. | ID/code/name/alias가 unique하고 미매핑 web finding은 DB ID를 만들지 않습니다. |
| 절차 인터넷 조회 운영 명세 | Kakao key secret·rotation·호출 허용 IP, quota/rate limit, 공식 domain allowlist 변경 승인, redirect/SSRF, timeout·MIME·byte 상한, cache와 장애 대응 | schema 문서 §10, Kakao 공식 문서 | 실제 조회는 외부 provider와 공식기관 서버에 의존하며 credential·보안·지연이 production endpoint에 영향을 줍니다. | key 없이 fail closed하고 비공식/private URL·unsafe redirect를 거부하는 통합 테스트와 runbook이 있습니다. |
| support catalog 명세 | DB ID, Wiki UUID, 외부 공고 ID, version, freshness, source, 검수 상태·주체·시각·hash | `schema_table.md` §5, 실제 기업마당 호환성 결과 | 실제 공고 payload는 Agent 판정용 구조화 조건을 직접 제공하지 않습니다. | 검수되지 않은 version을 주입할 수 없고 외부 ID가 canonical row와 reviewed catalog에 안정 매핑됩니다. |
| conflict lifecycle 명세 | `conflict_ref` 발급·복원·만료, digest/version 결합, 확인 audit | schema 문서 §6·§18·§19 | standalone ref는 운영 endpoint에서 신뢰할 수 없습니다. | 변조·만료·다른 Case·stale version 확인 요청을 거부합니다. |
| digest 고정 test vector | canonical JSON bytes와 SHA-256 결과, timezone/UUID/enum 예시 | schema 문서 §12·§18 | Python Agent와 BE 구현의 직렬화 차이는 proof 불일치를 만듭니다. | 두 구현에서 동일 vector가 byte-for-byte 같은 digest를 만듭니다. |
| contract fixture 묶음 | 정상, unknown, conflict, stale Evidence, no-change, version conflict, invalid transition | schema 문서 §20 | happy path만으로 조건부 불변식을 검증할 수 없습니다. | BE와 AI CI에서 같은 fixture가 같은 성공/실패 분기로 끝납니다. |
| 실제 연동 runbook | 개발 base URL, token 취득, test user/Case seed, source key 보관, cleanup, 동기화·장애 대응 | 실제 Case 조회에 필요한 연결 정보가 현재 없음 | 코드가 있어도 재현 가능한 환경과 권한이 없으면 통합 검증할 수 없습니다. | 비밀값을 저장소에 남기지 않고 권한 있는 개발자가 read-only smoke를 재현합니다. |

### BE가 제출해야 하는 구현 산출물

문서만 작성해서는 생산 연동이 완료되지 않습니다. P0 합의 뒤 아래 구현과 테스트가 함께 필요합니다.

| 구현 산출물 | 근거 | 필요한 이유 | 승인 기준 |
|---|---|---|---|
| Case/result/subsidy/history router와 외부 DTO adapter | OpenAPI, `interface-spec.md` | FE wire 계약과 내부 Agent 계약을 분리합니다. | 생성 OpenAPI 및 정상·오류 response fixture가 일치합니다. |
| JWT/auth dependency와 ownership query | `backend/CLAUDE.md` | 권한 없는 Case가 snapshot이나 오류 차이로 노출되면 안 됩니다. | 타 사용자 Case read/write 부정 테스트가 통과합니다. |
| versioned shared DTO 코드와 snapshot assembler | schema 문서 §7·§14·§21 | 공개 GET projection만으로는 Agent 입력을 만들 수 없습니다. | 한 읽기 시점에서 만든 DTO가 AI adapter와 strict schema를 통과합니다. |
| canonical procedure registry, support/Evidence repository와 read service | schema 문서 §5·§6·§8·§9 | 안정 progress ID, support metadata, 인터넷 조회 Evidence를 저장·복원합니다. | unknown·stale·삭제·새 revision fixture와 미매핑 web finding을 안전하게 처리합니다. |
| Planning Coordinator와 Graph 호출 경계 | architecture §3, schema 문서 §2·§4 | BE가 request/run/trace/deadline context를 만들고 AI entrypoint가 이를 받아 한 실행에 결합합니다. | 공통 fixture가 양쪽 경계를 통과하고 구성요소 실패도 tagged outcome으로 닫힙니다. |
| Output/State Transition Guardrail | architecture §5·§11, schema 문서 §14 | Review PASS만으로 권한·현재 DB 상태·전이를 보장할 수 없습니다. | tamper, stale version, invalid transition을 저장 전에 거부합니다. |
| idempotency registry와 production conflict ref 함수 | schema 문서 §6·§14·§19 | 중복 실행과 변조 가능한 standalone ref 노출을 막습니다. | 동시 replay는 한 번만 실행되고 ref 변조·재사용·만료를 거부합니다. |
| `persist_reviewed_plan()`과 migration/index/FK/unique constraint | schema 문서 §14, transaction ADR | decision, mutation, History, Evidence 참조의 부분 저장을 막습니다. | fault injection과 read-back에서 합의된 atomicity가 유지됩니다. |
| contract·integration·concurrency·fault-injection 테스트 | schema 문서 §20 | happy path만으로 안전 불변식을 증명할 수 없습니다. | §12 승인 시나리오와 공통 fixture가 CI에서 통과합니다. |

## 4. 구현 전에 닫아야 할 P0 결정

| P0 결정 | 현재 충돌·근거 | 결정이 필요한 이유 | 필요한 BE 응답 |
|---|---|---|---|
| Case 동시성 | 물리 CASE에는 version이 없고 API 예시는 `caseVersion/expectedVersion`을 사용 | snapshot 이후 변경을 덮어쓰지 않으려면 저장 조건이 필요합니다. | version column 채택 또는 모든 변경 대상의 atomic compare-and-set 설계 |
| 미확인 사실 표현 | Agent는 `status=UNKNOWN, value=null`, DB enum은 `UNKNOWN`이 없거나 nullable 정책이 다름 | null, 미수집, 명시적 비움, 해당 없음은 의미가 다릅니다. | fact status 저장 방식과 API 표현 |
| Case field 저장 위치 | `entity_type`, `building_use_type`, `previous_support_history`가 목표 입력에는 있고 CASE table에는 없음 | 실제 지원조건 비교에 필요한 값을 snapshot에서 복원할 수 없습니다. | column/별도 fact table/스코프아웃 중 하나와 migration |
| v1 field 범위 | Hero Scenario의 `lease_end_date`, `transfer_status`, `tax_status`가 현재 API/DB에 없음 | 없는 필드로 Agent가 판단하면 저장·재조회 시 정보가 사라집니다. | v1 포함 여부와 포함 시 canonical type |
| enum 정합성 | lease는 DB `LEASED`, API `LEASED_PAID`, standalone `ACTIVE`; restoration scope도 값이 다름 | adapter에서 임의 해석하면 Case 의미가 바뀝니다. | canonical enum과 legacy mapping/deprecation 표 |
| procedure identity/registry | DB 초안은 name 중심이고 Agent progress는 ID+`step_code`, Info mapping은 name+alias+registry version을 요구 | 웹 제목이나 모델이 DB ID를 만들지 않고 이름 변경 뒤에도 과거 진행상태를 복원해야 합니다. | stable step code, registry version, alias/deprecation contract. 절차 내용·조건·Evidence master는 요구하지 않음 |
| 절차검색 운영 | Kakao key와 일반 login client ID의 의미가 기존 env에서 혼동될 수 있고 외부 fetch는 SSRF·latency·quota 위험이 있음 | 잘못된 credential fallback이나 무제한 fetch는 장애·보안사고를 만듭니다. | `PROCEDURE_SEARCH_API_KEY` 우선, `KAKAO_CLIENT_ID` fallback의 실제 값 의미 확인, secret rotation, egress/allowlist, timeout·cache·quota ownership |
| support identity | DB `id/uuid`, API 문서 `supportItemId`, Agent `support_program_id/wiki_uuid`, 기업마당 `PBLN_...` | 외부 공고와 내부 검수 노트·신청 row를 같은 사업으로 연결해야 합니다. | canonical 이름과 external ID mapping table/resolver |
| match/application 분리 | DB `application_status`에 `ELIGIBLE/NOT_ELIGIBLE`가 섞여 있고 Agent는 비교와 실제 신청을 분리 | 조회만으로 신청 row를 만들거나 자격을 확정하면 안 됩니다. | 별도 support match 저장 모델과 application lifecycle |
| 자연어 신청상태 변경 | `/results`가 신청 완료 표현도 저장할지 PATCH만 사용할지 미정 | 이중 write 경로는 상태 전이와 idempotency를 깨뜨립니다. | 단일 권한 경로와 허용 전이 |
| Evidence 저장/resolver | 현재 물리 schema에 공통 Evidence/lineage 계약 없음 | Review와 감사에서 당시 근거를 복원할 수 없습니다. | ID, hash, locator, source version, lineage, retention 설계 |
| decision/Review 저장 위치 | CASE_LOG는 raw input과 next action 위주이며 digest/proof/run 연결이 없음 | 어떤 payload가 Review를 통과했는지 재현할 수 없습니다. | decision, subject digest, proof, run/trace 저장 모델 |
| conflict confirmation | `/results/confirm` request가 임의 값을 다시 전송하는 예시이고 server ref 방식 미정 | 사용자 확인이 원 conflict에 결합되지 않으면 값 바꿔치기가 가능합니다. | opaque ref 기반 계약, version/CAS, TTL |
| production conflict ref 결합 | 현재 Info Agent는 `standalone:` simulation ref를 생성 | 운영 응답에 simulation ref를 노출하거나 확인 API에서 신뢰할 수 없습니다. | pending conflict 저장 후 BE가 ref를 결합할지 `ConflictRefFactory`를 Graph에 주입할지와 관련 DTO 확정 |
| idempotency | `client_event_id`는 제안됐으나 uniqueness와 보존기간 미정 | 모바일·네트워크 retry가 중복 계획과 중복 History를 만들 수 있습니다. | scope, unique constraint, replay response, retention |
| result 우선순위 | 한 요청에 변경 후보와 추가 질문이 함께 생길 수 있음 | 하나의 외부 discriminator로 어떤 상태를 노출할지 필요합니다. | outcome mapping 표와 예제 |
| decision cardinality | Blocker 1개·Next Action 1개는 `ACTION`에만 적용하고, Next Action은 required `PROCEDURE | SUPPORT_PROGRAM` target tagged union을 가짐. `NEEDS_MORE_INFO`, `CASE_COMPLETE`는 구조가 다름 | nullable target이나 문자열 추정은 source provenance를 잃고 외부 DTO/DB/FE `viewState`도 decision별로 달라집니다. | decision별 필수·금지 필드, target discriminator와 canonical ID resolver, 표시 mapping |
| catalog 승인 주체 | 자연어 공고 구조화와 검수 완료 승격 주체가 아직 없음 | LLM 자기검수만으로 trusted catalog를 만들 수 없습니다. | 도메인 담당자 또는 승인된 deterministic rule, audit metadata와 배포 gate |
| Graph invocation envelope | 목표 문서는 Coordinator가 run ID/deadline을 만들지만 현재 Graph가 run ID를 생성 | 양쪽이 ID를 만들면 trace·idempotency·proof 연결이 갈라집니다. | BE가 run/trace를 생성하고 AI entrypoint가 소비하는 방식, deadline을 DTO 필드 또는 별도 execution context로 전달할지 확정 |
| Graph 호출 선택 | v2 first pass는 Procedure→Info→Support 고정 dependency이고 이후 Supervisor가 Review 재작업을 조정 | lookup 없이 Info가 절차를 만들거나 오래된 raw 결과를 재사용하면 provenance가 끊깁니다. | first-pass 고정 dependency와 trigger별 생략 가능 조건 공동 승인 |
| timeout/retry | standalone에는 상한이 있으나 BE request timeout과 재시도 정책 미정 | BE timeout과 Agent retry가 겹치면 중복 실행·비용이 커집니다. | 전체 deadline, 구성요소 budget, retry ownership |
| transaction/실패 | Case 변경 뒤 재계획 실패 시 rollback/유지 정책 미정 | DB 상태와 latest decision이 서로 다른 시점을 가리킬 수 있습니다. | 원자성 경계와 `REPLAN_FAILED` 응답/재처리 정책 |
| redaction/audit | runtime/model/telemetry별 전달 범위와 보존 정책 미정 | 실제 사용자 원문과 인증정보가 외부 LLM·trace로 유출될 수 있습니다. | `input_event_id`, source type, placeholder, Unicode code-point offset, 시각, 원문 보존·삭제, 단계별 allowlist와 access audit |

P0가 닫히기 전에는 BE 또는 AI 어느 쪽도 임의 enum, default, 저장 위치를 production 계약으로 확정하지 않습니다.

## 5. 우선 제공할 shared DTO

공동 승인 전 필드 제안의 단일 출처는 `agent-tool-io-schema.md`입니다. 승인 뒤에는 versioned shared DTO 코드와 그 코드에서 생성한 JSON Schema/OpenAPI를 규범적 출처로 삼고, Markdown은 근거와 설명을 유지합니다. BE는 아래 순서로 DTO를 제공하고 AI와 contract fixture를 교환합니다.

| 순서 | DTO | 생성·검증 주체 | 이유 |
|---:|---|---|---|
| 1 | `SharedCaseSnapshotDTO`와 nested fact/procedure/support/decision/history DTO | BE 생성, AI adapter가 `CaseSnapshot`으로 변환·strict 검증 | 나머지 모든 판단의 기준 입력이며 공개 GET response와 구분됩니다. |
| 2 | `EvidenceRecord`와 resolver 계약 | source별 신뢰 주체가 ID 발급, BE가 저장·복원, AI가 runtime 검증 | 절차조회 runtime의 URL/hash Evidence를 포함해 사실·절차·지원·결정의 근거를 닫힌 집합으로 만듭니다. |
| 3 | `RedactedInput`과 원문 보존 계약 | BE input guardrail 생성, Agent offset 검증 | 인증정보를 제거하면서 선택 span을 원 입력에 대조할 수 있어야 합니다. |
| 4 | `ComponentRequest[SupervisorRunInput]`, trigger variants, `ConfirmedConflictResolution` | BE Coordinator가 top-level run/call/trace context 생성, AI entrypoint 소비 | schema/run/call/case/trace와 실행 원인·idempotency·확인 proof를 결합합니다. 내부 component call ID는 Agent runtime이 만들고 deadline은 DTO 필드 또는 별도 execution context 중 §4 결정에 따릅니다. |
| 5 | `ReviewSubject`, `ReviewProof`, `MutationSet` | Agent 생성, BE 무결성 재검증 | 검토된 내용과 저장 후보를 정확히 고정합니다. |
| 6 | 목표 `AgentRunOutcome` | Agent 생성, Coordinator 소비 | `REVIEWED_PLAN`, `CONFLICT`, `NO_CHANGE`, `SAFE_FAILURE`를 null 조합 없이 구분합니다. 현재 runtime의 `NO_CHANGE`는 미구현입니다. |
| 7 | `OutputGuardrailProof`, `StateGuardrailProof`, `GuardrailRejection`, production conflict ref DTO | Coordinator/BE | Review 이후 형식·현재 상태 검증과 운영용 충돌 참조 발급을 증명합니다. |
| 8 | `PersistReviewedPlanCommand`, `PersistResult`, `ConcurrencyConflictDetail` | Coordinator 요청, BE 저장 함수 응답 | 일부 저장이나 stale snapshot 반영을 막습니다. |
| 9 | 외부 API response와 `viewState` DTO | BE 생성 | 내부 Agent 모델을 FE wire 계약으로 직접 노출하지 않습니다. |

LLM provider 전용 `InfoProviderOutput`, `SupportProviderOutput`, `SupervisorModelOutput`, `ReviewProviderOutput`은 BE shared DTO가 아닙니다. 이 모델은 외부 provider 제약을 위한 최소 projection이며 runtime ID, 인증, 저장 의미를 갖지 않습니다.

## 6. `CaseSnapshot` 조립 계약

BE는 소유권 확인 뒤 한 시점의 일관된 read view에서 `SharedCaseSnapshotDTO`를 조립해야 합니다. 아래 표는 shared DTO 영역과 목표 Agent `CaseSnapshot` 영역의 1:1 의미 매핑입니다. AI adapter는 명시적 이름·enum·datetime 변환만 할 수 있고 누락값에 default를 만들거나 Evidence를 합성할 수 없습니다.

| 목표 snapshot 영역 | 예상 원천 | 현재 상태 | BE가 확정할 내용 | 이유 |
|---|---|---|---|---|
| `case_id`, `case_status` | CASE | DB 초안 존재 | canonical 값과 ownership query | 실행 대상 Case를 고정합니다. |
| `case_version` | CASE 또는 field CAS | 미정 | version 채택 여부 | stale 판단 저장을 막습니다. |
| `facts` | CASE columns 또는 별도 fact table | 일부 column 존재, enum 불일치 | registry, unknown/null, updated time, Evidence | LLM에 DB row shape를 직접 노출하지 않습니다. |
| `procedure_progress` | CASE_CLOSURE_PROCEDURE_STEP_PROGRESS | 존재 | step ref, Evidence, row 없음 의미 | 실제 완료와 단순 추천을 구분합니다. |
| `support_applications` | SUPPORT_PROGRAM_APPLICATION | 존재하나 비교 상태 혼재 | 실제 신청 lifecycle만 포함 | 조회 결과가 신청 상태를 만들지 않게 합니다. |
| `support_matches` | 신규 또는 판단 이력 projection | 물리 모델 없음 | match status, source version, freshness, Evidence | 같은 지원사업을 매 실행마다 무근거로 다시 판단하지 않게 합니다. |
| `latest_decision` | CASE_LOG/BLOCKER 또는 신규 decision table | digest/proof 저장 부족 | Review된 decision 전체와 subject digest | 화면과 다음 실행이 마지막 검토 결과를 공유합니다. |
| `history_window` | CASE_LOG/History | bounded policy 미정 | limit, selection policy, truncated 표시 | 전체 원문을 LLM에 반복 전달하지 않고 필요한 맥락만 줍니다. |
| `evidence_records` | Evidence 저장소와 source resolver | 공통 모델 없음 | 이번 snapshot 참조의 닫힌 최소 집합 | dangling ref와 과도한 개인정보 전달을 막습니다. |
| `snapshot_id`, `captured_at` | snapshot assembler | 미구현 | runtime 생성과 timezone | Review와 저장을 정확한 읽기 시점에 결합합니다. |

`UNKNOWN` fact는 Evidence가 없을 수 있습니다. 그러나 “현재 정보 없음” 자체를 Blocker나 질문 근거로 사용할 때는 해당 JSON Pointer와 snapshot 시각을 가리키는 `SYSTEM_RECORD` Evidence를 포함해야 합니다.

현재 실행 코드의 `CaseSnapshot`은 `support_applications`, `support_matches`, `latest_decision`, `history_window`를 아직 받지 않습니다. `AgentSchema`가 extra field를 거부하므로 BE가 목표 DTO를 먼저 제공하더라도 자동으로 연결되지 않습니다. shared DTO 합의 뒤 AI가 실행 모델과 adapter를 함께 확장해야 합니다.

## 7. 필요한 read-only 함수와 API

함수명은 제안이며 BE convention에 맞게 바꿀 수 있습니다. 단, 입력과 출력은 합의된 typed DTO여야 하고 임의 `dict`를 반환하면 안 됩니다.

| 기능 | shared function 의미 | HTTP/API | 쓰기 여부 | 근거와 이유 |
|---|---|---|---:|---|
| Agent snapshot 조립 | `build_authorized_case_snapshot(auth_context, case_id) -> SharedCaseSnapshotDTO` | 내부 전용 | 없음 | Agent 판단에 필요한 Evidence·history·support 영역은 공개 FE 응답과 다르며 한 읽기 시점이어야 합니다. |
| 공개 Case view 조회 | 같은 read service를 FE projection으로 변환 | `GET /cases/{caseId}` | 없음 | 공개 응답을 내부 `CaseSnapshot`과 동일시하지 않고도 상태 drift를 막습니다. |
| 지원 상태 조회 | Case의 match와 실제 application을 분리 반환 | `GET /cases/{caseId}/subsidies` | 없음 | 조회만으로 application row를 생성하지 않습니다. |
| bounded history 조회 | 최근 이력과 active decision 관련 이력 반환 | `GET /cases/{caseId}/history` | 없음 | raw history 전체를 LLM에 넘기지 않습니다. |
| canonical procedure registry 조회 | stable step ID/code/name/alias/deprecated mapping 반환 | 내부 shared function 또는 versioned GET | 없음 | Info가 웹자료를 기존 progress ID에만 결합하고 새 DB ID를 만들지 않습니다. 절차 내용은 반환하지 않습니다. |
| support registry 조회 | canonical ID/Wiki UUID/external ID/source version 반환 | 내부 shared function 또는 versioned GET | 없음 | 실제 공고, Wiki, application row를 안정적으로 연결합니다. |

실제 Case를 검증할 때는 내부 snapshot assembler와 위 GET/read 경로만 먼저 연결하고 각각의 DTO를 따로 검증합니다. `POST /cases`, `POST /results`, `POST /results/confirm`, `PATCH /subsidy-applications/...`는 통합 저장 계약과 테스트가 끝나기 전에 실데이터 smoke test에 사용하지 않습니다.

### 절차 인터넷 조회 운영 경계

ProcedureLookupTool의 검색·원문 fetch·raw schema는 AI 소유이며 BE가 `ProcedureMaster`나 검색 결과 내용을 작성하는 API를 만들 필요가 없습니다. 다만 같은 backend process 또는 AI service가 production에서 외부 요청을 수행할 수 있도록 다음 운영 경계를 공동 확정해야 합니다.

| 항목 | AI 책임 | BE/인프라 책임 | 이유와 승인 기준 |
|---|---|---|---|
| Kakao credential | `PROCEDURE_SEARCH_API_KEY` 우선, `KAKAO_CLIENT_ID` fallback 로딩과 header 비노출 | 올바른 REST API 키 secret 주입·rotation·호출 허용 IP | key 없음/401/403을 빈 결과로 숨기지 않고 fail closed합니다. |
| Kakao 호출 | `PROCEDURE_SEARCH_ENDPOINT`를 고정 `https://dapi.kakao.com/v2/search/web`로 검증하고 page/size 상한·strict parse 적용 | outbound HTTPS, quota/rate-limit 관측 | provider 결과 수와 실패를 `ProcedureSearchSummary`에 기록합니다. 임의 endpoint나 query가 붙은 override는 거부합니다. |
| URL 안전성 | `PROCEDURE_SEARCH_ALLOWED_DOMAINS`는 코드 검토 root/하위 host로만 축소, HTTPS·표준 port·IP-literal 금지·redirect/MIME/byte/time 제한 | 새 공식 domain root의 코드·보안 승인, hostname DNS 해석 결과의 private range 차단·DNS rebinding 방어와 egress 정책 | 현재 application 검증만으로 해결되지 않는 DNS 목적지까지 차단하고, allowlist는 환경변수나 사용자 입력만으로 trust root를 확장하지 않습니다. |
| 원문 Evidence | fetch 본문의 excerpt/hash/retrieved_at/freshness 생성 | Evidence 저장·resolver·보존/삭제 | 검색 snippet이 아니라 당시 읽은 실제 공식 원문을 복원할 수 있어야 합니다. |
| cache | canonical URL/hash 기반 재검증과 stale/unknown 처리 | TTL, 용량, 장애 시 stale 사용 정책 승인 | 캐시를 최신 원문으로 오인하거나 과거 판단을 덮어쓰지 않습니다. |
| deadline·응답 상한 | 요청별 `PROCEDURE_SEARCH_TIMEOUT_SECONDS`, 전체 `PROCEDURE_SEARCH_TOTAL_TIMEOUT_SECONDS`, retry/backoff, response byte, redirect 및 provider 결과 수의 로컬 상한 검증과 취소 전파 | gateway/Coordinator 전체 budget | Kakao·공식 사이트·LLM 최악 시간을 긴 DB transaction 안에 두지 않고 대형/무한·과다 결과 응답을 차단합니다. |

Kakao 공식 근거:

- [Daum 검색 REST API 개발 가이드](https://developers.kakao.com/docs/ko/daum-search/dev-guide): `GET https://dapi.kakao.com/v2/search/web`, REST API 키, query/page/size와 title/contents/url/datetime 응답
- [Kakao REST API 시작하기](https://developers.kakao.com/docs/ko/rest-api/getting-started): 서버 환경의 REST API 사용
- [Kakao 앱 키 설정](https://developers.kakao.com/docs/ko/app-setting/app): REST API 키·호출 허용 IP 관리
- [Kakao 쿼터 안내](https://developers.kakao.com/docs/ko/getting-started/quota): 검색 quota와 사용량 관측

Kakao의 `contents`는 검색 결과 일부일 뿐 공식 원문이 아니므로 Evidence로 저장하지 않습니다. Tool은 allowlist를 통과한 URL을 직접 fetch하고, 발행·수정일을 검증하지 못하면 `freshness_status=UNKNOWN`으로 둡니다.

## 8. 실제 기업마당 데이터와 support catalog 경계

2026-09-15에 [기업마당 공식 지원사업정보 API](https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi)를 Agent runtime과 별개로 GET 호출했습니다. 이는 그 시점의 수동 read-only 관찰이며 API key, sanitized response fixture, hash, 재현 script가 저장소에 없으므로 변동 가능한 건수와 payload를 자동 회귀 증거로 사용하지 않습니다. 응답과 현재 Agent 계약의 차이는 다음과 같습니다.

| 실제 API 필드 | 예시/의미 | Agent 목표 | 담당과 필요한 변환 | 이유 |
|---|---|---|---|---|
| 문서상 필수 `seq`, 관찰된 optional `pblancId` | 예: `PBLN_000000000117676` | `support_program_id` + `wiki_uuid` | 어떤 source ID를 primary/fallback으로 쓸지 정하고 내부 ID/Wiki UUID에 매핑 | optional 필드 하나만 stable ID로 가정하면 일부 공고를 연결하지 못합니다. |
| `pblancNm` | 공고명 | `program_name` | 직접 복사 가능하나 source Evidence 결합 | 표시명은 stable ID가 아닙니다. |
| `bsnsSumryCn`, `trgetNm` | 자연어 개요와 대상 | 구조화 `criteria[]` | AI가 구조화 초안을 만들 수 있으나 도메인 담당자 또는 승인된 deterministic rule이 승인하고 BE가 승인본을 제공 | 자연어 대상을 자동으로 자격 확정식으로 쓰거나 LLM이 자기승인하면 오판합니다. |
| `reqstMthPapersCn` | 신청방법 중심 자연어 | channel + required documents | 항목을 분리하고 공식 문서로 교차 검수 | 신청방법과 필요서류는 같은 의미가 아닙니다. |
| `reqstBeginEndDe` | 날짜 또는 `세부사업별 상이` | sourced application period/freshness | 원문 보존, 구조화 가능할 때만 날짜화 | 자유문장을 임의 날짜로 변환하면 기한 오류가 생깁니다. |
| `pblancUrl`, `printFlpthNm` | 공식 페이지/첨부 | `EvidenceRecord` | official source ref, locator, hash, retrieved time 생성 | 어떤 원문 버전을 사용했는지 재현해야 합니다. |
| 문서화된 `creatPnttm`, item `pubDate`, channel `lastBuildDate`; 관찰 시 optional `updtPnttm` | 생성·발행·feed 갱신 시각 | `source_version`, freshness | 공식 필드, 원문 hash, 조회 시각을 함께 사용하고 미문서 필드 하나에 의존하지 않음 | source 수정과 feed 갱신은 의미가 다르므로 단일 시각으로 최신성을 단정할 수 없습니다. |
| 제공되지 않음 | 내부 절차 연결 | `related_steps` | canonical procedure mapping을 별도 검수 | 모델이 관계를 임의 생성하지 않게 합니다. |

수동 점검에서 실제 원문은 `EvidenceRecord`로 검증됐지만 raw item에는 `ReviewedSupportProgram`이 요구하는 `support_program`, `related_steps`, `criteria`, `required_documents` key가 없어 직접 변환이 실패했습니다. `criteria`는 최소 1개가 필요하고, `related_steps`와 `required_documents`는 검수 결과 실제로 없을 때 빈 목록이 가능하지만 API 누락을 근거로 자동 삽입해서는 안 됩니다.

권장 ingestion 경계는 다음과 같습니다.

```text
기업마당 GET
  → 원문 보존·hash·source version
  → external ID ↔ canonical support row 매핑
  → 조건·서류·기간 구조화
  → 공식 첨부 교차 확인
  → 도메인 담당자 또는 승인된 deterministic rule의 검수
  → review_status/reviewer/rule ID/reviewed_at/source hash 기록
  → immutable ReviewedSupportCatalog version 발행
  → Support Agent read-only 주입
```

## 9. Guardrail과 persistence 계약

`ReviewedPlanOutcome`과 `ReviewProof`는 저장 허가가 아닙니다. BE/Coordinator는 다음 순서를 지켜야 합니다.

```text
Agent REVIEWED_PLAN
  → ReviewSubject digest 재검증
  → Output Guardrail: payload를 수정하지 않고 PASS 또는 전체 거부
  → State Transition Guardrail: 현재 DB 재조회 + version/field CAS
  → 모든 mutation 전체 승인 또는 전체 거부
  → PersistReviewedPlanCommand
  → ADR로 합의한 atomic boundary에서 Evidence/변경/decision/History 저장
  → PersistResult
```

| 요구사항 | 근거 | 이유 | 승인 기준 |
|---|---|---|---|
| proof ID/digest 일치 | schema 문서 §12·§14 | 다른 Case나 수정된 초안에 PASS를 재사용하지 못하게 합니다. | run/case/subject/digest 불일치는 저장 전 거부합니다. |
| 저장 직전 상태 재조회 | schema 문서 §14 | Agent 호출 동안 다른 요청이 Case를 바꿀 수 있습니다. | version 또는 각 before state가 다르면 `VERSION_CONFLICT`입니다. |
| mutation 전체 승인/거부 | schema 문서 §14 | Review하지 않은 부분집합은 새로운 계획입니다. | 일부 후보만 저장하는 함수 경로가 없습니다. |
| 상태 전이 재검증 | `backend/CLAUDE.md`, architecture §5 | LLM/Review는 DB 제약과 현재 row를 최종 권한으로 알 수 없습니다. | 역행·확인 전 덮어쓰기·근거 없는 완료를 거부합니다. |
| 짧은 atomic unit | architecture §10 | 외부 LLM 호출을 DB atomic boundary 안에 두면 lock과 실패 범위가 커집니다. | LLM/외부 API 호출은 저장 전에 끝나며 정확한 transaction 분할은 ADR로 고정합니다. |
| Evidence와 원자적 참조 | schema 문서 §14 | dangling evidence ref를 만들지 않습니다. | Evidence를 선행 idempotent upsert하거나 같은 boundary에 저장하되, Case mutation과 decision/History 참조는 함께 성공·실패합니다. |
| idempotent replay | schema 문서 §19 | client/provider retry가 중복 row를 만들지 않게 합니다. | 같은 client event는 기존 결과를 반환하고 새 History를 만들지 않습니다. |

## 10. 외부 endpoint와 outcome 매핑

| Endpoint | BE 책임 | Agent 사용 | 계약상 주의점 |
|---|---|---|---|
| `POST /cases` | 인증, Case 생성, 초기 상태/History, Coordinator 호출 | 최초 계획 | 생성과 계획 실패의 transaction 정책을 명시해야 합니다. |
| `GET /cases/{caseId}` | 현재 `CaseCurrentViewResponse` projection | 기본적으로 LLM 호출 없음 | 내부 Agent snapshot이 아니며, 단순 화면 조회에 Agent를 호출하지 않습니다. |
| `POST /cases/{caseId}/results` | input guardrail, snapshot, Agent 호출, 저장·응답 | 재계획 | `expectedVersion`/idempotency와 실패 결과를 tagged union으로 정합니다. |
| `POST /cases/{caseId}/results/confirm` | conflict ref/소유권/version 확인, 재계획·저장 | confirmed trigger | 임의 field/value만 받아 원 conflict 없이 저장하지 않습니다. |
| `GET /cases/{caseId}/subsidies` | match와 application 조회 | stale/missing 시 별도 재계획 가능 | 조회 자체가 신청 row를 만들지 않습니다. |
| `PATCH /subsidy-applications/{applicationId}` | 명시적 신청상태 변경 | 없음 | 실제 사용자 행동이 있을 때만 허용합니다. |
| `GET /cases/{caseId}/history` | bounded history projection | 다음 snapshot의 제한된 context | 실제 raw input 전체를 기본 반환하지 않습니다. |

HTTP 응답은 내부 `AgentRunOutcome`을 그대로 노출하지 말고, `result` discriminator와 `viewState`를 가진 외부 DTO로 변환합니다. 내부 snake_case, 외부 camelCase, timezone 포함 datetime을 명시적으로 매핑해야 합니다.

## 11. 오류와 재시도 계약

| 상황 | Agent/BE 결과 | 재시도 주체 | 이유 |
|---|---|---|---|
| Case 없음 또는 소유권 불일치 | 외부 `404` 정책 또는 합의한 비노출 오류 | 사용자 요청 수정 | 존재 여부 정보 유출을 막습니다. |
| invalid input/auth | Agent 실행 전 HTTP 오류 | client | LLM 호출 비용을 쓰기 전에 차단합니다. |
| LLM/provider 일시 장애 | `SAFE_FAILURE`, retryable metadata | Coordinator 또는 client, 전체 deadline 내 | 장애를 업무상 미대상으로 바꾸지 않습니다. |
| Review 소진 | `SAFE_FAILURE` | 새 요청 또는 운영 재처리 | 미검토 Blocker/Action을 반환하지 않습니다. |
| snapshot/version conflict | `VERSION_CONFLICT`, 최신 snapshot으로 재계획 | Coordinator | 이전 Review 결과를 새 상태에 저장하지 않습니다. |
| invalid transition | 전체 저장 거부 | 사용자 확인/새 입력 | 일부 mutation만 적용하지 않습니다. |
| 중복 client event | 기존 결과 replay | BE | 중복 실행·History·과금을 줄입니다. |

동기식 endpoint라면 BE/gateway deadline은 합의한 Agent 전체 worst-case execution budget과 network 여유보다 커야 합니다. timeout 이후 작업 취소 여부를 명시하고 client retry는 같은 `client_event_id`를 유지해야 합니다. 이 budget이 HTTP 운영 한계를 넘으면 비동기 job 계약을 별도로 합의합니다.

## 12. 통합 승인 시나리오

다음 테스트가 모두 통과해야 실제 Case 연동 완료로 보고합니다.

- [ ] 다른 사용자의 Case는 읽기와 쓰기 모두 거부됩니다.
- [ ] 내부 snapshot assembler가 한 읽기 시점에서 `SharedCaseSnapshotDTO`를 만들고 AI adapter를 거쳐 목표 `CaseSnapshot` 검증을 통과합니다.
- [ ] 공개 `GET /cases/{caseId}`는 같은 read service의 FE projection이며 내부 Evidence/history를 과다 노출하지 않습니다.
- [ ] 모든 confirmed fact와 completed procedure의 Evidence가 resolve됩니다.
- [ ] DB/API/Agent canonical enum fixture가 동일하게 해석됩니다.
- [ ] 각 `ProcedureLookupResult` document가 실제 공식 HTTPS `canonical_url`, `authority_name`, `source_domain`, `excerpt`, `retrieved_at`, `freshness_status`, `content_hash`와 1:1 Evidence를 갖고 Review source result에 포함됩니다.
- [ ] Info `procedure_findings`는 canonical registry step에만 결합되고 `based_on_procedure_lookup_call_id`/digest가 정확한 raw lookup을 가리킵니다.
- [ ] Kakao snippet, 비공식 domain, unsafe redirect는 Evidence가 되지 않고 unknown freshness로 기한·서류·의무를 확정하지 않습니다.
- [ ] 웹문서만으로 procedure progress나 `CASE_COMPLETE`를 저장하지 않습니다.
- [ ] 실제 기업마당 external ID가 canonical support ID/Wiki UUID에 안정 매핑됩니다.
- [ ] `pblancId` 없이 `seq`만 있는 item도 정책대로 매핑되고 공고 수정·종료·삭제는 새 catalog version/freshness로 처리됩니다.
- [ ] 자연어 공고만으로 자격을 확정하지 않고 unknown/confirmation을 유지합니다.
- [ ] 검수되지 않은 catalog version은 Support Agent에 주입되지 않고 새 revision이 과거 판단 기록을 덮어쓰지 않습니다.
- [ ] Review 전후 payload 변경 시 proof와 저장이 거부됩니다.
- [ ] snapshot 이후 Case 변경 시 `VERSION_CONFLICT`가 발생하고 아무 mutation도 저장되지 않습니다.
- [ ] 한 mutation 실패 시 나머지도 저장되지 않습니다.
- [ ] 같은 `client_event_id` 재전송은 새 History를 만들지 않으며 같은 ID의 다른 payload는 거부됩니다.
- [ ] 동일 idempotency key로 독립된 Graph run이 중복 시작되지 않습니다. 동일 run 안의 허용된 provider/Review retry는 구분해 기록하고 History·mutation side effect는 한 번만 반영합니다.
- [ ] conflict ref 변조·만료·다른 Case·이미 소비된 ref 재사용을 거부합니다.
- [ ] production `CONFLICT`의 모든 `source_evidence_refs`가 trigger/snapshot/outcome Evidence 집합에서 해석됩니다.
- [ ] `standalone:` conflict ref는 production HTTP 응답에 노출되지 않습니다.
- [ ] provider timeout과 Review 소진이 `SAFE_FAILURE`이며 기존 판단을 새 판단처럼 반환하지 않습니다.
- [ ] 저장 성공 후 read-back snapshot의 값과 persisted candidate가 일치합니다.
- [ ] prompt 원문, 인증 token 값, credential, 실제 주소와 raw input이 일반 log·trace에 남지 않습니다. 집계 prompt/completion token count는 허용합니다.
- [ ] Kakao search와 공식 원문 fetch의 pagination/상한, key 보관, allowlist, redirect/SSRF, rate limit, retry/cache, timeout과 장애 runbook이 검증됩니다.

## 13. BE 구현 뒤 필요한 AI 후속 작업

BE 구현만으로 생산 연동이 자동 완성되지는 않습니다. BE 산출물을 받은 뒤 AI가 다음을 구현·검증합니다.

| AI 후속 작업 | 선행 BE 산출물 | 필요한 이유 |
|---|---|---|
| BE shared snapshot DTO → `CaseSnapshot` adapter | shared DTO, canonical registry, 정상/오류 fixture | DB/HTTP shape와 공개 FE response를 모델 prompt에 직접 결합하지 않습니다. |
| runtime `CaseSnapshot` 확장 | applications, matches, latest decision, history 계약 | 현재 strict 모델은 목표 필드를 extra로 거부합니다. |
| `KnownProcedureStep[]` canonical registry adapter | versioned ID/code/name/alias DTO | Info가 웹 제목이나 모델 출력으로 DB step을 만들지 않고 기존 progress에만 finding을 연결합니다. |
| Kakao procedure search/fetch production adapter | secret/network/allowlist/deadline runbook | 실제 URL discovery와 원문 Evidence를 수행하고 key·unsafe URL·검색 snippet을 노출하지 않습니다. 검색 내용은 BE가 만들지 않습니다. |
| 기업마당/Wiki ingestion/catalog builder와 runtime adapter | canonical support registry, 승인·source 저장 계약 | 승인 후보와 trusted catalog를 분리하고 외부 공고의 누락 조건·서류·step을 임의 생성하지 않습니다. |
| Graph entrypoint의 외부 run context 수용 | BE가 생성한 `ComponentRequest`, deadline/trace 규칙 | 현재 Graph 내부 생성 ID를 Coordinator의 provenance와 맞추되 BE Coordinator 구현을 중복하지 않습니다. |
| 목표 mutation 필드 | persistence DTO | 절차의 `execution_input_event_id`·`source_observation_id`·`source_observation_call_id`, 지원의 `before_match`를 저장 명령까지 보존합니다. |
| `FactCandidate` SET/CLEAR tagged union | canonical fact/clear 계약 | 현재 단일 모델을 목표 mutation 의미와 맞추고 null/clear 혼동을 막습니다. |
| self-contained conflict Evidence와 production `CONFLICT_CONFIRMED` 경로 | BE pending conflict/ref/TTL/CAS·Evidence resolver 계약 | 모든 conflict ref를 복원하고 simulation ref가 노출되지 않으며 확인이 원 conflict에 결합되게 합니다. |
| `NO_CHANGE`와 외부 outcome adapter | 외부 result/viewState 계약 | 현재 runtime의 세 variant와 목표 API variant가 다릅니다. |
| trigger별 선택 호출 최적화 | first-pass Procedure→Info dependency 승인 | 기본 순서는 유지하되 절차자료가 불필요한 trigger에서만 안전하게 생략할 조건을 정합니다. |
| Review rework routing 결정 | issue target/호출권한 합의 | 현재 Review Tool 계산+Graph dependency routing과 목표 Supervisor 소유 모델의 차이를 닫습니다. |
| Coordinator integration test | auth, snapshot, guardrail, persistence 함수 | Agent 내부 성공과 실제 저장 성공을 분리 검증합니다. |

## 14. BE 전달 및 회신 절차

1. AI가 `agent-tool-io-schema.md`와 이 문서를 BE에 전달합니다.
2. BE는 §4 P0 표의 각 행에 `채택 / 대안 / 제외`와 근거를 회신합니다.
3. 양측이 canonical registry와 shared DTO version을 확정합니다.
4. BE가 OpenAPI, shared DTO, migrations, ADR, contract fixture를 PR로 제공합니다.
5. AI가 §13의 runtime schema, Case/canonical procedure registry/support adapter, Kakao search/fetch와 Graph 경계를 구현합니다.
6. 양측 CI에서 같은 contract fixture와 digest vector를 실행합니다.
7. 개발용 사용자·Case로 GET/read-only 통합 smoke test를 먼저 수행합니다.
8. Guardrail·CAS·합의된 atomicity 테스트가 끝난 뒤에만 POST/PATCH persistence를 연결합니다.

BE 회신이 없거나 P0가 미확정인 항목은 AI가 임의로 추정하지 않습니다. 해당 데이터는 Agent 판단에서 제외하거나 안전 실패/확인 필요로 반환합니다.
