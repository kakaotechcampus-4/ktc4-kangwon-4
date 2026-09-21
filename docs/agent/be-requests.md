# BE에 요청하는 것

> 소유: AI · 기준일: 2026-09-21
> 데이터 기준은 **`origin/develop`의 `docs/schema/schema_table.md`**입니다. 로컬 사본이나
> 미병합 브랜치가 아니라 병합된 것을 봅니다(2026-09-21 확인: 로컬과 `origin/develop` 동일).
>
> 이 문서의 책임: **Agent가 동작하려면 필요한데 AI가 고칠 수 없는 것**만 모읍니다.

배경 계약과 논의 항목은 [`be-integration-requirements.md`](./be-integration-requirements.md)에 있습니다.
여기는 그중 **지금 바로 막고 있는 것**만 짧게 추립니다.

**이번 작업은 `schema_table.md`를 변경하지 않습니다.** 과거의 새 출처 컬럼·JSON 컬럼·공용
테이블 제안은 구현 요청으로 진행하지 않습니다. BE가 만든 코드와 현재 브랜치 반영 상태는
[`implementation-status.md`](./implementation-status.md) §3에 구분했습니다. 2026-09-20 20:52 KST에
갱신된 `.env`로 실제 MySQL을 읽기 전용 조회했고, 아래 6개 테이블·8개 컬럼 누락도 확인했습니다.
확인한 연결 대상의 상태이며 다른 배포 DB 전체에 대한 판정은 아닙니다.
실측은 [`live-verification.md`](./live-verification.md)에 있습니다.

멘토 재리뷰(2026-09-19)에서 "DDL이나 SQLModel 클래스 아직 반영되지 않은 건들이 있으니 확인 후
구현 요청드립니다"라고 하신 부분이 1번입니다.

---

## 1. SQLModel이 ERD보다 뒤처져 있습니다

ERD와 `docs/schema/schema_table.md`에는 있는데 `backend/app/be/models/`에 없습니다.

**컬럼**

| 테이블 | 없는 컬럼 | Agent가 왜 필요한가 |
|---|---|---|
| `case` | `case_version` | 현행 스키마의 필수 버전입니다. 과거 MVP 제외 메모는 최신 사용자 지시의 기준이 아닙니다. 실제 버전 공급·증가·저장 검증을 BE와 연결해야 하며 내부 fixture의 `null`을 그대로 저장할 수 없습니다 |
| `procedure_step` | `step_name`, `utterance_aliases`, `registry_version`, `deprecated_at`, `replaced_by_procedure_step_id` | 앞 두 개는 **필수**입니다. Agent가 사용자 말을 절차 단계에 연결할 때 표시명과 별칭으로 맞춥니다(`schemas.py`의 `KnownProcedureStep`). 지금은 `step_code`만 있어서 연결할 수가 없습니다 |
| `support_item` | `catalog_version`, `external_notice_id` | 현행 스키마의 지원사업 catalog 버전과 외부 공고 식별자를 보존해야 합니다 |

**테이블 (클래스 자체가 없음)**

`evidence`, `evidence_lineage`, `conflict_reference`, `decision_record`, `case_field_history`, `support_match`

이 중 MVP에 꼭 필요한 건 **근거 저장**입니다. 다만 멘토가 "MVP 단계에서 MySQL에 구조화된 방식으로
저장하는 것은 필수가 아니다, evidence가 포함된 llm 응답을 json 형식으로 저장해두는 것만으로도
evidence 추적이 이미 동작한다"고 하신 대안이 있습니다. **현행 스키마 안의 실제 저장 방식은
아직 확정하지 않았습니다**(3번). 이 말만으로 새 JSON 컬럼을 만들지는 않습니다.

## 2. 절차 원문과 실제 절차 ID를 연결해야 합니다

`procedure_step`에는 담당기관·기한규칙·필요서류·주의사항이 있는데,
**"이 내용을 어느 공식 문서에서 언제 가져왔고 원문이 무엇이었는지"**가 없습니다.

Agent는 기한이나 서류를 말할 때 근거(URL·발췌·해시·수집시각)를 함께 내야 합니다.
출처 없는 DB 절차 metadata만으로는 확정 안내를 하지 않습니다.

현재 AI 쪽은 공용 원문을 JSON 스냅샷으로 들고 있습니다
(`backend/app/agent/procedure_tool/data/reviewed-procedures.ko-KR.json`).
이 자료를 유지하고, 실제 Case 판단에 쓰인 근거는 기존 `EVIDENCE` 구조에 맞춰 BE가 저장하는
연결을 협의합니다. `case_id` 제약 변경이나 새 컬럼·테이블 추가는 요청하지 않습니다.
AI 런타임은 기존 `ReviewedProcedureStore` 주입을 지원하므로 출처가 준비되면 그 경계로 연결합니다.
자세한 구조는 [`procedure-knowledge.md`](./procedure-knowledge.md)에 있습니다.

## 3. 기존 스키마 안에서 판단·근거 저장을 연결해야 합니다

멘토가 판단 결과 JSON 보관을 MVP 대안으로 허용한 사실은 유지합니다.
다만 `schema_table.md`에 없는 JSON 컬럼을 이번 작업에서 추가하거나 BE에 추가 요청하지 않습니다.

Agent 결과에는 이미 **판단·검수 대상·근거가 전부 닫힌 형태로** 들어 있습니다
(`ReviewSubject` + `ReviewProof` + evidence 집합). 따로 조립할 필요가 없습니다.

`DECISION_RECORD`, `EVIDENCE`, `EVIDENCE_LINEAGE`, `CASE_HISTORY` 등 현재 정의된 구조 안에서
어떤 값을 저장하고 어떤 참조를 재조회할지 C4/C5에서 확정해야 합니다. 근거 관계를 잃는
문자열 요약이나 문서에 없는 FK/JSON 컬럼으로 AI가 임의 해결하지 않습니다.

## 4. DB `UNKNOWN`과 AI 내부 미확인의 경계 변환이 필요합니다

팀 메모(2026-09-19)의 AI 표현은 **미확인은 값이 아니라 상태**라는 것입니다.
이번 지시에서 물리 스키마 기준을 `schema_table.md`로 고정했으므로, 기존 DB enum을 바꾸는
요청 대신 읽기·쓰기 경계 변환을 C1에서 협의합니다.

- 모델에 이미 들어간 것: `case.restoration_scope`, `case.demolition_required`
  — `UNKNOWN`이 enum 값이자 기본값입니다 (`backend/app/be/models/case.py:34-48`)
- DB의 `UNKNOWN`이 문서에만 있는 것: `case.restoration_status`
  — `schema_table.md:60`은 `UNKNOWN` 기본값인데 모델(`case.py:28-33`)에는 아직 없습니다.
  현행 스키마와 모델의 차이를 BE에서 확인해야 합니다.

실제 DB도 `restoration_status.UNKNOWN`이 없었습니다. `support_item_application.application_status`
역시 현행 신청 생명주기 대신 `NOT_CHECKED/ELIGIBLE/NOT_ELIGIBLE`을 포함한 이전 enum입니다.
AI가 이 값을 자격 확정이나 현행 신청 상태로 변환하지 않고 BE migration 대상으로 건의합니다.

Agent는 이미 이 방식입니다 — 값은 typed 값이거나 `null`이고, 확인 여부는 따로 표현합니다.

제안은 DB `UNKNOWN`을 Agent 경계에서 `status=UNKNOWN, value=null`로 읽는 것입니다.
반대 방향의 저장과 명시적 `CLEAR`, NOT NULL 필드의 처리는 BE·FE와 합의가 필요합니다.
확인되지 않은 값을 `NOT_REQUIRED`나 false로 바꾸지 않습니다.

## 5. (해결) `sqlmodel`이 `backend/requirements.txt`에 없었습니다

`backend/app/be/models/`의 모든 모델이 `from sqlmodel import ...`를 하는데
requirements 세 파일 어디에도 고정돼 있지 않습니다.
깨끗한 환경에서 `pip install -r backend/requirements.txt`만 하면 `app.be.models`를 import할 수 없습니다.

(`backend/requirements.txt`는 BE 소유라 직접 고치지 않았습니다. 현재 venv에는 `0.0.42`가 설치돼 있습니다.)

**2026-09-21 해결됨.** `origin/develop`(`87367f6`)의 `backend/requirements.txt:10`에
`sqlmodel==0.0.42`가 있습니다(커밋 `b82d58a`). 더 요청할 것은 없습니다.

## 6. `procedure_step`에 행을 넣을 방법이 없습니다

Alembic 설정도, seed 스크립트도, SQL 파일도 없습니다.
1·2번이 정리돼도 **데이터를 넣는 경로**가 있어야 Agent가 DB에서 절차를 읽을 수 있습니다.
실제 DB에서도 `procedure_step=0`, `support_item=0`을 확인했습니다. 공식 API에서 받은
절차 문서 4건·지원공고 9건(2026-09-21 재수집)은 미검수 후보이며, DB 시드로 자동 승격하지 않았습니다.

## 7. 우선 협의할 건의안 — 기존 스키마 안에서 연결

아래는 협의용으로 준비한 항목이며 상대 파트에 전달·승인됐다는 뜻은 아닙니다.
현재 스키마로 표현할 수 없는 필수 요구가 확인되면 구체적인 재현 사례·영향·대안을 덧붙여
변경을 건의합니다. 새로운 테이블이나 컬럼이 필요하다고 미리 가정하지 않습니다.

| 건의 | 사용할 기존 기준 | 필요한 결정·완료 증거 |
|---|---|---|
| 이미 만든 BE 작업의 통합 위치 확인 | 현재 17개 테이블 정의와 구현된 BE 브랜치 | 실제 모델·migration 위치와 적용 상태 확인. 중복 테이블 생성 요청이 아님 |
| Case 입력 adapter 완성 | `CASE`, `CASE_PROCEDURE_STEP`, `PROCEDURE_STEP`, `EVIDENCE` | 실제 ID·버전·시각·근거로 `CaseSnapshot` 구성. `UNKNOWN`/NULL 변환과 누락 근거 처리 합의 |
| 절차 조회 데이터 연결 | `PROCEDURE_STEP`, `STEP_DEPENDENCY`, `STEP_ELIGIBILITY` | 검수된 원문과 실제 step ID·조건·선후 관계 연결. 문서·시드 검수 담당 확인 |
| 실제 지원사업과 Wiki 매핑 제공 | `SUPPORT_ITEM.id`, `uuid`, `external_notice_id`, `catalog_version` | A7 reader가 사용할 실제 ID·UUID 쌍과 검수 노트 위치. 공고 수집기가 임시 부여한 로컬 ID·UUID를 DB 값으로 간주하지 않음 |
| 실제 S3 원문 읽기 연결 | `SUPPORT_ITEM.source_file_location`, 기존 Evidence·version 정보 | 실제 지원사업과 객체 경로 매핑, 읽기 설정·원문 version/hash 공급 방식. API 정규화 hash와 객체 bytes hash 구분. AI가 임의 경로·DB 식별자를 생성하지 않음 |
| 결과 저장 함수와 transaction 경계 | `DECISION_RECORD`, `EVIDENCE`, `EVIDENCE_LINEAGE`, `CASE_HISTORY`, `BLOCKER`, 필드/절차 변경이력, `SUPPORT_MATCH` | Review 결과 검증 후 허용 변경·판단·근거·이력을 저장하고 재조회. 중간 실패 rollback 검증 |
| 운영용 충돌 확인 연결 | `CONFLICT_REFERENCE`의 version·만료·사용시각 | 소유권·현재값 검증, 1회 사용 보장, 재계획 및 저장 연결 |
| 원문·비식별 입력 보존 정책 | `CASE_HISTORY.raw_input` | 개인정보 원칙과 저장 목적을 함께 충족하는 내용·접근·보존 정책 협의. 임의 빈 값으로 필수 컬럼을 채우지 않음 |

지원금 조회는 `SUPPORT_ITEM.uuid`와 `source_file_location`을 사용하는 Wiki·S3 연결이 남았습니다.
Agent가 필요한 자격정보를 새 Case 필드로 만들거나 확인되지 않은 값으로 채우지 않습니다.

## 8. 사용자 입력의 비식별 처리를 누가 하는지 확인이 필요합니다

Agent는 `RedactedInput`을 받습니다. 이름 그대로 **BE가 이미 개인정보를 지운 텍스트**를 준다는
전제이고, `redacted_text`와 `redactions`가 그 계약입니다(`backend/app/agent/schemas.py`).
그런데 실제로 그 처리를 하는 BE 구현이 있는지 확인하지 못했습니다.

Agent 안에도 민감정보 정규식이 있지만 **그물이지 방벽이 아닙니다.** 이번에 사업자등록번호
패턴을 추가하면서 왜 그런지 실측했습니다 — 전화번호·이메일·주소까지 넓히면 실제 공고의
기관 문의처와 접수처가 걸립니다. 공백 구분까지 허용하는 사업자번호 패턴은 저장소의 공식
자료에서 11건이 걸리는데 전부 SHA-256 근거 digest와 공식 문서 URL의 id 값입니다.
근거와 공식 링크를 막으면 실행이 자기 근거 때문에 실패합니다.

즉 **경계마다 필요한 엄격함이 다릅니다.** 외부로 나가는 검색어는 넓게 막아도 되지만,
공식 원문 발췌가 지나가는 자리는 좁아야 합니다. 정규식만으로 입력 단계의 개인정보를
책임질 수 없습니다.

확인이 필요한 것:

- `RedactedInput`을 만드는 BE 구현이 있는지, 없다면 누가 언제 만드는지
- 무엇을 지우고 무엇을 남기는지(상호·주소·금액·연락처)와 `redactions`의 형식
- 지우기 전 원문을 어디에 얼마나 두는지 — `CASE_HISTORY.raw_input`과 함께 OD-05에서 정합니다

## 9. Case를 만들 수 없는 두 컬럼 — `lease_status` · `restoration_status`

2026-09-21에 Agent Graph를 실제로 끝까지 돌려 보고 확인했습니다. **지금 스키마로는 Hero
Scenario Turn 1의 Case를 만들 수 없습니다.** 이건 미정 사항이 아니라 고쳐야 할 것입니다.

### 무엇이 문제인가

| 컬럼 | `schema_table.md` | 실제 DB·모델 | 문제 |
|---|---|---|---|
| `lease_status` | NOT NULL, **DEFAULT 없음**, `LEASED_PAID/LEASED_FREE/OWNED` | 같음 | 임대 형태를 모르면 **행을 만들 수 없음** |
| `restoration_status` | NOT NULL, **DEFAULT `UNKNOWN`**, `UNKNOWN` 포함 5값 | `UNKNOWN` 없음, DEFAULT 없음 | 문서가 지정한 기본값이 **enum에 없음** |
| (비교) `restoration_scope` | NOT NULL, DEFAULT `UNKNOWN` | `UNKNOWN` 있음, DEFAULT 있음 | 정상 |
| (비교) `demolition_required` | NOT NULL, DEFAULT `UNKNOWN` | `UNKNOWN` 있음, DEFAULT 있음 | 정상 |

`restoration_scope`와 `demolition_required`는 "아직 모름"을 `UNKNOWN` 기본값으로 이미
처리하고 있습니다. 같은 성격의 두 컬럼만 빠져 있습니다.

### 왜 Case 생성이 막히는가

Turn 1에서 사용자는 "카페를 접으려고 합니다" 정도만 말합니다. 그 시점에 임대료를 내는지,
원상복구를 시작했는지는 **아무도 모릅니다.** 그런데 두 컬럼은 NOT NULL이고 넣을 값이 없습니다.

- `lease_status`: enum에 "모름"에 해당하는 값이 아예 없습니다
- `restoration_status`: `schema_table.md:60`이 "Case 생성 직후 `UNKNOWN`으로 시작"이라고
  적어 두었는데, 그 `UNKNOWN`이 enum에 없습니다

### 실측 근거

실제 LLM으로 Graph를 돌린 결과입니다(Case 골격은 만든 값, 절차·지원사업 지식은 실제 자료).

- 재계획 시나리오 **4회 전부 `lease_status`에서 막혔습니다.** 안전 실패 결과의
  `requested_field_paths`가 `['lease_status']`를 가리켰습니다.
- Case 생성 시나리오에서도 정보분석은 `lease_status`를 **일관되게 미확인으로 남겼습니다.**
  사용자가 "임대차 계약 기간이 아직 남았는데"라고만 말했고, 유상인지 무상인지는 그 문장에
  없기 때문입니다. Agent 가드레일이 추정을 막는 것은 의도된 동작입니다.

즉 **사용자가 알려주기 전에는 이 값을 채울 방법이 없고, 채우지 않으면 행을 만들 수 없습니다.**

### 요청

1. **`CASE.restoration_status` enum에 `UNKNOWN`을 추가하고 DEFAULT로 지정해 주세요.**
   `schema_table.md`가 이미 그렇게 정의하고 있으므로 스키마 변경이 아니라 **구현을 문서에
   맞추는 일**입니다. 실제 DB와 SQLModel 양쪽 모두 해당합니다.

2. **`CASE.lease_status`를 Case 생성 시점에 어떻게 둘지 정해 주세요.** 이건 `schema_table.md`
   자체를 바꾸는 일이라 AI가 단독으로 건의만 합니다. 선택지는 둘로 보입니다.
   - enum에 `UNKNOWN`을 추가하고 DEFAULT로 둔다 — 다른 두 컬럼과 같은 방식이고 일관됩니다
   - 컬럼을 nullable로 바꾼다 — AI 내부 표현(`status=UNKNOWN, value=null`)과 더 가깝습니다

   어느 쪽이든 **AI가 임의로 `LEASED_PAID`를 채워 넣지는 않습니다.** 사용자가 말하지 않은
   사실을 만드는 것이고, 루트 `CLAUDE.md`의 "모르는 것을 아는 척하기"에 걸립니다.

3. 두 컬럼이 정해지기 전까지 **Case 생성 API는 이 값들을 필수 입력으로 요구하지 말아
   주세요.** 요구하면 FE가 사용자에게 "임대료를 내십니까"를 첫 화면에서 물어야 합니다.

### `case_version`을 빼면 다른 세 테이블이 참조 대상을 잃습니다

`CASE.case_version`은 구현하지 않기로 확인했습니다(2026-09-21). 그런데 `origin/develop`의
`schema_table.md`는 그 컬럼을 여전히 `NOT NULL, DEFAULT 1`로 정의하고, **다른 세 테이블이
그 값을 NOT NULL로 담도록** 돼 있습니다.

| 테이블 | 컬럼 | 정의 |
|---|---|---|
| `CASE_FIELD_HISTORY` | `resulting_case_version` | NOT NULL — "변경 결과로 생성된 `case_version`" |
| `CONFLICT_REFERENCE` | `case_version` | NOT NULL — "대상 케이스 시점 버전" |
| `DECISION_RECORD` | `case_version` | NOT NULL — "대상 케이스 시점 버전" |

세 테이블 모두 구현 예정 목록에 있습니다. 구현할 때 이 컬럼에 **무엇을 넣을지** 정해야 합니다.
원본이 없어지므로 그대로 두면 채울 값이 없습니다. 정리가 필요한 것은 둘입니다.

1. `schema_table.md`에서 `CASE.case_version`을 빼고, 위 세 컬럼도 함께 정리해 주세요.
   문서와 결정이 어긋난 채로 두면 다음 사람이 다시 같은 질문을 합니다.
2. 낙관적 동시성 제어(동시 수정 충돌 방지)를 버전 없이 어떻게 할지 정해 주세요. 원래 이
   컬럼의 용도입니다. AI는 저장하지 않으므로 BE 판단이지만, 충돌 확인(C6) 경로가 이 값을
   쓰기로 돼 있어 함께 정해야 합니다.

AI 쪽은 `case_version`을 이미 선택 값(`int | None`)으로 다루고 있어 없어도 동작합니다.
2026-09-21 실제 Graph 실행도 `case_version=null`로 통과했습니다. 다만 AI가 임의의 버전을
만들어 넣지는 않습니다.

### 그 밖에 새 테이블·컬럼을 요청하는 것은 아닙니다

위 2건은 기존 컬럼의 허용값과 기본값 문제입니다. `schema_table.md`에 이미 정의된
6개 테이블(`EVIDENCE`, `EVIDENCE_LINEAGE`, `CONFLICT_REFERENCE`, `DECISION_RECORD`,
`CASE_FIELD_HISTORY`, `SUPPORT_MATCH`)은 구현 예정으로 확인했고, `CASE.case_version`은
구현하지 않기로 확인했습니다(2026-09-21). 그 밖에 새로 만들어 달라고 요청하는 테이블이나
컬럼은 없습니다.

## 10. AI 쪽에서 이미 닫은 항목 — `to_agent_case_snapshot` 진행 가능

BE `feature/case-service`의 `docs/case-service.md` "열린 이슈 A"가 `to_agent_case_snapshot`을
막고 있는 이유로 두 가지를 들었고, **둘 다 AI 쪽에서 끝냈습니다.**

| BE가 적은 조건 | 현재 AI 코드 | 상태 |
|---|---|---|
| **A-2** `lease_status`가 `ACTIVE/TERMINATION_NOTIFIED/TERMINATED/OWNED`(해지 단계)라 DB의 임대 조건과 다른 사실 | `LEASED_PAID/LEASED_FREE/OWNED` | **해결** — DB와 같은 값 |
| **A-2** `restoration_scope`가 `AGREEMENT_REQUIRED/TENANT_ALL/LANDLORD_ALL/SHARED/NOT_REQUIRED`(비용 부담자) | `PARTIAL/FULL/NOT_REQUIRED` | **해결** — DB와 같은 값 |
| **A-3** `entity_type`·`building_use_type`·`previous_support_history`가 DB에 없음 | Case 필드 허용 목록에서 **제거** | **해결** — DB에 컬럼을 만들 필요 없음 |

BE 문서의 "다음에 할 일" 2번이 *"AI 쪽이 `CASE_FIELD_SPECS`를 schema_table.md 기준으로
갱신하거나 매핑을 승인하면, DB에 없는 3개 필드 처리 방향이 정해지면 1차 구현을 진행한다"*
였습니다. 그 조건이 충족됐으니 진행하셔도 됩니다.

`restoration_status`에도 스키마에 있는 `NOT_REQUIRED`를 추가했습니다. AI 쪽에 `UNKNOWN`이
enum 값으로 없는 것은 실수가 아니라 설계입니다 — 미확인은 값이 아니라 상태
(`status=UNKNOWN, value=null`)로 표현합니다(팀 결정 2026-09-19). 경계 변환은 OD-04입니다.

**주의:** 위 AI 변경은 아직 원격에 올라가 있지 않습니다. `origin/develop`에는 이전 값이
그대로 있으므로, 원격만 보고 판단하면 여전히 불일치로 보입니다.

## 11. 설정과 환경 파일이 둘로 갈라졌습니다

`origin/develop`(`1f7f9d6`) 기준입니다. 같은 값을 읽는 곳이 두 군데씩 생겼습니다.

| | 루트 | `backend/` |
|---|---|---|
| 설정 클래스 | `config.py` (16개 키) | `backend/app/common/config.py` (7개 키) |
| 예시 파일 | `.env.example` (49개 키) | `backend/.env.example` (7개 키) |

**겹치는 키 5개:** `DATABASE_URL`, `KAKAO_CLIENT_ID`, `KAKAO_CLIENT_SECRET`,
`KAKAO_REDIRECT_URI`, `JWT_SECRET_KEY`

### 문제 셋

**1. 같은 키의 예시 값이 다릅니다.**

| 키 | 루트 `.env.example` | `backend/.env.example` |
|---|---|---|
| `KAKAO_REDIRECT_URI` | `http://localhost:8000/auth/kakao/callback` | `http://localhost:8000/login/callback` |

`backend/app/be/routers/auth.py`에는 `/login/form`과 `/login`만 있고 콜백 경로가 없습니다.
어느 주소가 맞는지, 그 주소를 FE가 받는지 BE가 받는지 알려 주세요. 카카오 앱 설정에
등록하는 값이라 틀리면 로그인 자체가 안 됩니다.

**2. `env_file=".env"`가 상대 경로입니다** (`backend/app/common/config.py:7`).

실행 위치에 따라 다른 파일을 읽습니다 — 저장소 루트에서 실행하면 루트 `.env`, `backend/`에서
실행하면 `backend/.env`입니다. 지금 루트 `.env` 하나에 모든 값이 있고 `backend/.env`는
없으므로, `backend/`에서 띄우면 `KAKAO_CLIENT_ID` 등이 없어 기동에 실패합니다(기본값이 없는
필수 필드입니다).

**3. 값이 갈라지면 조용히 어긋납니다.** 한쪽 `.env`만 고치면 다른 쪽은 옛 값을 계속 씁니다.
같은 `DATABASE_URL`로 AI는 A를, BE는 B를 볼 수 있습니다.

### 요청

- **환경 파일을 하나로 정해 주세요.** 루트 `.env` 하나를 쓰고 `backend/.env.example`을
  없애거나, `backend/` 하나로 옮기고 루트를 없애는 쪽 중 하나입니다. 어느 쪽이든 AI 쪽
  실행 경로(`PYTHONPATH=backend python -m app.agent.cli`)가 같은 파일을 읽어야 합니다.
- 나누기로 한다면 **`env_file`에 절대 경로 또는 저장소 루트 기준 경로**를 쓰고, 겹치는 키 5개를
  어느 쪽이 소유하는지 정해 주세요.
- `docker-compose.yml`과 `backend/Dockerfile`이 어느 파일을 읽는지도 함께 맞춰야 합니다.

AI 쪽은 루트 `.env`를 읽습니다(`config.py`, `app.agent.llm`, `procedure_tool`,
`support_agent` 전부). 옮기기로 하면 AI 코드도 함께 바꾸겠습니다.

**참고:** 루트 `.env`/`.env.example`/`config.py`에서 `REDIS_URL`을 지웠습니다(2026-09-21).
`backend/` 쪽에는 원래 없으니 되살리지 말아 주세요.

---

## 다른 파트에 전달할 것 (AI 소유가 아님)

### PM

- `/CLAUDE.md:133` — `docs/interface-spec.md`를 가리키는데 **그 파일을 삭제했습니다.**
  → `docs/agent/be-integration-requirements.md`로 바꿔주세요
- `docs/hero-scenario.md` — 없는 테이블 이름 2개: `subsidy_application` → `SUPPORT_ITEM_APPLICATION`,
  `support_check_result` → `SUPPORT_MATCH`
- `/CLAUDE.md` "개인정보" 절의 **"테스트는 가짜 데이터로 한다"** 와 이번 작업의 **더미 데이터
  금지** 지시가 문서 수준에서 서로 반대입니다. 지금은 "가짜 Case·사업자·DB 식별자를 만들지
  않는 검사만 실행한다"로 정리하고 `real_data` marker로 갈라 뒀습니다(`backend/tests/conftest.py`).
  팀 기준을 어느 쪽으로 할지 정해 주세요 — 두 문장이 같이 있으면 다음 사람이 또 헷갈립니다

### FE

- `frontend/CLAUDE.md:46`, `frontend/src/pages/ConfirmChangePage.tsx:60`, `frontend/src/mocks/resultFlow.ts:172`
  — `interface-spec.md §5`를 가리킵니다. 그 파일은 삭제됐고 해당 항목은
  [`open-decisions.md`](./open-decisions.md)와 `be-integration-requirements.md` §4로 옮겼습니다

### BE (문서)

- `backend/CLAUDE.md:55-56` — 후속 A7 작업으로 `support_agent/wiki/`에 선택 reader를 추가했습니다.
  A8의 `support_agent/rag/`에는 미검수 공고의 오프라인 검색이 추가됐습니다. 실제 검수 Wiki·S3 연결은 남아 있습니다. 두 경로가 모두
  운영 중인 것으로 설명하지 않도록 현재 상태를 맞춰야 합니다

- `backend/CLAUDE.md:34` — **Redis를 쓰지 않기로 확정했습니다(2026-09-21).** `config.py`의
  `redis_url` 필드, `.env`/`.env.example`의 `REDIS_URL`, `docs/tech-stack.md`의 언급을 모두
  지웠습니다. 저장소 전체에 Redis 참조는 이 한 줄만 남았습니다. "현재 사용처가 없는 선점
  변수"가 아니라 아예 없으므로 문장을 지워 주세요
- `backend/CLAUDE.md:44-56` — 없는 디렉토리를 설명합니다:
  `app/shared/{db,models,schemas,functions}`, `app/api/`.
  실제 모델 위치는 `app/be/models/`이며 Wiki reader와 오프라인 검색은 AI 디렉터리에 추가됐습니다
- (해결) `docs/tech-stack.md`의 Chroma 설명은 AI 소유 문서라 직접 고쳤습니다. 설치 의존성은
  바꾸지 않았고, 별도 미검수 검색 CLI에서만 쓰며 운영 Graph에는 연결하지 않았다고 적었습니다
- `backend/CLAUDE.md:56` — `docs/tech-stack.md §4.4`를 가리키는데 그런 절이 없습니다

### 공동 (논의 필요)

- `case_history.raw_input`이 사용자 발화 원문을 `NOT NULL`로 저장합니다.
  팀 개인정보 원칙과 충돌합니다 — [`open-decisions.md`](./open-decisions.md) OD-05
- 지원금 자격조건을 Wiki에서 읽는지 검수 catalog에서 읽는지 문서가 반대로 적혀 있습니다 — OD-01
- `restoration_scope`·`lease_status`의 확정값은 이번 AI 수정으로 `schema_table.md`에 맞췄습니다.
  테이블에 없는 Case 필드 3개도 제거했습니다. 기존 데이터를 임의 변환하지 않으며,
  BE `to_agent_case_snapshot`과 `UNKNOWN` 경계 처리는 별도 연결이 필요합니다 — OD-04.
- `CASE_COMPLETE`는 AI 내부 타입만 있고 Supervisor·Review가 실제 출력을 거부합니다.
  현재 DB의 `decision_type`에 새 값을 추가하지 않습니다. 전체 완료 판정의 근거·저장 계약은 미완료입니다.
- 버전 제외 메모는 현행 데이터 기준으로 사용하지 않습니다. 스키마대로 버전을 공급·저장하는
  BE 계약이 필요합니다 — OD-11.
