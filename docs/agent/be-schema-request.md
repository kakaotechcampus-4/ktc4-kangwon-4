# BE 스키마 요청서 — 테이블·컬럼·enum

> 작성: AI · 2026-09-21
> 기준: **`origin/develop`의 [`docs/schema/schema_table.md`](../schema/schema_table.md)** (`1f7f9d6`)
> 대조: 실제 MySQL 8.0.46 (2026-09-21 읽기 전용 조회), `origin/develop`의 SQLModel

이 문서는 **BE가 바로 작업할 수 있게** 정리한 것입니다. 배경과 논의는
[`be-requests.md`](./be-requests.md), 미정 사항은 [`open-decisions.md`](./open-decisions.md)에 있습니다.

**전제 두 가지를 먼저 밝힙니다.**

- `schema_table.md`가 절대 기준입니다. 아래 요청은 대부분 **문서에 이미 있는 것을 구현해
  달라는 것**이고, 문서 자체를 바꿔야 하는 건 A-2 하나뿐입니다.
- `CASE.case_version`은 구현하지 않기로 했습니다(2026-09-21 확인). 그래서 생기는 연쇄는 E절에 있습니다.

---

## 한눈에

| 절 | 요청 | 성격 | 급함 |
|---|---|---|---|
| **A-1** | `CASE.restoration_status`에 `UNKNOWN` 추가 + DEFAULT | 문서대로 구현 | **막힘** |
| **A-2** | `CASE.lease_status`를 Case 생성 시 비워둘 수 있게 | **문서 변경 필요** | **막힘** |
| **B** | 없는 테이블 6개 생성 | 문서대로 구현 | 순차 |
| **C-1** | `support_item_application.application_status`의 옛 값 3개 제거 | 문서대로 구현 | 중간 |
| **C-2** | `procedure_step.applicable_business_type`과 `case.business_type` 타입 불일치 | 확인 요청 | 낮음 |
| **D** | `procedure_step` 5개 · `support_item` 2개 컬럼 추가 | 문서대로 구현 | B와 함께 |
| **E** | `case_version` 제외에 따른 세 컬럼 정리 | 문서 정리 | 결정 필요 |

---

## A. 지금 Case를 만들 수 없습니다

두 컬럼 때문에 Hero Scenario Turn 1이 성립하지 않습니다. **다른 것보다 먼저입니다.**

### A-1. `CASE.restoration_status`에 `UNKNOWN`이 없습니다

| | 값 | NULL | DEFAULT |
|---|---|---|---|
| `schema_table.md:60` | `UNKNOWN` / `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` / `NOT_REQUIRED` | NOT NULL | **`UNKNOWN`** |
| 실제 DB | `NOT_STARTED` / `IN_PROGRESS` / `COMPLETED` / `NOT_REQUIRED` | NOT NULL | **없음** |

**문서와 구현이 어긋난 것이라 새 결정이 필요 없습니다.** 문서가 이미
*"Case 생성 직후 `UNKNOWN`으로 시작, `restoration_scope` 확정 후 나머지 값으로 전환"*
이라고 적고 있습니다.

**왜 필요한가.** 사용자는 Turn 1에서 "카페를 접으려고 합니다" 정도만 말합니다. 원상복구를
시작했는지는 그 시점에 아무도 모릅니다. 지금은 넣을 값이 없는데 NOT NULL이라 **행을 만들 수
없습니다.**

**요청:** enum에 `UNKNOWN`을 추가하고 `DEFAULT 'UNKNOWN'`으로 지정해 주세요. SQLModel
(`backend/app/be/models/case.py`)과 실제 DB 양쪽입니다.

> 같은 성격의 옆 컬럼은 이미 그렇게 돼 있습니다 — `restoration_scope`와
> `demolition_required` 둘 다 `UNKNOWN`을 갖고 DEFAULT도 `UNKNOWN`입니다. 이 둘만 빠졌습니다.

### A-2. `CASE.lease_status`는 "모름"을 표현할 방법이 없습니다

| | 값 | NULL | DEFAULT |
|---|---|---|---|
| `schema_table.md:59` | `LEASED_PAID` / `LEASED_FREE` / `OWNED` | NOT NULL | **없음** |
| 실제 DB | 같음 | NOT NULL | 없음 |

문서와 DB가 **일치합니다.** 그래서 이건 구현 누락이 아니라 **기준 자체를 정해야 하는
문제**이고, AI가 단독으로 정하지 않고 건의만 합니다.

**무엇이 문제인가.** 이 칸은 "임대료를 내는가"를 묻습니다. 셋 중 하나를 반드시 넣어야 하는데,
Case를 만드는 시점에 그 답을 아는 경로가 없습니다.

**실측 근거 (2026-09-21, 실제 LLM으로 Graph 실행).**

- **재계획 시나리오 4회가 전부 이 필드에서 막혔습니다.** 안전 실패 결과의
  `requested_field_paths`가 `['lease_status']`를 가리켰습니다.
- Case 생성 시나리오에서도 정보분석은 이 값을 **일관되게 미확인으로 남겼습니다.** 사용자가
  "임대차 계약 기간이 아직 남았는데"라고 말해도 유상인지 무상인지는 그 문장에 없습니다.
  Agent 가드레일이 추정을 막는 것은 **의도된 동작**입니다 — 루트 `CLAUDE.md`의
  "모르는 것을 아는 척하기" 금지에 해당합니다.

**요청:** 둘 중 하나를 정해 주세요.

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **(a)** | enum에 `UNKNOWN` 추가 + `DEFAULT 'UNKNOWN'` | 옆 세 컬럼과 같은 방식, 일관됨 | 문서 수정 필요 |
| **(b)** | 컬럼을 `NULLABLE`로 | AI 내부 표현(`status=UNKNOWN, value=null`)과 가까움 | NOT NULL 전제를 쓰는 곳 확인 필요 |

어느 쪽이든 **AI가 임의로 `LEASED_PAID`를 채워 넣지는 않습니다.** 사용자가 말하지 않은 사실을
만드는 것이기 때문입니다.

**함께 부탁드립니다:** 이 값이 정해지기 전까지 Case 생성 API가 `lease_status`를 필수 입력으로
요구하지 말아 주세요. 요구하면 FE가 첫 화면에서 "임대료를 내십니까"를 물어야 합니다.

---

## B. 없는 테이블 6개

`schema_table.md`에 정의된 17개 중 **6개가 실제 DB에 없습니다.** 전부 구현 예정으로
확인했으므로, 아래는 "왜 필요한지"와 "AI가 무엇을 넣을지"만 정리합니다.
**컬럼 정의는 문서 그대로면 됩니다.**

| 테이블 | AI에서 대응하는 것 | 없으면 무엇이 안 되는가 |
|---|---|---|
| **`EVIDENCE`** | `EvidenceRecord` | **Case 자체를 만들 수 없습니다.** 아래 참조 |
| **`EVIDENCE_LINEAGE`** | `EvidenceRecord.parent_evidence_refs` | 근거에서 파생된 근거의 출처를 잃습니다 |
| **`DECISION_RECORD`** | Supervisor `decision` + `ReviewProof` | 판단과 그 검수 증명을 저장할 곳이 없습니다 |
| **`SUPPORT_MATCH`** | `SupportCheck` | 지원사업 비교 결과를 남길 곳이 없습니다 |
| **`CASE_FIELD_HISTORY`** | `FactChangeCandidate` 적용 결과 | 무엇이 언제 왜 바뀌었는지 못 남깁니다 |
| **`CONFLICT_REFERENCE`** | `ConflictCandidate.conflict_ref` | 충돌 확인(Turn 3) 경로가 성립하지 않습니다 |

### B-1. `EVIDENCE`가 가장 먼저입니다

**이게 없으면 Case에 확정된 사실을 하나도 넣을 수 없습니다.**

`backend/app/agent/schemas.py:363-364`:

```python
if not self.evidence_refs:
    raise ValueError("CONFIRMED fact requires evidence")
```

AI는 "확인된 사실"에 반드시 근거를 요구합니다. 근거를 저장할 테이블이 없으면 Case의 모든
사실이 영원히 미확인으로 남습니다. 서비스가 "무엇을 근거로 그렇게 판단했는지"를 못 밝히게
되고, 이건 루트 `CLAUDE.md`의 "뚫리면 안 되는 선" 5번입니다.

**enum 두 개가 있고, AI 쪽 정의와 이미 정확히 일치합니다.**

| 컬럼 | 값 | 뜻 |
|---|---|---|
| `source_type` | `USER_INPUT` | 사용자가 한 말 |
| | `EXPERT_CONFIRMATION` | 전문가가 확인해 준 것 |
| | `REVIEWED_WIKI` | 사람이 검수한 지원사업 Wiki 노트 |
| | `OFFICIAL_DOCUMENT` | 공식 문서 원문 |
| | `OFFICIAL_API` | 공식 기관 API 응답 |
| | `CALCULATION_RESULT` | 코드가 계산한 값 |
| | `SYSTEM_RECORD` | 시스템이 남긴 기록 |
| `freshness_status` | `CURRENT` / `STALE` / `UNKNOWN` | 이 근거가 아직 최신인지 |

AI의 `EvidenceSourceType`·`FreshnessStatus`가 위와 **글자까지 같습니다.** 변환 없이 그대로
저장·조회하면 됩니다.

> `source_type`을 구분하는 이유: 같은 문장이라도 사용자가 한 말과 공식 문서에 적힌 말은
> 무게가 다릅니다. AI는 금액·날짜·법률·세무·자격 주장에 대해 `OFFICIAL_*` 근거를 요구하고,
> `USER_INPUT`만으로는 단정하지 않습니다. 이 구분이 사라지면 그 규칙이 무너집니다.

### B-2. `SUPPORT_MATCH`

`match_status` enum도 AI의 `SupportMatchStatus`와 **정확히 일치**합니다.

| 값 | 뜻 |
|---|---|
| `POSSIBLY_RELEVANT` | 검토 대상 — 조건이 맞아 보이나 확정 아님 |
| `NEEDS_CONFIRMATION` | 추가 확인 필요 |
| `NOT_RELEVANT` | 해당 없음 |
| `STALE` | 근거가 오래됨 |
| `UNVERIFIABLE` | 확인할 수 없음 |

**"지원 가능"이나 "지원금 수령 확정"에 해당하는 값이 없는 것은 의도입니다.** 팀 원칙상 지원
자격의 최종 판단은 하지 않습니다. 이 enum에 `ELIGIBLE` 같은 값을 추가하지 말아 주세요.

### B-3. 나머지 넷

`DECISION_RECORD`·`CASE_FIELD_HISTORY`·`CONFLICT_REFERENCE`·`EVIDENCE_LINEAGE`는 문서 정의
그대로면 됩니다. 다만 앞 셋은 `case_version` 컬럼을 NOT NULL로 갖고 있어 **E절 결정이
먼저입니다.**

---

## C. enum이 문서와 다른 곳

### C-1. `support_item_application.application_status` — 옛 값 3개가 남아 있습니다

| | 값 | DEFAULT |
|---|---|---|
| `schema_table.md:301` | `NOT_STARTED` / `APPLIED` / `SUPPLEMENT_REQUIRED` / `RESUBMITTED` / `APPROVED` / `REJECTED` | `NOT_STARTED` |
| 실제 DB | **`NOT_CHECKED` / `ELIGIBLE` / `NOT_ELIGIBLE`** + `APPLIED` / `SUPPLEMENT_REQUIRED` / `RESUBMITTED` / `APPROVED` / `REJECTED` | `NOT_CHECKED` |

문서에 없는 3개가 DB에 남아 있고, 문서의 `NOT_STARTED`는 DB에 없습니다.

**왜 그냥 두면 안 되는가.** 이 컬럼은 **신청이 어디까지 갔는지**(신청 생명주기)를 담는
자리입니다. 그런데 남아 있는 `ELIGIBLE`·`NOT_ELIGIBLE`은 **자격이 되는지**를 뜻합니다.
성격이 다른 두 가지가 한 칸에 섞여 있습니다.

더 중요한 것은, `ELIGIBLE`이 저장 가능한 값으로 남아 있으면 **"이 사장님은 지원 자격이
있다"가 DB에 기록될 수 있다**는 점입니다. 팀이 하지 않기로 한 판단입니다. 자격 관련 표현은
`SUPPORT_MATCH.match_status`의 "검토 대상 / 추가 확인 필요"로만 다룹니다.

**요청:** `NOT_CHECKED`·`ELIGIBLE`·`NOT_ELIGIBLE`을 제거하고 `NOT_STARTED`를 추가한 뒤
DEFAULT를 `NOT_STARTED`로 바꿔 주세요. 현재 이 테이블은 0행이라 데이터 이전이 필요 없습니다.

### C-2. `procedure_step.applicable_business_type`과 `case.business_type`의 타입이 다릅니다

| 컬럼 | 타입 | 현재 값 |
|---|---|---|
| `case.business_type` | `VARCHAR(50)` | 자유 문자열, 문서 예시는 한글 `"카페"` |
| `procedure_step.applicable_business_type` | `ENUM` | `ALL`, **`CAFE`** |

같은 "업종"인데 한쪽은 자유 문자열 한글, 한쪽은 enum 영문입니다. 나중에 "이 절차가 이
사업자에게 해당하는가"를 맞춰볼 때 `"카페"`와 `CAFE`를 비교하게 됩니다.

**요청:** 둘을 어떻게 맞출지 정해 주세요. 급하지는 않지만 절차 데이터를 넣기 전에는
정해져야 합니다. AI는 현재 `business_type`을 자유 문자열로 다루고 있으며(문서 기준),
실제로 사용자 발화에서 `"작은 카페"` 같은 값을 추출합니다.

---

## D. 없는 컬럼

### D-1. `PROCEDURE_STEP` — 5개

| 컬럼 | 급함 | AI가 왜 필요한가 |
|---|---|---|
| `step_name` | **필수** | 아래 참조 |
| `utterance_aliases` | **필수** | 아래 참조 |
| `registry_version` | 보통 | 어느 시점 절차 목록을 썼는지 |
| `deprecated_at` | 보통 | 폐지된 절차를 구분 |
| `replaced_by_procedure_step_id` | 보통 | 대체된 절차 추적 |

**앞 두 개가 없으면 사용자 말을 절차에 연결할 수 없습니다.**

`backend/app/agent/schemas.py:594-597`:

```python
class KnownProcedureStep(AgentSchema):
    procedure_step: ProcedureStepRef
    step_name: NonEmptyStr          # 필수
    utterance_aliases: list[NonEmptyStr]
```

사용자는 "폐업신고 했어요"라고 말하지 `FILE_TAX_BUSINESS_CLOSURE`라고 말하지 않습니다.
`step_name`("사업자등록 폐업신고")과 `utterance_aliases`(["폐업신고", "홈택스 폐업"])가
그 둘을 잇습니다. 지금은 `step_code`만 있어 연결할 방법이 없습니다.

2026-09-21 Graph 실행에서는 이 값을 **AI가 임시로 만들어 넣어야 했습니다.** 실제 운영에서는
그럴 수 없습니다 — 절차 이름은 팀이 검수할 대상이지 AI가 지어낼 것이 아닙니다.

### D-2. `SUPPORT_ITEM` — 2개

| 컬럼 | AI가 왜 필요한가 |
|---|---|
| `external_notice_id` | 기업마당 공고 ID(`PBLN_000000000117676`)입니다. 지금 수집한 9건은 이 ID로만 식별되며, DB의 `id`/`uuid`와 잇는 유일한 열쇠입니다 |
| `catalog_version` | 어느 시점 지원사업 목록을 비교에 썼는지 남깁니다. 공고는 수정공고가 자주 나옵니다 |

`SUPPORT_ITEM.uuid`는 이미 있습니다. AI의 Wiki 조회는 `support_program_id`(DB `id`)와
`wiki_uuid`(DB `uuid`) 쌍을 **정확히 일치**로만 찾습니다(`schemas.py:340-342`).

---

## E. `case_version`을 빼면 세 컬럼이 참조 대상을 잃습니다

`CASE.case_version`을 구현하지 않기로 했는데, `schema_table.md`는 그 컬럼을
`NOT NULL, DEFAULT 1`로 정의하고 **다른 세 테이블이 그 값을 NOT NULL로 담도록** 돼 있습니다.

| 테이블 | 컬럼 | 문서 설명 |
|---|---|---|
| `CASE_FIELD_HISTORY` | `resulting_case_version` | "변경 결과로 생성된 `case_version`" |
| `CONFLICT_REFERENCE` | `case_version` | "대상 케이스 시점 버전" |
| `DECISION_RECORD` | `case_version` | "대상 케이스 시점 버전" |

셋 다 B절의 "만들어야 할 테이블"입니다. **만들 때 이 칸에 넣을 값이 없습니다.**

**요청 두 가지.**

1. `schema_table.md`에서 `CASE.case_version`을 빼고 위 세 컬럼도 함께 정리해 주세요.
   문서와 결정이 어긋난 채로 두면 다음 사람이 같은 질문을 다시 합니다.
2. **동시 수정 충돌을 무엇으로 막을지** 정해 주세요. 원래 이 컬럼의 용도입니다. 두 사람이
   같은 Case를 동시에 고칠 때 나중 것이 앞의 것을 조용히 덮어쓰는 문제이며, 충돌
   확인(C6) 경로가 이 값을 쓰기로 돼 있습니다.

AI 쪽은 `case_version`을 선택 값(`int | None`)으로 다뤄 없어도 동작합니다. 2026-09-21 Graph
실행도 `case_version=null`로 통과했습니다. **AI가 임의의 버전을 만들어 넣지는 않습니다.**

---

## 우선순위

1. **A-1, A-2** — 이게 풀려야 Case가 만들어지고 Hero Loop Turn 1이 성립합니다
2. **E** — B절 테이블 셋의 컬럼이 여기 달려 있습니다
3. **B-1 `EVIDENCE`** — 확정된 사실을 저장하려면 먼저입니다
4. **D-1 `step_name`·`utterance_aliases`** — 절차 데이터를 넣기 전에
5. B 나머지, C-1, D-2
6. C-2

## 끝났는지 어떻게 아는가

AI 쪽에서 확인할 수 있는 것만 적습니다.

| 절 | 확인 방법 |
|---|---|
| A-1·A-2 | 임대 형태와 복구 상태를 모르는 상태로 Case 행이 만들어진다 |
| B-1 | `EVIDENCE`에 저장한 근거를 `evidence_refs`로 참조하는 `CONFIRMED` 사실이 AI 입력 검증을 통과한다 |
| D-1 | "폐업신고 했어요" 같은 발화가 실제 `PROCEDURE_STEP` 행에 연결된다 |
| D-2 | 수집한 공고 9건이 실제 `SUPPORT_ITEM.id`/`uuid`와 이어지고 Wiki 조회가 HIT를 낸다 |
| C-1 | `ELIGIBLE`을 저장하려는 시도가 DB에서 거부된다 |
| E | `DECISION_RECORD` 한 건이 버전 값 없이 저장되고 다시 읽힌다 |

## 요청하지 않는 것

- **새 테이블·새 컬럼을 만들어 달라고 하지 않습니다.** 위 전부가 `schema_table.md`에 이미
  있거나(A-1, B, C-1, D), 기존 컬럼의 제약을 바꾸는 것(A-2)이거나, 문서 정리(E)입니다.
- 지원 자격을 담는 컬럼을 만들지 말아 주세요. AI는 자격을 확정하지 않습니다.
- `DECISION_RECORD.decision_type`에 새 값을 추가하지 말아 주세요. AI의 `CASE_COMPLETE`는
  현재 Supervisor와 Review가 거부하는 내부 타입입니다.
