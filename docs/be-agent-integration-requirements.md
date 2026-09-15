# RE:BORN BE ↔ Agent 생산 연동 요구안

> 대상: BE, AI, PM
>
> 문서 역할: **BE·AI·PM이 shared 경계를 검토하고 공동 계약을 확정하기 위한 단일 전달 문서**
>
> 현재 상태: `[PROPOSED_SHARED][NOT_APPROVED][NOT_IMPLEMENTED]`
>
> 현재 `[AGREED_SHARED]`: **0개**

이 문서는 HTTP 후보, shared DTO 후보, 인증, 저장 불변식, 운영 요구사항과 승인 기준을 한곳에 정리한다. Agent 내부 모델의 규범적 설명은 [`agent-tool-io-schema.md`](./agent-tool-io-schema.md), 전체 실행 구조는 [`architecture.md`](./architecture.md), 공식 데이터 수집·크롤링·RAG 계획은 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)가 담당한다. BE는 이 문서만으로 shared 경계를 검토할 수 있어야 하며, 다른 문서의 오래된 JSON이나 물리 테이블 초안을 조합해 계약을 추정하면 안 된다.

이 문서는 **승인 전 구현 명세가 아니다.** 아래 후보와 P0 질문을 공동 확정한 뒤 BE가 생성하는 exact DTO/JSON Schema·OpenAPI·migration이 실제 구현 기준이 된다.

## 0. 상태를 읽는 법

상태는 계약, 구현, 검증의 서로 다른 축이다.

| 축 | 값 | 의미 |
|---|---|---|
| 계약 | `[CURRENT_AI]` | 현재 AI 코드 내부에서 사용하는 계약이다. shared 계약 승인을 뜻하지 않는다. |
| 계약 | `[TYPE_ONLY]` | AI 내부 타입은 존재하지만 현재 Graph의 정상 경로에서 생성·도달하지 않는다. |
| 계약 | `[DECIDED_ARCHITECTURE]` | 프로젝트가 선택한 큰 기술 방향이다. endpoint·payload·저장 세부 합의를 뜻하지 않는다. |
| 계약 | `[PROPOSED_SHARED]` | AI가 BE·PM에 제안한 경계 계약이다. 승인 전에는 확정 명세가 아니다. |
| 계약 | `[NOT_APPROVED]` | 승인자·승인일·version·PR/ADR 중 하나라도 없어 구현 기준으로 사용할 수 없다. |
| 계약 | `[AGREED_SHARED]` | 승인자, 승인일, 계약 version과 근거 PR/ADR가 기록된 항목에만 붙인다. 현재 0개다. |
| 구현 | `[NOT_IMPLEMENTED]` | 대응 BE route, adapter, repository, migration 또는 coordinator가 없다. |
| 구현 | `[IMPLEMENTED]` | 실제 코드와 변경 이력이 존재한다. |
| 검증 | `[NOT_VERIFIED]` | contract·integration test 또는 실제 환경 검증이 없다. |
| 검증 | `[TESTED]` | 자동화된 fixture/test가 통과했다. |
| 검증 | `[LIVE_OBSERVED: YYYY-MM-DD]` | 날짜와 환경이 기록된 실호출 관찰이다. 생산 연동 완료와는 다르다. |

이 문서의 명령형 문장은 전부 `[PROPOSED_SHARED][NOT_APPROVED]` 요구안이다. 승인 전에는 필드, enum, HTTP status, 저장 위치를 임의로 구현하지 않는다. 승인 뒤 규범 우선순위는 다음과 같다.

1. migration·repository·DTO 코드와 그 코드에서 생성한 JSON Schema/OpenAPI
2. 공동 contract fixture와 digest test vector
3. 승인된 ADR
4. 이 Markdown 설명

상위 산출물과 이 문서가 다르면 코드를 무조건 정답으로 간주하지 말고 계약 drift로 처리해 함께 수정한다.

## 1. 현재 사실과 생산 연동에 없는 것

| 구분 | 현재 상태 | 근거 | 해석 |
|---|---|---|---|
| Agent 내부 strict schema | `[CURRENT_AI][IMPLEMENTED][TESTED]` | `backend/app/agent/schemas.py`, `backend/tests/agent/test_schemas.py` | `agent-io/2.0` 내부 모델이 존재한다. BE shared DTO가 있다는 뜻은 아니다. |
| AgentGraph | `[CURRENT_AI][IMPLEMENTED][TESTED]` | `backend/app/agent/graph.py`, `backend/tests/agent/test_graph.py` | standalone 입력으로 세 outcome을 생성할 수 있다. 인증 Case를 읽거나 저장하지 않는다. |
| Review | `[CURRENT_AI][IMPLEMENTED][TESTED]` | `backend/app/agent/review_tool/`, 관련 tests | `ReviewSubject`와 PASS proof가 있다. DB 저장 허가는 아니다. |
| 절차 인터넷 조회 | `[CURRENT_AI][IMPLEMENTED][TESTED]` | `backend/app/agent/procedure_tool/`, 관련 tests | 공식 registry와 제한된 검색 fallback으로 실제 공식 원문을 읽는다. canonical DB step을 만들지는 않는다. |
| 기업마당 discovery adapter | `[CURRENT_AI][IMPLEMENTED][TESTED]` | `backend/app/agent/support_agent/discovery_tool.py`, 관련 tests | 미검수 공고 후보를 읽는 독립 adapter다. Graph의 검수 catalog나 BE 저장소에는 연결되지 않았다. |
| 인증된 Case snapshot adapter | `[PROPOSED_SHARED][NOT_IMPLEMENTED]` | 이 문서 §5 | 실제 사용자 Case 입력이 현재 Graph에 연결되지 않았다. |
| HTTP endpoint와 외부 DTO | `[PROPOSED_SHARED][NOT_IMPLEMENTED]` | 이 문서 §6 | route, OpenAPI와 FE 합의가 없다. |
| persistence·CAS·history | `[PROPOSED_SHARED][NOT_IMPLEMENTED]` | 이 문서 §7 | Review 결과를 실제 DB에 안전하게 반영하는 구현이 없다. |
| production conflict 확인 | `[PROPOSED_SHARED][NOT_IMPLEMENTED]` | 이 문서 §5.5 | 현재 standalone ref를 운영에서 신뢰할 수 없다. |

따라서 현재 Agent가 standalone으로 정상 실행되는 것과 BE 연동이 완료된 것은 다르다. HTTP 200, 외부 API 한 번 성공, mock test 통과도 실제 Case `read → plan → persist → read-back` 성공을 대신하지 않는다.

## 2. 소유권과 신뢰 경계

| 범위 | BE 책임 | AI 책임 | 이유 |
|---|---|---|---|
| 인증·권한 | 서비스 JWT 검증, member/Case 소유권 확인, 비인가 Case 비노출 | token·credential을 prompt로 보내지 않음 | 모델은 권한 원천이 아니다. |
| Case 입력 | 한 읽기 시점의 immutable shared snapshot 조립 | shared DTO를 내부 `CaseSnapshot`으로 strict 변환 | DB 구조와 모델 입력을 분리한다. |
| 실행 조정 | input guardrail, idempotency, deadline, Graph 호출, 저장 순서 | AgentGraph와 내부 retry·Review | 외부 호출과 DB transaction을 분리한다. |
| 절차 | canonical step registry와 progress 저장 | 공식 인터넷 원문 조회와 Info 분석 | 웹 제목이나 모델 출력이 DB identity가 되면 안 된다. |
| 지원사업 | canonical ID, 승인 metadata, match/application 저장·조회 | 공고 수집·구조화 후보와 runtime 비교 | 발견, 검수, 자격 비교, 실제 신청은 다른 행위다. |
| Evidence | 저장·resolve·보존·접근통제 | AI 생성 근거의 hash·lineage·참조 검증 | 당시 판단 근거를 재현해야 한다. |
| Review 이후 | 현재 상태 재검증, guardrail, CAS, 원자 저장 | reviewed subject와 proof 제공 | PASS는 현재 DB 상태나 권한을 증명하지 않는다. |
| 외부 HTTP | camelCase wire DTO, status와 FE view mapping | 내부 snake_case outcome | 내부 provider 모델을 외부 API로 노출하지 않는다. |

BE는 Agent 하위 구성요소를 개별 HTTP endpoint로 만들 필요가 없다. 생산 경계는 `BE Coordinator → AgentGraph` 입력·결과와 `BE Coordinator → guardrail/persistence`다.

## 3. 제안 production 흐름

```text
1. HTTP 인증과 Case 소유권 검증
2. request 형식·크기·PII input guardrail
3. clientEventId idempotency 확인
4. 한 읽기 시점에서 SharedCaseSnapshotDTO 조립
5. canonical registry/catalog와 Evidence 최소 집합 resolve
6. BE가 runId·traceId·deadline을 부여해 AgentGraph 호출
7. Agent가 trigger별 Graph를 실행
   - `CASE_CREATED | RESULT_SUBMITTED`: Procedure → Info; confirmed fact 충돌이면 Review 없이 `CONFLICT`로 종료, 충돌이 없을 때만 Support → Supervisor → Review
   - `SUPPORT_REFRESH`: Support → Supervisor → Review
8. outcome discriminator 검증
9. REVIEWED_PLAN이면 subject digest와 ReviewProof 재검증
10. 저장 직전 Case를 다시 읽고 version/field CAS와 상태 전이 검증
11. 허용된 변경·Evidence 참조·decision·history를 전부 commit하거나 전부 rollback
12. 저장 결과를 다시 읽어 external response로 projection
```

`SUPPORT_REFRESH`처럼 새 사용자 입력과 절차 해석이 없는 trigger는 합의된 조건에서 Support부터 시작할 수 있다. 외부 LLM·검색·원문 fetch는 DB transaction 밖에서 끝낸다. timeout 뒤 재시도는 같은 `clientEventId`를 유지한다.

## 4. 구현 전에 닫아야 할 P0 결정

| 결정 | 제안 기본값 | BE가 회신할 내용 | 이유 |
|---|---|---|---|
| snapshot 동시성 | Case-level 증가 version과 `expectedVersion` CAS | version 원천, 증가 시점, conflict 응답 | 실행 중 변경을 덮어쓰지 않는다. |
| idempotency | 사용자+endpoint+`clientEventId` 범위에서 같은 payload만 replay | uniqueness, 보존기간, 다른 payload 처리 | 중복 실행·이력·비용을 막는다. |
| fact 미확인·삭제 | `UNKNOWN`은 `value=null`; 명시적 삭제는 별도 operation | null/unknown/not-applicable/clear 표현 | 서로 다른 상태를 null 하나로 섞지 않는다. |
| canonical field/enum | versioned registry와 legacy mapping | v1 field 목록, enum, deprecated 값 | DB·API·Agent 간 임의 변환을 막는다. |
| Case fact 범위 | 지원 판정에 필요한 사업체 형태·건축물 용도·과거 지원 이력 등을 명시적 v1 scope로 관리 | 포함/제외 field와 각 저장 원천 | Agent 입력에는 있으나 snapshot에서 복원할 수 없는 값을 없앤다. |
| procedure registry | stable ID/code/name/alias/version | owner, 적용 조건, 변경·폐기 정책 | 웹 제목은 stable identity가 아니다. |
| progress 초기화 | Case 적용 단계 전체를 한 transaction에서 생성·검증 | 초기화 시점과 registry 변경 처리 | unique만으로 누락 row를 막을 수 없다. |
| support identity | canonical ID ↔ Wiki UUID ↔ 외부 공고 ID mapping | identity source와 revision 정책 | 같은 사업을 이름으로 연결하지 않는다. |
| support 상태 | match와 application lifecycle 분리 | 각 상태 enum과 쓰기 권한 | 조회가 신청 row를 만들면 안 된다. |
| 신청상태 쓰기 경로 | PATCH 또는 자연어 `/results` 중 하나를 authoritative 경로로 선택 | 허용 전이와 actor/audit | 두 write 경로가 상태와 idempotency를 갈라놓지 않게 한다. |
| Evidence | immutable ID, source/version/locator/hash/lineage | 저장 위치, resolver, 보존·삭제 | Review와 감사가 실제 근거를 복원해야 한다. |
| decision·Review 기록 | decision, subject digest, proof, run/trace 결합 | 보존·조회 모델 | 어떤 payload가 PASS였는지 재현한다. |
| conflict 확인 | opaque ref+digest+Case/version+TTL+single-use | ref 발급·저장·소비 방식 | client field/value 바꿔치기를 막는다. |
| outcome/API mapping | tagged union으로 변환 | `NEEDS_MORE_INFO`, no-change, failure HTTP 정책 | nullable 조합과 FE 추정을 막는다. |
| auth | Kakao OAuth 후 서비스 JWT 방향 | claim, 전달, 만료, 회전, 401/403/404 | 카카오 token과 서비스 token을 구분한다. |
| transaction | mutation·decision·history는 all-or-nothing | Evidence 선행 저장 허용 범위, 실패 정책 | 부분 저장을 막는다. |
| 개인정보 | raw input 최소 보존, prompt·trace allowlist | 암호화, 접근, 보존, 삭제, 동의 | 사업자번호·주소·사용자 발화를 보호한다. |
| timeout/retry | 하나의 전체 deadline 아래 bounded retry | gateway budget, retry owner, async 전환 기준 | 중복 실행과 긴 lock을 막는다. |
| run context 소유권 | BE가 `runId`·deadline을 주입하는 목표안 | 현재 Graph 생성 `runId`와의 전환 방식 | trace·proof·idempotency ID가 두 벌이 되는 것을 막는다. |
| runtime dependency 전달 | 한 version의 canonical step registry와 reviewed support catalog를 묶어 전달 | inline bundle 또는 권한 있는 resolver, cache·갱신·실패 정책 | version 문자열만으로는 현재 Graph를 생성할 수 없다. |
| guardrail audit | BE Coordinator가 판정하고 별도 audit record를 남김 | 판정 필드, 발급·검증 주체, 저장·보존 방식 | 정의되지 않은 proof를 persistence command에 넣지 않는다. |

각 행에는 `동의 / 수정안 / 제외`, 담당자, 결정일, ADR 또는 PR 링크를 기록한다. 결정되지 않은 값은 `UNKNOWN`, 확인 필요 또는 safe failure로 처리하며 추정 default를 만들지 않는다.

## 5. shared DTO 후보

### 5.1 공통 규칙

모든 DTO는 `[PROPOSED_SHARED][NOT_APPROVED][NOT_IMPLEMENTED]`다.

- 외부/shared JSON은 `camelCase`, Agent 내부 Python은 `snake_case`를 사용하고 adapter에서 명시적으로 변환한다.
- 모든 object는 unknown extra field를 거부하고 `schemaVersion`을 가진다.
- ID, enum, timezone 포함 datetime, nullable 여부를 schema로 고정한다.
- tagged union은 `type` 또는 `result` discriminator를 필수로 한다.
- `UNKNOWN` fact는 `value=null`이고 confirming Evidence를 갖지 않는다. `CONFIRMED` fact는 typed value와 Evidence를 갖는다.
- 빈 문자열·누락·`null`·`UNKNOWN`·`NOT_APPLICABLE`·명시적 `CLEAR`를 같은 뜻으로 변환하지 않는다.
- 모든 Evidence reference는 함께 전달된 집합 또는 권한 있는 resolver에서 해석돼야 한다.
- digest는 합의한 canonical JSON bytes와 SHA-256 test vector로 고정한다.

### 5.2 `SharedCaseSnapshotDTO`

| 필드 | 타입/필수 | 의미와 불변식 |
|---|---|---|
| `schemaVersion` | string, 필수 | shared 계약 version |
| `snapshotId` | UUID, 필수 | 이 immutable read view의 ID |
| `caseId` | positive integer, 필수 | 소유권 검증이 끝난 Case |
| `caseVersion` | positive integer, 필수 | 저장 CAS 기준 |
| `caseStatus` | canonical enum, 필수 | 현재 Case 상태 |
| `facts` | `SharedFactDTO[]`, 필수 | `fieldPath`당 최대 1개 |
| `procedureProgress` | `SharedProcedureProgressDTO[]`, 필수 | canonical `procedureStepId`당 정확히 1개인 적용 단계 projection |
| `supportMatches` | `SharedSupportMatchDTO[]`, 필수 | 자격 비교 결과; 실제 신청과 분리 |
| `supportApplications` | `SharedSupportApplicationDTO[]`, 필수 | 실제 신청 lifecycle만 표현 |
| `latestDecision` | object 또는 null, 필수 | 같은 `caseVersion`에서 저장된 마지막 reviewed decision |
| `historyWindow` | bounded object[], 필수 | 선택 정책과 잘림 여부를 포함; raw input 기본 제외 |
| `evidenceRecords` | `EvidenceDTO[]`, 필수 | snapshot 참조의 닫힌 최소 집합 |
| `capturedAt` | aware datetime, 필수 | 읽기 시점 |

`SharedFactDTO`는 `fieldPath`, `valueType`, `value`, `status`, `evidenceRefs`, `updatedAt`을 가진다. `SharedProcedureProgressDTO`는 canonical `procedureStepId`, `stepCode`, registry version, status, Evidence와 갱신 시각을 가진다. AI adapter는 누락값, Evidence 또는 procedure row를 합성하지 않는다.

`[CURRENT_AI]` 내부 `CaseSnapshot`은 현재 `snapshot_id`, `case_id`, nullable `case_version`, `case_status`, `facts`, `procedure_progress`, `evidence_records`, `captured_at`의 8개 필드만 받는다. 위 shared 후보의 required version, support, latest decision과 history 영역은 현재 모델에 자동 입력되지 않는다. 계약 승인 후 AI가 별도 adapter와 필요한 내부 schema 확장을 구현해야 하며, BE가 확장 필드를 보내는 것만으로 연동되지는 않는다.

### 5.3 `EvidenceDTO`

| 필드 | 의미 |
|---|---|
| `evidenceId` | 전역 또는 합의 범위에서 불변인 ID |
| `sourceType`, `sourceRef`, `sourceVersion` | 출처 종류·식별자·revision |
| `locator`, `excerpt` | 원문 내 위치와 최소 인용 범위 |
| `parentEvidenceRefs` | 파생 근거 lineage |
| `publishedAt`, `retrievedAt`, `freshnessStatus` | 시점과 최신성 |
| `contentHash` | 원문/정규화 규칙에 따른 무결성 값 |

같은 `evidenceId`의 내용과 hash는 바뀌지 않는다. 외부 검색 snippet은 Evidence가 아니며, allowlist를 통과해 직접 fetch한 공식 원문만 공식 Evidence 후보가 된다.

### 5.4 invocation과 outcome

`AgentInvocationDTO` 후보:

| 필드 | 의미 |
|---|---|
| `schemaVersion`, `runId`, `traceId` | 계약과 관측 연결 |
| `clientEventId` | 요청 idempotency |
| `deadlineAt` | 전체 실행 상한 |
| `trigger` | `CASE_CREATED \| RESULT_SUBMITTED \| SUPPORT_REFRESH` tagged union |
| `snapshot` | `SharedCaseSnapshotDTO` |
| `runtimeDependencies` | `RuntimeDependencyBundleDTO`; Graph 생성에 필요한 canonical step과 reviewed catalog |

`[CURRENT_AI]` Graph는 현재 `runId`를 내부에서 만들고 optional `traceId`만 외부에서 받으며, trigger의 `clientEventId`를 DB idempotency로 처리하지 않는다. 따라서 위 invocation envelope는 현재 callable의 별칭이 아니다. P0에서 ID·deadline 소유권을 정한 뒤 AI entrypoint와 BE Coordinator를 함께 맞춰야 한다.

자연어 trigger의 `input` 후보는 `inputEventId`, `sourceType`, `redactedText`, placeholder와 Unicode code-point offset을 가진 `redactions[]`, `submittedAt`을 포함한다. raw text와 credential은 포함하지 않는다. `SUPPORT_REFRESH`는 자연어 대신 canonical support program ref 목록과 `asOf`를 받는다.

`RuntimeDependencyBundleDTO` 후보는 version 문자열만이 아니라 현재 Graph가 실제로 소비할 데이터를 함께 제공한다.

| 필드 | 필수 내용 |
|---|---|
| `procedureRegistryVersion` | 한 실행에 고정한 registry version |
| `knownProcedureSteps` | `procedureStepId`, `stepCode`, `stepName`, `utteranceAliases[]`를 가진 canonical step 목록 |
| `supportCatalogVersion` | 한 실행에 고정한 reviewed catalog version |
| `reviewedSupportPrograms` | canonical support ID·Wiki UUID, 이름, related steps, criteria, required documents, 신청 channel/URL/period, source version, freshness, Evidence refs |
| `supportEvidenceRecords` | catalog가 참조하는 Evidence의 닫힌 집합 |

각 criterion은 `criterionCode`, canonical `fieldPath`, `operator`, typed `requiredValues`, `evidenceRefs`를 포함한다. required document와 신청 정보도 원문 `evidenceRefs`를 가진다. `knownProcedureSteps`는 `AgentGraph(... known_procedure_steps=...)`, reviewed catalog는 `SupportAgent(... catalog=...)`로 strict 변환된다. **version만 보내고 항목을 생략해서는 실행할 수 없다.**

제안 기본값은 BE Coordinator가 권한 있는 shared resolver로 한 version의 전체 bundle을 조립해 in-process AI adapter에 전달하는 방식이다. inline 전달과 AI가 version으로 trusted resolver를 호출하는 방식 중 무엇을 쓸지는 P0에서 확정하며, 어느 방식이든 미검수 raw discovery 결과를 이 bundle에 넣지 않는다.

현재 AI 내부 `AgentRunOutcome`은 정확히 다음 세 variant다.

| 내부 outcome | 필수 내용 | 외부 mapping 후보 |
|---|---|---|
| `REVIEWED_PLAN` | 수정 불가능한 `ReviewSubject`와 matching `ReviewProof` | decision에 따라 `UPDATED` 또는 `NEEDS_MORE_INFO` |
| `CONFLICT` | Case/snapshot/version에 묶인 conflict 후보 | `CONFLICT`와 server-issued 확인 ref |
| `SAFE_FAILURE` | failure code, retryable, recovery action, trace | `FAILED` 또는 합의한 오류 envelope |

BE가 검증·저장 경계에서 소비할 camelCase projection 후보는 다음과 같다. 이름이 같은 `[CURRENT_AI]` 내부 type을 wire format으로 직접 노출한다는 뜻은 아니다.

| payload | 필수 의미 |
|---|---|
| `ReviewSubjectDTO` | `reviewSubjectId`, `reviewAttempt`, `runId`, `caseId`, trigger, snapshot, source result+digest 집합, supervisor draft, `subjectDigest` |
| `ReviewProofDTO` | review call/run/Case/snapshot ID, Case version, subject ID/digest, `verdict=PASS`, `reviewedAt` |
| `DecisionDTO` | `decisionType` discriminator, draft ID/version, summary, human-confirmation 여부, Evidence와 source call IDs; `ACTION`은 blocker+next action, `NEEDS_MORE_INFO`는 blocker+질문 |
| `MutationSetDTO` | fact SET/CLEAR, forward-only procedure progress, support match, optional Case status 후보 목록; candidate ID와 before/proposed 상태 포함 |
| `ConflictDTO` | opaque ref, candidate/digest, snapshot/version, canonical field, committed/proposed typed 상태, Evidence와 source call ID |
| `SafeFailureDTO` | run/Case/snapshot/version, failure/message/recovery code, retryable, failed component, trace ID |

`ReviewSubjectDTO.subjectDigest`는 subject 전체의 canonical bytes를 고정하고 `ReviewProofDTO`는 같은 run/Case/snapshot/version/subject/digest에만 유효하다. `MutationSetDTO`를 저장 전에 수정·필터링하면 기존 proof는 무효다.

`CASE_COMPLETE`는 내부 type만 존재하고 authoritative procedure coverage가 없어 현재 성공 경로에서 거부된다. `NO_CHANGE`도 현재 runtime outcome이 아니다. 둘을 외부 계약에 활성화하려면 별도 acceptance와 mapping 승인이 필요하다.

### 5.5 저장·충돌 확인 DTO

`PersistReviewedPlanCommand` 후보는 다음을 포함한다.

- `caseId`, `expectedCaseVersion`, `clientEventId`, `runId`
- 변경 불가능한 `reviewSubject`, `reviewProof`
- 전체 `MutationSet`; 일부만 선택해 저장할 수 없음
- 새 Evidence와 기존 Evidence reference

Output/State Transition Guardrail의 판정은 BE Coordinator가 command를 받기 전과 저장 직전에 수행한다. audit 필드나 별도 proof DTO는 §4 P0에서 구조와 발급·검증 주체를 정하기 전까지 이 command의 확정 필드가 아니다.

`PersistResult`는 `APPLIED | NO_CHANGE | VERSION_CONFLICT | REJECTED` tagged union 후보이며, `APPLIED`일 때 새 Case version과 read-back 식별자를 반환한다. 여기의 persistence `NO_CHANGE`는 현재 Agent outcome `NO_CHANGE`가 있다는 뜻이 아니다.

`ConflictConfirmationRequest` 후보는 `conflictRef`, `confirmation=CONFIRM_ORIGINAL`, `expectedVersion`, `clientEventId`만 받는다. client가 원 후보의 field/value를 다시 보내거나 수정할 수 없다. 서버는 opaque ref로 원 candidate, subject digest, Case ID/version, owner를 복원하고 TTL·single-use·CAS를 검증해야 한다. `standalone:` ref는 운영 HTTP에 노출하지 않는다.

그 뒤 확인된 후보를 새 Graph run과 Review에 넣는 경로는 `[TYPE_ONLY][NOT_IMPLEMENTED]`다. 현재 `CONFIRMED_CONFLICT` fact-change 타입만 있고 이를 만드는 trigger, Graph node, BE→AI adapter는 없다. 생산 confirm endpoint를 열기 전에 AI가 이 세 경로와 Review 회귀 테스트를 구현하고 shared 계약으로 승인받아야 한다.

### 5.6 지원사업 DTO 분리

| DTO | 표현하는 것 | 포함하면 안 되는 것 |
|---|---|---|
| `SharedSupportMatchDTO` | Case와 canonical support program 간 `POSSIBLY_RELEVANT \| NEEDS_CONFIRMATION \| NOT_RELEVANT \| STALE \| UNVERIFIABLE` 및 Evidence/version | 실제 신청 완료 상태 |
| `SharedSupportApplicationDTO` | 사용자가 실제 수행한 `NOT_STARTED \| APPLIED \| SUPPLEMENT_REQUIRED \| RESUBMITTED \| APPROVED \| REJECTED` lifecycle | Agent가 계산한 자격 확정 |

공고 조회 또는 subsidies GET은 application row를 만들지 않는다. 미검수 discovery candidate를 trusted catalog나 match로 자동 승격하지 않는다.

## 6. 외부 HTTP와 인증 후보

### 6.1 endpoint 목록

전부 `[PROPOSED_SHARED][NOT_APPROVED][NOT_IMPLEMENTED]`다. 별도 `/replan` endpoint는 만들지 않고 `/results` 처리 안에서 재계획하는 안이다.

| Method | Path | 목적 | Agent 호출/쓰기 |
|---|---|---|---|
| `GET` | `/auth/kakao/login` | 카카오 로그인 시작 | 없음 |
| `GET` | `/auth/kakao/callback` | OAuth callback과 서비스 session/token 발급 | 인증 쓰기 가능 |
| `POST` | `/cases` | Case 생성, progress 초기화, 최초 계획 | Graph 호출, 저장 |
| `GET` | `/cases/{caseId}` | current Case projection | 기본적으로 Agent 호출·쓰기 없음 |
| `POST` | `/cases/{caseId}/results` | 자연어 결과 입력, 재계획, 검증, 저장 | Graph 호출, 저장 |
| `POST` | `/cases/{caseId}/results/confirm` | 원 conflict에 대한 사용자 확인 | Graph 호출, CAS 저장 |
| `GET` | `/cases/{caseId}/subsidies` | match와 application 분리 조회 | 조회만으로 쓰기 없음 |
| `PATCH` | `/subsidy-applications/{applicationId}` | 실제 신청 lifecycle 변경 | Agent 호출 없음; 명시적 쓰기 |
| `GET` | `/cases/{caseId}/history` | bounded decision/change history | Agent 호출·쓰기 없음; MVP 후순위 가능 |

`POST /cases/{caseId}/results` request 후보는 `rawInput`, `expectedVersion`, `clientEventId`를 갖는다. canonical procedure 대상은 서버 snapshot과 registry로 판단하며 client가 임의 DB step ID를 주입하지 않는다. 외부 response는 `result` discriminator, `caseVersion`, 변경 요약, decision/view state, Evidence reference를 포함하는 후보이며 내부 snake_case 객체를 그대로 직렬화하지 않는다.

### 6.2 `[DECIDED_ARCHITECTURE]` 인증 방향 / `[PROPOSED_SHARED]` 세부 계약

큰 방향은 카카오 OAuth로 사용자를 식별하고 RE:BORN 서버가 발급한 서비스 JWT로 이후 요청을 인증하는 것이다. 카카오 access/refresh token과 서비스 JWT access/refresh token은 다른 credential이다. claim, 쿠키/본문 전달, 만료, refresh rotation, 저장 위치와 401/403/404 비노출 정책은 P0 승인 전이다.

Case route는 항상 BE가 token과 Case owner를 검증한 뒤 snapshot을 조립한다. 소유권 검증 실패 응답은 Case 존재 여부를 누출하지 않는 한 가지 정책으로 통일한다.

### 6.3 outcome과 HTTP 오류

아래는 결정용 후보이며 확정 status code가 아니다.

| 상황 | body discriminator | HTTP 후보 | 규칙 |
|---|---|---:|---|
| reviewed 변경 저장 성공 | `UPDATED` | 200 | read-back version 포함 |
| 추가 확인 질문 | `NEEDS_MORE_INFO` | 200 | 저장 가능한 변경과 질문 동시 처리 우선순위 결정 필요 |
| 사용자 확인이 필요한 conflict | `CONFLICT` | 200 또는 409 | opaque ref만 노출 |
| stale snapshot | `VERSION_CONFLICT` | 409 | 아무 업무 변경도 저장하지 않음 |
| 중복 동일 event | 원 응답 replay | 원 status | 새 Graph run/history를 만들지 않음 |
| 잘못된 요청 | 오류 code | 400 또는 422 | Agent 호출 전 차단 |
| 인증 실패 | 오류 code | 401 | token 값은 log에 남기지 않음 |
| 권한 없음/Case 없음 | 비노출 오류 | 404 후보 | 존재 여부 보호 |
| provider/Review 실패 | `SAFE_FAILURE` mapping | 200 또는 5xx | retryable과 recovery action 보존 |

## 7. persistence 논리 요구사항

이 절은 **논리 불변식**이며 물리 테이블·컬럼·ORM·DDL을 제안하지 않는다. BE가 기술 스택과 현재 데이터에 맞는 data dictionary와 migration으로 구현안을 제시해야 한다.

1. 핵심 업무 aggregate의 논리명은 `CASES`로 사용한다. `CASE`는 MySQL keyword와 충돌할 수 있으므로 새 schema·query·문서에서 사용하지 않는다. 정확한 물리 rename 절차는 BE migration에서 정한다.
2. Case의 변경 가능한 상태에는 단조 증가하는 version 또는 동등하게 강한 field-level CAS가 있어야 한다. 저장은 snapshot의 `expectedCaseVersion`과 현재 상태가 일치할 때만 성공한다.
3. Case별 canonical procedure step의 current progress는 `(caseId, procedureStepId)`당 **최대 1개**여야 한다. DB unique constraint 또는 동등한 강제 수단이 필요하다.
4. 최대 1개만으로는 **적용 단계마다 정확히 1개**를 보장하지 못한다. Case 생성 또는 registry 적용 transaction에서 적용 단계 집합을 고정하고 전부 초기화한 뒤 예상 개수와 실제 개수를 검증하며, 하나라도 실패하면 Case/progress 초기화를 전부 rollback한다.
5. current progress와 progress history는 분리한다. current는 덮어쓰되 상태 변경마다 append-only history를 남긴다. 인터넷 조회 결과는 progress identity나 row 존재를 만들지 않는다.
6. Case field history는 Review·guardrail 뒤 **실제로 반영된 변경만** before/after, canonical field, source, reason, resulting Case version과 함께 append한다. 후보, stale write, no-op, rollback은 history를 남기지 않는다.
7. mutation, Case version 증가, procedure/support 상태, decision, history와 필수 Evidence reference는 합의한 하나의 atomic boundary에서 전부 성공하거나 전부 실패한다. Evidence blob의 선행 idempotent 저장을 허용할지는 ADR로 정하되 dangling reference는 금지한다.
8. history는 수정·삭제할 수 없는 감사 기록이어야 한다. raw 사용자 입력, token, 사업자등록번호 같은 원문 PII를 field history에 복제하지 않는다.
9. canonical procedure registry는 stable `procedureStepId`, `stepCode`, 표시명, alias, registry version과 폐기 mapping을 제공한다. 웹 문서 제목, 검색 결과 순서나 LLM 출력으로 새 ID·row를 생성하지 않는다.
10. canonical support identity는 외부 공고 ID, 내부 support ID와 Wiki/catalog revision을 안정적으로 연결한다. support match와 실제 application lifecycle은 별도 상태와 쓰기 경로를 가진다.
11. `UNKNOWN` fact는 `value=null`; `CONFIRMED` fact는 typed value와 Evidence를 갖는다. row 누락을 임의로 `UNKNOWN` 또는 `NOT_STARTED`로 보정하지 않는다.
12. current view의 progress와 latest decision은 같은 Case/version projection이어야 한다. `RESTORATION_CHECK=COMPLETED`이면 latest blocker가 “원상복구 범위가 아직 확인되지 않음”이라고 주장할 수 없다. 새로 확인할 철거 지원조건이 있다면 별도의 canonical blocker/target과 근거를 가리켜야 한다.
13. conflict confirmation은 저장된 원 candidate digest와 Case/version에 대한 CAS가 성공할 때만 처리한다. 변조·만료·다른 Case·이미 소비된 ref는 아무 변경 없이 거부한다.

## 8. 데이터·조회 운영 경계

- 폐업 절차 **내용**은 AI의 ProcedureLookupTool이 공식기관 인터넷 원문에서 조회한다. BE가 절차 본문을 작성하는 master API를 만들 필요는 없다.
- BE는 절차 내용이 아니라 canonical step identity, Case progress와 Evidence 저장·resolver를 제공한다.
- 검색 provider 결과는 URL 발견 수단일 뿐 Evidence가 아니다. 공식 domain allowlist, HTTPS, redirect·DNS/SSRF, MIME, byte, timeout 제한을 통과해 직접 읽은 원문만 Evidence 후보가 된다.
- 공식 registry miss에서만 승인된 provider fallback을 쓰고 provider attempt, URL, fetch 결과, hash와 최신성을 trace한다.
- 기업마당 API 응답은 discovery input이다. 원문 보존·hash → external/canonical ID mapping → 조건·서류 구조화 → 공식 첨부 교차검증 → 담당자 또는 승인된 deterministic rule 검수 → immutable catalog version 발행 뒤에만 Support Agent의 trusted input이 된다.
- API로 제공되지 않는 자료의 crawling/RAG는 AI 구현 계획에 포함하되 robots/이용조건, 증분수집, chunk lineage, freshness, 삭제와 재색인 기준을 먼저 승인한다. “미구현” 표시는 포기가 아니라 현재 상태이며 milestone과 acceptance를 가진 목표여야 한다.

상세 provider 우선순위, 실제 API 관찰과 crawling/RAG milestone은 `agent-official-data-source-strategy.md`를 따른다.

## 9. 보안·PII·trace·비용·재시도

| 항목 | 최소 요구사항 | 검증 방법 |
|---|---|---|
| 인증정보 | OAuth/JWT/API key를 prompt, error body, 일반 log에 기록하지 않음 | secret pattern test와 log inspection |
| 사용자 원문 | 입력 ID와 redacted text를 분리하고 최소 전달·최소 보존 | PII fixture로 prompt/trace 검증 |
| 사업자 식별정보 | 권한 있는 deterministic resolver에만 전달, 암호화·마스킹·외부전송 audit | 타 사용자·일반 Agent 접근 부정 테스트 |
| Evidence | 접근권한, source hash, lineage, 보존·삭제 정책 | 모든 ref resolve 및 변조 검출 test |
| trace | `runId`, `traceId`, component call, retry, duration, outcome만 연결 | Case 간 trace 혼선 부정 테스트 |
| 비용 | 모델/provider, prompt/completion token 집계와 retry 횟수 수집; 원문 미수집 | telemetry schema test |
| idempotency | 동일 key+payload는 원 결과 replay, 동일 key+다른 payload는 거부 | 동시·재전송 test |
| deadline | 전체 deadline 안에서 component budget과 bounded retry; 취소 정책 명시 | timeout/fault injection |
| 외부 fetch | official allowlist, DNS/private IP 차단, redirect 재검증, 크기·MIME·시간 상한 | SSRF·redirect·대용량 fixture |

Langfuse 등 특정 관측 제품은 이 계약의 필수조건이 아니다. 제품을 선택해도 raw prompt·PII·credential을 수집하지 않고 위 trace/cost 의미를 만족해야 한다.

## 10. BE 산출물

P0 합의 뒤 BE PR에는 다음이 함께 있어야 한다.

| 산출물 | 최소 내용 | 완료 기준 |
|---|---|---|
| shared DTO 코드 | version, required/nullable, enum, tagged union, adapters | AI와 같은 fixture를 양방향 검증 |
| 생성 OpenAPI | §6 endpoint, auth, response/error union, examples | CI에서 drift 검출, examples schema 통과 |
| canonical registry | Case field/enum, procedure ID/code/alias/version, support identity | unknown/deprecated mapping test |
| migration/data dictionary | BE가 정한 실제 구조, 제약, index, rollback | 기존 데이터 보존과 apply/rollback test |
| snapshot assembler | 권한 검증 후 한 시점의 `SharedCaseSnapshotDTO` | AI strict adapter와 contract test |
| coordinator | idempotency, deadline, Graph 호출, guardrail, persistence 순서 | duplicate/timeout/retry test |
| persistence service | CAS, all-or-nothing mutation/decision/history, read-back | concurrency/fault-injection test |
| Evidence resolver | source별 저장, hash, lineage, 권한, 보존 | 모든 ref resolve와 변조 부정 test |
| conflict store/ref service | opaque ref, digest, owner, version, TTL, single-use | 변조·만료·replay·stale test |
| 운영 ADR/runbook | auth, transaction, 개인정보, 외부 egress, timeout, 장애·rollback | 개발자가 secret 없이 절차를 재현 |

## 11. 공동 acceptance checklist

다음이 모두 통과해야 “BE와 Agent가 실제 Case로 정상 연동된다”고 말할 수 있다.

- [ ] 다른 사용자의 Case read/write가 동일한 비노출 정책으로 거부된다.
- [ ] 하나의 read point에서 만든 snapshot이 shared schema와 AI adapter를 통과한다.
- [ ] 적용 canonical procedure step마다 progress가 정확히 1개이며 동시 생성·retry·부분 실패에서도 유지된다.
- [ ] `RESTORATION_CHECK=COMPLETED` fixture가 같은 미확인을 latest blocker로 반환하지 않는다.
- [ ] web title이나 LLM 문자열로 procedure ID/progress row를 만들 수 없다.
- [ ] support match 조회가 application row를 생성·변경하지 않는다.
- [ ] 모든 confirmed fact, completed progress와 grounded claim의 Evidence가 resolve된다.
- [ ] Review subject 변경 또는 proof/digest 불일치가 저장 전에 거부된다.
- [ ] stale snapshot은 `VERSION_CONFLICT`이고 mutation·decision·history가 하나도 남지 않는다.
- [ ] 성공 시에만 Case version이 증가하며 실제 변경마다 append-only field history가 남는다.
- [ ] 한 mutation 실패 시 같은 계획의 나머지 변경도 저장되지 않는다.
- [ ] 같은 `clientEventId` 재전송은 Graph 실행·history·과금을 중복시키지 않는다.
- [ ] conflict ref의 변조·만료·다른 Case·single-use replay가 거부된다.
- [ ] 공식 원문이 아닌 검색 snippet은 Evidence로 승인되지 않는다.
- [ ] 미검수 기업마당 candidate가 trusted support catalog로 자동 승격되지 않는다.
- [ ] provider/Review timeout은 기존 결정을 새 결과처럼 반환하지 않고 safe failure가 된다.
- [ ] 저장 후 read-back snapshot이 persisted result와 같은 Case/version 값을 가진다.
- [ ] token, API key, raw PII와 실제 주소가 일반 log·trace에 남지 않는다.
- [ ] 실제 개발 사용자·Case로 `read → plan → review → guardrail → persist → read-back` 통합 test가 통과한다.

## 12. 승인과 변경 절차

1. BE·AI·PM은 §4 P0 각 행에 결정과 근거를 기록한다.
2. BE와 AI가 shared DTO version, canonical registry와 contract fixture를 함께 승인한다.
3. BE가 OpenAPI, migration, coordinator/persistence 구현과 ADR를 PR로 제출한다.
4. AI가 shared adapter와 필요한 runtime schema 확장을 별도 PR로 제출한다.
5. 양측 CI에서 같은 contract fixture와 digest vector를 실행한다.
6. 개발 Case로 read-only smoke를 먼저 통과한 뒤 쓰기 통합 test를 연다.
7. §11을 모두 충족한 version에만 `[AGREED_SHARED][IMPLEMENTED][TESTED]`를 붙인다.

승인 기록 표:

| Contract version | 상태 | 승인자(AI/BE/PM) | 승인일 | PR/ADR | 비고 |
|---|---|---|---|---|---|
| 미정 | `[PROPOSED_SHARED][NOT_APPROVED]` | 없음 | 없음 | 없음 | 현재 공동 승인 0개 |

## 13. 근거와 출처

| 근거 | 이 문서에 반영한 내용 |
|---|---|
| `backend/app/agent/schemas.py` | 현재 `CaseSnapshot`, `EvidenceRecord`, `MutationSet`, `ReviewSubject`, `ReviewProof`, 세 가지 `AgentRunOutcome`과 strict invariant |
| `backend/app/agent/graph.py`, `backend/tests/agent/test_graph.py` | 현재 Graph 실행 순서, retry/Review와 standalone outcome 범위 |
| `backend/app/agent/procedure_tool/`, 관련 tests | 공식 원문 조회, discovery와 Evidence의 구분, 안전한 fetch 필요성 |
| `backend/app/agent/support_agent/`, 관련 tests | support analysis와 기업마당 discovery adapter의 현재 분리 상태 |
| `backend/app/agent/review_tool/`, 관련 tests | Review subject/digest/proof 무결성과 PASS 조건 |
| `backend/CLAUDE.md` | Agent의 DB 직접 접근 금지와 shared function 경계 |
| `docs/architecture.md` | Coordinator, Guardrail, persistence를 포함한 목표 생산 흐름 |
| `docs/agent-tool-io-schema.md` | AI 내부 Agent·Tool별 정확한 current 입출력 계약 |
| `docs/agent-official-data-source-strategy.md` | 공식 API 관찰, 검색·크롤링·RAG의 상태와 구현 계획 |
| DB 리뷰 피드백 | `CASES` 명명, progress cardinality, Case field history, 완료 progress와 blocker 정합성 요구 |

이 문서가 확정하는 것은 **구현 방향이 아니라 검토할 단일 계약안**이다. 승인 전 공동 계약은 0개이며, 실제 BE migration·OpenAPI·통합 test가 생기기 전에는 생산 연동 완료로 보고하지 않는다.
