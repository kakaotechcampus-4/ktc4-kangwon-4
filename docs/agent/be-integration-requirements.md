# RE:BORN Agent 외부 연동 공동 검토 요청서

> 대상: BE, AI, PM
>
> 현재 상태: **공동 계약 미승인 · BE 연동 미구현**
>
> Agent 외부 연동에 공동 확정된 DTO, endpoint, persistence mapping: **0개**

> 기준일: 2026-09-19 · 지금 바로 막고 있는 요청만 추린 것은 [`be-requests.md`](./be-requests.md)

## 먼저 읽어주세요

현재 AI에는 standalone Agent 코어와 AI 내부 schema가 있습니다. 하지만 실제 사용자 Case를 읽고 Agent 결과를 DB에 저장하는 BE 연동은 아직 없습니다.

이 문서는 BE에 전달할 **요청서이자 공동 검토안**입니다. 바로 구현해야 하는 확정 명세가 아닙니다.

`develop`에는 DB 팀의 현재 설계 문서인 [`../schema/schema_table.md`](../schema/schema_table.md)와 [`schema/ERD.png`](../schema/ERD.png)가 있습니다. 이 요청서는 해당 설계를 폐기하거나 대신하지 않습니다. DB 설계와 AI 내부 schema 사이의 이름·enum·version 차이를 실제 연동 전에 함께 닫기 위한 문서입니다.

### BE에게 요청하는 것

1. §4의 `구현 전에 닫아야 할 P0 결정`마다 `동의 / 수정안 / 제외`로 회신해 주세요.
2. 공동 결정 후 exact DTO·JSON Schema, OpenAPI, DB migration을 BE 기술 스택에 맞게 제시해 주세요.
3. Case snapshot 조립, Agent 호출, CAS 저장, Evidence 조회를 담당할 BE coordinator·persistence 경계를 구현해 주세요.
4. AI와 같은 contract fixture를 사용해 `Case 조회 → Agent 실행 → Review → 저장 → 재조회`를 통합 검증해 주세요.

### 이 문서의 사용 방법

- AI의 내부 JSON과 DB 설계 문서를 임의로 조합해 외부 연동 계약을 추정하지 맙니다.
- 먼저 핵심 결정을 합의한 뒤, BE가 생성한 DTO·OpenAPI·migration을 실제 구현 기준으로 삼습니다.
- AI 내부 schema의 상세는 [`tool-io-schema.md`](./tool-io-schema.md), AI 실행 구조는 [`architecture.md`](../architecture.md)에서 확인합니다.
- DB 팀의 현재 설계는 [`../schema/schema_table.md`](../schema/schema_table.md)와 [`schema/ERD.png`](../schema/ERD.png)에서 확인합니다.
- 공식 데이터, 크롤링, RAG 계획은 [`official-data-sources.md`](./official-data-sources.md)에서 확인합니다.

## 0. 이 문서의 상태

### 이미 구현된 것

- AI 내부 Agent·Tool schema와 standalone 실행기
- Supervisor 초안과 Review 검수
- 공식 폐업 절차 원문 제한 조회
- 기업마당 raw 공고를 독립적으로 조회하는 adapter

위 기능은 AI 내부 코드와 테스트가 있다는 뜻이다. 외부 HTTP·DB 계약이 승인됐다는 뜻은 아니다.

### 이 문서에서 제안하는 것

- 실제 Case를 Agent 입력으로 만드는 공통 DTO
- 실행 요청·결과의 외부 API 형태
- Case version, 중복 요청 방지와 저장 순서
- Evidence 저장·조회와 conflict 확인 방식

위 내용은 모두 **공동 검토 제안**이다. 아직 승인되거나 구현되지 않았다.

### 아직 공동 확정된 계약

Agent 외부 연동용 shared DTO, endpoint와 persistence mapping은 현재 **0개**다. DB 설계 문서가 `develop`에 병합된 사실과, AI가 그 DB를 읽고 쓰는 연동 계약이 확정된 것은 서로 다른 상태다. 승인자, 승인일, 계약 version과 근거 PR 또는 ADR이 모두 기록돼야 공동 확정으로 본다.

특정 날짜에 외부 API 호출을 성공한 기록은 해당 원천에 접근할 수 있었다는 뜻일 뿐, 실제 Case 연동 완료를 뜻하지 않는다.

이 문서의 명령형 문장은 승인 전 요청안이다. 합의 전에 field, enum, HTTP status와 저장 위치를 확정된 값처럼 구현하지 않는다.

승인 후 규범 우선순위는 다음과 같습니다.

1. migration·repository·DTO 코드와 그 코드에서 생성한 JSON Schema/OpenAPI
2. 공동 contract fixture와 digest test vector
3. 승인된 ADR
4. 이 Markdown 설명

상위 산출물과 이 문서가 다르면 코드를 무조건 정답으로 간주하지 말고 계약 drift로 처리해 함께 수정한다.

## 1. 현재 사실과 생산 연동에 없는 것

### AI에 구현되고 테스트까지 끝난 기능

- **AI 내부 schema와 검증 규칙**
  - 근거: `backend/app/agent/schemas.py`, `backend/tests/agent/test_schemas.py`
  - 의미: `agent-io/2.0` 내부 모델이 있습니다. 외부 연동용 공통 DTO가 있다는 뜻은 아닙니다.

- **AgentGraph**
  - 근거: `backend/app/agent/graph.py`, `backend/tests/agent/test_graph.py`
  - 의미: standalone 입력으로 세 가지 최종 결과를 생성합니다. 인증된 Case를 읽거나 DB에 저장하지는 않습니다.

- **Review**
  - 근거: `backend/app/agent/review_tool/`와 관련 test
  - 의미: Review Tool은 `ReviewSubject`를 검수해 `ReviewResult`를 반환합니다. 실행기는 같은 대상에 대한 정확한 `PASS`를 확인한 뒤 `ReviewProof`를 생성합니다. `PASS`와 `ReviewProof`는 DB 저장 허가가 아닙니다.

- **절차 인터넷 조회**
  - 근거: `backend/app/agent/procedure_tool/`와 관련 test
  - 의미: 공식 registry와 제한된 검색 fallback으로 공식 원문을 읽습니다. canonical DB step을 만들지는 않습니다.

- **기업마당 discovery adapter**
  - 근거: `backend/app/agent/support_agent/discovery_tool.py`와 관련 test
  - 의미: 미검수 공고 후보를 읽는 독립 adapter입니다. Graph의 reviewed catalog나 BE 저장소에는 연결되지 않았습니다.

### BE 연동에 아직 없는 기능

- **인증된 Case snapshot adapter**
  - 상태: 제안 단계이며 미구현
  - 영향: 실제 사용자 Case가 현재 Graph 입력으로 연결되지 않았습니다.

- **HTTP endpoint와 외부 DTO**
  - 상태: 제안 단계이며 미구현
  - 영향: route, OpenAPI, FE 응답 계약이 아직 없습니다.

- **Persistence, CAS, history**
  - 상태: 제안 단계이며 미구현
  - 영향: Review 결과를 실제 DB에 안전하게 반영하는 구현이 아직 없습니다.

- **운영용 conflict 확인**
  - 상태: 제안 단계이며 미구현
  - 영향: 현재 standalone ref를 운영에서 신뢰할 수 없습니다.

따라서 standalone 성공과 BE 연동 완료는 다른 상태입니다. HTTP 200, 외부 API 1회 성공, mock test 통과는 실제 Case의 `read → plan → persist → read-back` 성공을 대신하지 않습니다.

## 2. 소유권과 신뢰 경계

이 절은 책임을 확정하는 명세가 아니라, 공동 검토를 시작하기 위한 제안이다.

### 인증과 권한

- **외부 서비스 경계:** 서비스 JWT, 사용자와 Case 소유권을 확인하고 권한 없는 Case를 노출하지 않는다.
- **AI 경계:** token과 credential을 LLM prompt에 보내지 않는다.
- **이유:** 모델은 인증과 권한의 판단 원천이 될 수 없다.

### Case 입력

- **외부 서비스 경계:** 한 번의 읽기 시점에서 Case snapshot을 조립한다.
- **AI 경계:** 공동 DTO를 내부 `CaseSnapshot`으로 엄격하게 변환한다.
- **이유:** DB 구조를 그대로 LLM 입력으로 노출하지 않고 한 실행의 기준 상태를 고정해야 한다.

### 실행과 저장 순서

- **외부 서비스 경계:** 입력 검증, 중복 요청 방지, 전체 제한 시간, Agent 호출과 저장 순서를 관리한다.
- **AI 경계:** `AgentGraph` 실행, 내부 재시도와 Review를 담당한다.
- **이유:** 오래 걸리는 외부 호출을 DB transaction과 분리해야 한다.

### 폐업 절차

- **외부 서비스 경계:** 공식 절차 단계 ID와 Case별 현재 진행 상태를 저장한다.
- **AI 경계:** 공식기관 원문을 조회하고 Case 문맥에서 의미를 분석한다.
- **이유:** 웹 제목이나 LLM 문장이 DB의 절차 ID가 되면 안 된다.

### 지원사업

- **외부 서비스 경계:** 안정적인 지원사업 ID와 실제 신청 상태를 저장·조회한다.
- **AI 경계:** 공고 후보 수집·구조화와 검수 catalog 기반 비교를 담당한다.
- **이유:** 공고 발견, 검수, 조건 비교와 실제 신청은 서로 다른 행위다.

### Evidence

- **외부 서비스 경계:** Evidence 저장·조회, 보존과 접근 권한을 관리한다.
- **AI 경계:** 근거의 hash, 계보와 참조가 닫혀 있는지 검증한다.
- **이유:** 당시 판단에 사용한 실제 근거를 나중에도 복원할 수 있어야 한다.

### Review 이후

- **외부 서비스 경계:** 저장 직전 Case 상태, 권한과 version을 다시 확인하고 한 transaction으로 저장한다.
- **AI 경계:** Review한 대상과 일치하는 proof를 제공한다.
- **이유:** Review `PASS`만으로 현재 DB 상태와 저장 권한까지 증명되지는 않는다.

### 외부 HTTP 응답

- **외부 서비스 경계:** 외부 `camelCase` DTO, HTTP status와 화면용 응답을 정의한다.
- **AI 경계:** 내부 `snake_case` 결과를 제공한다.
- **이유:** 내부 LLM·provider 모델을 외부 API로 그대로 노출하지 않는다.

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

아래 항목마다 `동의 / 수정안 / 제외`, 담당자, 결정일과 근거 PR 또는 ADR을 회신해야 한다. 결정되지 않은 값은 추정하지 않고 `UNKNOWN`, 확인 필요 또는 안전 실패로 처리한다.

### 실행 중 상태 변경과 중복 요청

- **Case version:** Case 단위 증가 version과 `expectedVersion` 비교 후 저장하는 방식을 제안한다. version의 원천, 증가 시점과 충돌 응답을 정해야 한다. 실행 중 바뀐 Case를 이전 판단으로 덮어쓰지 않기 위해 필요하다.
- **중복 요청 방지:** 사용자·endpoint·`clientEventId` 범위에서 같은 요청만 기존 결과를 다시 주는 방식을 제안한다. key 범위, 보존기간과 같은 key에 다른 내용이 들어온 경우를 정해야 한다.
- **전체 제한 시간:** 하나의 전체 deadline 안에서 제한된 재시도만 허용하는 방식을 제안한다. gateway 시간, 재시도 담당과 비동기 전환 기준을 정해야 한다.
- **실행 ID 소유권:** 외부 coordinator가 `runId`와 deadline을 주입하는 목표안을 제안한다. 현재 `AgentGraph`가 내부 생성하는 `runId`와 어떻게 전환할지 정해야 한다.
- **원자 저장:** 변경 후보, decision과 history를 전부 저장하거나 전부 취소하는 방식을 제안한다. Evidence를 먼저 중복 안전하게 저장할 수 있는 범위와 실패 정책을 정해야 한다.

### Case 값과 절차 단계

- **미확인과 삭제 구분:** `UNKNOWN`은 `value=null`, 명시적 삭제는 별도 operation으로 표현하는 안을 제안한다. `null`, 미확인, 해당 없음과 삭제를 어떻게 구분할지 정해야 한다.
- **공식 field와 enum:** `UNKNOWN`을 enum 값으로 둘지는 **결정됐다 — 두지 않는다**(팀 결정 2026-09-19). 미확인은 값이 아니라 상태이므로 `value=null`과 확인 상태로 표현한다. DB 쪽 정리는 [`be-requests.md`](./be-requests.md) 4번. 나머지 값 집합은 아직 다르다. 예를 들어 DB의 `lease_status`는 `LEASED_PAID | LEASED_FREE | OWNED`, AI는 `ACTIVE | TERMINATION_NOTIFIED | TERMINATED | OWNED`를 사용한다. DB의 `restoration_scope`는 `UNKNOWN | PARTIAL | FULL | NOT_REQUIRED`, AI는 `AGREEMENT_REQUIRED | TENANT_ALL | LANDLORD_ALL | SHARED | NOT_REQUIRED`를 사용한다. 어느 값을 공통 기준으로 삼을지와 이전 값 mapping을 합의해야 하며, adapter에서 임의 변환하면 안 된다.
- **Case fact 범위:** 지원 판단에 필요한 사업체 형태, 건축물 용도와 과거 지원 이력 등의 포함 범위와 저장 원천을 정해야 한다.
- **절차 registry:** AI 입력에는 변하지 않는 ID·code뿐 아니라 사용자에게 보여줄 `stepName`, 발화 매칭용 alias와 registry version이 필요하다. **ERD에는 이미 `step_name`·`utterance_aliases`·`registry_version`이 들어갔다.** 남은 것은 SQLModel 클래스 반영과 데이터 입력이다 — [`be-requests.md`](./be-requests.md) 1·6번. 소유자, 적용 조건과 변경·폐기 정책은 여전히 합의가 필요하다.
- **진행 상태 초기화:** Case에 적용되는 모든 절차 단계를 한 transaction에서 만들고 개수를 검증하는 방식을 제안한다. 초기화 시점과 registry 변경 시 처리를 정해야 한다.

### 지원사업과 Evidence

- **지원사업 ID:** 내부 ID, Wiki UUID와 외부 공고 ID의 안정적인 mapping을 제안한다. ID 원천과 공고 revision 처리 정책을 정해야 한다.
- **지원 판단과 실제 신청 분리:** 지원 검토 결과와 실제 신청 lifecycle을 분리하는 방식을 제안한다. 각 상태와 쓰기 권한을 정해야 한다.
- **신청 상태 쓰기:** 명시적 PATCH와 자연어 결과 입력 중 어느 경로를 기준으로 삼을지, 허용 상태 전이와 기록할 actor를 정해야 한다.
- **Evidence:** 바뀌지 않는 ID, 출처, version, 원문 위치, hash와 계보를 보존하는 방식을 제안한다. 저장 위치, 조회 방법과 보존·삭제 정책을 정해야 한다.
- **Decision·Review 기록:** decision, 검수 대상 digest, proof와 run·trace를 함께 기록하는 방식을 제안한다. 보존 기간과 조회 형태를 정해야 한다.
- **실행 dependency:** 같은 version의 절차 registry와 검수된 지원사업 catalog 전체를 한 묶음으로 전달해야 한다. inline 전달과 권한 있는 resolver 중 하나를 고르고 cache·갱신·실패 정책을 정해야 한다.

### 충돌, API 응답과 보안

- **Conflict 확인:** 서버가 발급한 opaque ref에 digest, Case/version, 만료시간과 1회 사용 조건을 묶는 방식을 제안한다. ref 발급·저장·소비 방식을 정해야 한다.
- **Agent 결과의 API 변환:** 결과 종류가 명확한 tagged union을 제안한다. `NEEDS_MORE_INFO`, 변경 없음과 실패를 어떤 body·HTTP status로 보낼지 정해야 한다.
- **인증:** Kakao OAuth로 사용자를 식별하고 서비스 JWT로 이후 요청을 인증하는 큰 방향이 있다. claim, 전달 위치, 만료, rotation과 401·403·404 정책을 정해야 한다.
- **개인정보:** 원문 입력 최소 보존과 prompt·trace 허용 목록을 제안한다. 암호화, 접근, 보존·삭제와 동의 범위를 정해야 한다.
- **Guardrail 기록:** 저장 직전 판정과 별도 audit record를 coordinator가 남기는 방식을 제안한다. 판정 필드, 생성·검증 주체와 보존 방법을 정해야 한다.

## 5. shared DTO 후보

### 5.1 공통 규칙

아래 DTO는 모두 **검토를 위한 후보**다. 아직 승인되거나 구현되지 않았다.

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

현재 AI 내부 `CaseSnapshot`은 `snapshot_id`, `case_id`, nullable `case_version`, `case_status`, `facts`, `procedure_progress`, `evidence_records`, `captured_at`의 8개 필드만 받는다. 위 shared 후보의 필수 version, support, latest decision과 history 영역은 현재 모델에 자동 입력되지 않는다. 계약 승인 후 AI가 별도 adapter와 필요한 내부 schema 확장을 구현해야 하며, 외부에서 확장 필드를 보내는 것만으로 연동되지는 않는다.

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

현재 Graph는 `runId`를 내부에서 만들고 선택적인 `traceId`만 외부에서 받으며, trigger의 `clientEventId`를 DB 중복 요청 방지에 사용하지 않는다. 따라서 위 invocation envelope는 현재 공개 호출의 다른 이름이 아니다. P0에서 ID와 deadline 소유권을 정한 뒤 AI entrypoint와 외부 coordinator를 함께 맞춰야 한다.

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
| `REVIEWED_PLAN` | digest로 내용이 결속된 `ReviewSubject`와 matching `ReviewProof` | `NEEDS_MORE_INFO`이거나, 저장 결과에 따라 `UPDATED` 또는 `NO_CHANGE` |
| `CONFLICT` | Case/snapshot/version에 묶인 conflict 후보 | `CONFLICT`와 server-issued 확인 ref |
| `SAFE_FAILURE` | failure code, retryable, recovery action, trace | `FAILED` 또는 합의한 오류 envelope |

외부 검증·저장 경계에서 사용할 camelCase 변환 후보는 다음과 같다. 이름이 같은 현재 AI 내부 type을 wire format으로 직접 노출한다는 뜻은 아니다.

`REVIEWED_PLAN`의 decision만 보고 저장 성공을 뜻하는 `UPDATED`로 바꾸면 안 된다. `ACTION`이어도 변경 후보가 비어 있을 수 있으므로, 외부 coordinator가 ReviewProof와 저장 조건을 검증하고 transaction·재조회까지 마친 뒤 `UPDATED`와 `NO_CHANGE`를 구분해야 한다.

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

**Guardrail 판정은 Agent 안에서 한다**(팀 결정 2026-09-19). 무엇이 허용되는 변경인지, 근거 없는 단정이 아닌지, 상태 전이가 유효한지는 Agent가 판정해 결과에 담는다.

BE가 저장 직전에 하는 것은 Guardrail이 아니라 **저장 조건 확인**이다 — Case version이 그대로인지, 요청자가 그 Case의 주인인지. 이 둘은 DB의 현재 상태를 봐야 알 수 있어서 Agent가 할 수 없다.

audit 필드나 별도 proof DTO는 §4 P0에서 구조와 발급·검증 주체를 정하기 전까지 이 command의 확정 필드가 아니다.

`PersistResult`는 `APPLIED | NO_CHANGE | VERSION_CONFLICT | REJECTED` tagged union 후보이며, `APPLIED`일 때 새 Case version과 read-back 식별자를 반환한다. 여기의 persistence `NO_CHANGE`는 현재 Agent outcome `NO_CHANGE`가 있다는 뜻이 아니다.

`ConflictConfirmationRequest` 후보는 `conflictRef`, `confirmation=CONFIRM_ORIGINAL`, `expectedVersion`, `clientEventId`만 받는다. client가 원 후보의 field/value를 다시 보내거나 수정할 수 없다. 서버는 opaque ref로 원 candidate, subject digest, Case ID/version, owner를 복원하고 TTL·single-use·CAS를 검증해야 한다. `standalone:` ref는 운영 HTTP에 노출하지 않는다.

그 뒤 확인된 후보를 새 Graph 실행과 Review에 넣는 경로는 아직 구현되지 않았다. 현재 `CONFIRMED_CONFLICT` fact-change 타입만 있고 이를 만드는 trigger, Graph 단계와 외부→AI adapter는 없다. 운영 confirm endpoint를 열기 전에 AI가 이 경로와 Review 회귀 테스트를 구현하고 공통 계약으로 승인받아야 한다.

### 5.6 지원사업 DTO 분리

| DTO | 표현하는 것 | 포함하면 안 되는 것 |
|---|---|---|
| `SharedSupportMatchDTO` | Case와 canonical support program 간 `POSSIBLY_RELEVANT \| NEEDS_CONFIRMATION \| NOT_RELEVANT \| STALE \| UNVERIFIABLE` 및 Evidence/version | 실제 신청 완료 상태 |
| `SharedSupportApplicationDTO` | 사용자가 실제 수행한 `NOT_STARTED \| APPLIED \| SUPPLEMENT_REQUIRED \| RESUBMITTED \| APPROVED \| REJECTED` lifecycle | Agent가 계산한 자격 확정 |

공고 조회 또는 subsidies GET은 application row를 만들지 않는다. 미검수 discovery candidate를 trusted catalog나 match로 자동 승격하지 않는다.

## 6. 외부 HTTP와 인증 후보

### 6.1 endpoint 목록

아래 endpoint는 모두 **검토 후보**이며 아직 승인되거나 구현되지 않았다. 별도 `/replan` endpoint를 만들지 않고 `/results` 처리 안에서 재계획하는 안이다.

- **`GET /auth/kakao/login`:** 카카오 로그인 시작. Agent 호출과 업무 데이터 쓰기 없음
- **`GET /auth/kakao/callback`:** OAuth callback과 서비스 session 또는 token 발급
- **`POST /cases`:** Case 생성, 절차 진행 상태 초기화, 최초 Agent 실행과 저장
- **`GET /cases/{caseId}`:** 현재 Case 조회. 기본적으로 Agent 호출과 쓰기 없음
- **`POST /cases/{caseId}/results`:** 자연어 결과 입력, 재계획, 검증과 저장
- **`POST /cases/{caseId}/results/confirm`:** 기존 conflict에 대한 사용자 확인, Agent 재실행과 CAS 저장
- **`GET /cases/{caseId}/subsidies`:** 지원 검토 결과와 실제 신청 상태 분리 조회. 조회만으로 쓰기 없음
- **`PATCH /subsidy-applications/{applicationId}`:** 사용자가 실제 수행한 신청 상태 변경. Agent 호출 없음
- **`GET /cases/{caseId}/history`:** 제한된 decision·변경 이력 조회. Agent 호출과 쓰기 없음. MVP 이후로 미룰 수 있음

`POST /cases/{caseId}/results` request 후보는 `rawInput`, `expectedVersion`, `clientEventId`를 갖는다. canonical procedure 대상은 서버 snapshot과 registry로 판단하며 client가 임의 DB step ID를 주입하지 않는다. 외부 response는 `result` discriminator, `caseVersion`, 변경 요약, decision/view state, Evidence reference를 포함하는 후보이며 내부 snake_case 객체를 그대로 직렬화하지 않는다.

### 6.2 인증 방향과 아직 정할 세부 계약

큰 방향은 카카오 OAuth로 사용자를 식별하고 RE:BORN 서버가 발급한 서비스 JWT로 이후 요청을 인증하는 것이다. 카카오 access/refresh token과 서비스 JWT access/refresh token은 다른 credential이다. claim, 쿠키/본문 전달, 만료, refresh rotation, 저장 위치와 401/403/404 비노출 정책은 P0 승인 전이다.

Case route는 항상 BE가 token과 Case owner를 검증한 뒤 snapshot을 조립한다. 소유권 검증 실패 응답은 Case 존재 여부를 누출하지 않는 한 가지 정책으로 통일한다.

### 6.3 outcome과 HTTP 오류

아래는 결정용 후보이며 확정 status code가 아니다.

- **변경 저장 성공:** body `UPDATED`, HTTP 200 후보. 저장 후 다시 읽은 Case version 포함
- **추가 확인 질문:** body `NEEDS_MORE_INFO`, HTTP 200 후보. 저장 가능한 변경과 질문을 함께 받았을 때 우선순위 결정 필요
- **사용자 확인이 필요한 충돌:** body `CONFLICT`, HTTP 200 또는 409 후보. 서버가 발급한 opaque ref만 노출
- **오래된 snapshot:** body `VERSION_CONFLICT`, HTTP 409 후보. 업무 변경은 하나도 저장하지 않음
- **동일 요청 재전송:** 이전 body와 HTTP status 재사용. 새 Agent 실행·history를 만들지 않음
- **잘못된 요청:** HTTP 400 또는 422 후보. Agent 호출 전에 차단
- **인증 실패:** HTTP 401 후보. token 값을 log에 남기지 않음
- **권한 없음 또는 Case 없음:** HTTP 404 후보. Case 존재 여부를 보호하는 정책 필요
- **외부 provider 또는 Review 실패:** `SAFE_FAILURE` 변환, HTTP 200 또는 5xx 후보. 재시도 가능 여부와 복구 행동을 보존

## 7. persistence 논리 요구사항

이 절은 AI 연동에 필요한 **논리 불변식과 현재 DB 설계의 확인 항목**이다. [`../schema/schema_table.md`](../schema/schema_table.md)와 `ERD.png`의 테이블·컬럼을 덮어쓰는 물리 설계가 아니다. 실제 migration·ORM이 생기기 전에는 DB 문서와 아래 요구사항의 차이를 함께 확인해야 한다.

1. 현재 DB 설계 문서는 테이블명을 `CASE`로 사용한다. `CASE`는 MySQL keyword이므로 `CASES`로 바꿀지, quoting 규칙을 강제할지 migration 전에 결정해야 한다. AI adapter는 결정된 물리명에 맞추되 내부 `case_id` 의미는 유지한다.
2. Case의 변경 가능한 상태에는 단조 증가하는 version 또는 동등하게 강한 field-level CAS가 있어야 한다. 저장은 snapshot의 `expectedCaseVersion`과 현재 상태가 일치할 때만 성공한다.
3. Case별 canonical procedure step의 current progress는 `(caseId, procedureStepId)`당 **최대 1개**여야 한다. 현재 DB 문서는 `UNIQUE (case_id, procedure_step_id)`를 명시했으며, 실제 migration에도 같은 제약이 포함되는지 검증해야 한다.
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

- 폐업 절차 **내용**은 미리 저장·검수한 자료에서만 읽는다(멘토 리뷰 PR #14). 사용자 요청마다 공식 사이트를 조회하지 않는다. BE가 절차 본문을 **작성**할 필요는 없지만, 검수된 본문과 그 **출처(URL·발췌·해시·수집시각·검수자)를 저장할 자리**는 필요하다 — [`be-requests.md`](./be-requests.md) 2번.
- BE는 canonical step identity, Case progress, Evidence 저장·resolver와 위 절차 자료의 저장소를 제공한다.
- AI는 그 자료를 읽어 Case 문맥에서 해석한다. 공식 사이트 직접 조회는 AI의 갱신 명령에서만 수행한다.
- 검색 provider 결과는 URL 발견 수단일 뿐 Evidence가 아니다. 공식 domain allowlist, HTTPS, redirect·DNS/SSRF, MIME, byte, timeout 제한을 통과해 직접 읽은 원문만 Evidence 후보가 된다.
- 공식 registry miss에서만 승인된 provider fallback을 쓰고 provider attempt, URL, fetch 결과, hash와 최신성을 trace한다.
- 기업마당 API 응답은 discovery input이다. 원문 보존·hash → external/canonical ID mapping → 조건·서류 구조화 → 공식 첨부 교차검증 → 담당자 또는 승인된 deterministic rule 검수 → immutable catalog version 발행 뒤에만 Support Agent의 trusted input이 된다.
- API로 제공되지 않는 자료의 crawling/RAG는 AI 구현 계획에 포함하되 robots/이용조건, 증분수집, chunk lineage, freshness, 삭제와 재색인 기준을 먼저 승인한다. “미구현” 표시는 포기가 아니라 현재 상태이며 milestone과 acceptance를 가진 목표여야 한다.

상세 provider 우선순위, 실제 API 관찰과 crawling/RAG milestone은 `official-data-sources.md`를 따른다.

## 9. 보안·PII·trace·비용·재시도

### 인증정보

- **최소 요구:** OAuth, JWT와 API key를 prompt, 오류 응답과 일반 log에 기록하지 않는다.
- **검증:** secret pattern test와 log 점검

### 사용자 원문과 사업자 식별정보

- **최소 요구:** 입력 ID와 비식별 텍스트를 분리하고 필요한 범위만 전달·보존한다. 사업자 식별정보는 권한 있는 결정적 resolver에만 전달하고 암호화·마스킹·외부 전송 기록을 적용한다.
- **검증:** PII fixture 기반 prompt·trace 검사와 다른 사용자 접근 거부 테스트

### Evidence

- **최소 요구:** 접근 권한, source hash, 계보, 보존과 삭제 정책을 가진다.
- **검증:** 모든 reference 조회와 변조 검출 테스트

### Trace와 비용

- **최소 요구:** `runId`, `traceId`, 구성요소 호출, 재시도, 소요 시간과 결과를 연결한다. 모델·provider와 prompt/completion token, 재시도 횟수를 집계하되 사용자 원문은 수집하지 않는다.
- **검증:** Case 간 trace 혼선 방지와 telemetry schema 테스트

### 중복 요청과 제한 시간

- **최소 요구:** 같은 key와 같은 내용은 이전 결과를 다시 주고, 같은 key에 다른 내용은 거부한다. 전체 deadline 안에서 구성요소 예산과 제한된 재시도를 적용하고 취소 정책을 정한다.
- **검증:** 동시 재전송, timeout과 fault injection 테스트

### 외부 원문 조회

- **최소 요구:** 공식 allowlist, DNS와 private IP 차단, redirect 재검증, 응답 크기·MIME·시간 상한을 적용한다.
- **검증:** SSRF, redirect와 대용량 응답 fixture 테스트

Langfuse 등 특정 관측 제품은 이 계약의 필수조건이 아니다. 제품을 선택해도 raw prompt·PII·credential을 수집하지 않고 위 trace/cost 의미를 만족해야 한다.

## 10. BE 산출물

P0 합의 뒤 BE PR에는 다음이 함께 있어야 한다.

- **공통 DTO 코드:** version, 필수·nullable, enum, tagged union과 adapter. AI와 같은 fixture를 양방향으로 검증해야 함
- **생성된 OpenAPI:** §6 endpoint, 인증, 정상·오류 결과와 예시. CI에서 코드와 문서 차이를 검출하고 예시가 schema를 통과해야 함
- **공식 registry:** Case field·enum, 절차 ID·code·별칭·version과 지원사업 ID. unknown·폐기 값 mapping을 테스트해야 함
- **Migration과 data dictionary:** 실제 테이블·제약·index와 rollback. 기존 데이터 보존과 적용·복구 테스트가 있어야 함
- **Snapshot assembler:** 권한 확인 후 한 시점의 `SharedCaseSnapshotDTO` 생성. AI strict adapter와 계약 테스트를 통과해야 함
- **Coordinator:** 중복 요청 방지, 전체 제한 시간, Agent 호출, Guardrail과 저장 순서. 중복·timeout·retry 테스트가 있어야 함
- **Persistence service:** CAS, 변경·decision·history의 원자 저장과 저장 후 재조회. 동시성과 fault injection 테스트가 있어야 함
- **Evidence resolver:** 출처별 저장, hash, 계보, 권한과 보존. 모든 reference 조회와 변조 거부 테스트가 있어야 함
- **Conflict reference service:** opaque ref, digest, owner, version, TTL과 1회 사용. 변조·만료·재사용·오래된 version을 거부해야 함
- **운영 ADR·runbook:** 인증, transaction, 개인정보, 외부 통신, timeout, 장애와 rollback. 비밀값 없이 재현 가능한 절차가 있어야 함

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

1. BE·AI·PM은 §4 P0 각 항목에 결정과 근거를 기록한다.
2. BE와 AI가 shared DTO version, canonical registry와 contract fixture를 함께 승인한다.
3. BE가 OpenAPI, migration, coordinator/persistence 구현과 ADR를 PR로 제출한다.
4. AI가 shared adapter와 필요한 runtime schema 확장을 별도 PR로 제출한다.
5. 양측 CI에서 같은 contract fixture와 digest vector를 실행한다.
6. 개발 Case로 read-only smoke를 먼저 통과한 뒤 쓰기 통합 test를 연다.
7. §11을 모두 충족한 version만 공동 승인·구현·검증 완료로 기록한다.

### 승인 기록에 반드시 남길 내용

- 계약 version
- 현재 상태
- AI·BE·PM 승인자
- 승인일
- 근거 PR 또는 ADR
- 예외와 남은 작업

현재는 계약 version과 승인자·승인일·근거가 없으며, 공동 승인된 계약은 0개다.

## 13. 근거와 출처

- **AI 내부 schema:** `backend/app/agent/schemas.py`의 `CaseSnapshot`, `EvidenceRecord`, `MutationSet`, `ReviewSubject`, `ReviewProof`와 세 가지 `AgentRunOutcome`
- **현재 실행 순서와 결과:** `backend/app/agent/graph.py`, `backend/tests/agent/test_graph.py`
- **공식 원문 조회:** `backend/app/agent/procedure_tool/`과 관련 테스트
- **지원금 분석과 기업마당 조회의 분리:** `backend/app/agent/support_agent/`과 관련 테스트
- **Review 무결성:** `backend/app/agent/review_tool/`과 관련 테스트
- **Agent의 DB 직접 접근 금지:** `backend/CLAUDE.md`
- **현재 구조와 목표 구조:** [`architecture.md`](../architecture.md)
- **Agent·Tool의 정확한 공개 호출 계약:** [`tool-io-schema.md`](./tool-io-schema.md)
- **공식 API 관찰과 crawler·RAG 계획:** [`official-data-sources.md`](./official-data-sources.md)
- **DB 팀의 현재 설계:** [`../schema/schema_table.md`](../schema/schema_table.md), [`schema/ERD.png`](../schema/ERD.png)
- **남은 연동 차이:** `CASE` 예약어 처리, DB·AI enum mapping, Case version/CAS, Case field 이력, 완료 상태와 Blocker의 정합성

이 문서가 확정하는 것은 **구현 방향이 아니라 검토할 단일 계약안**이다. 승인 전 공동 계약은 0개이며, 실제 BE migration·OpenAPI·통합 test가 생기기 전에는 생산 연동 완료로 보고하지 않는다.
