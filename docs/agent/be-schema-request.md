# BE 스키마 요청서

> 작성: AI · 2026-09-21 (2판)
> 기준: **`origin/develop`의 [`docs/schema/schema_table.md`](../schema/schema_table.md)** (`1f7f9d6`)

**`schema_table.md`에 있는 것은 BE가 구현할 예정으로 확인했습니다. 그래서 이 문서는
"거기에 없어서 결정이 필요한 것"만 담습니다.**

1판에서 이미 문서에 있는 항목들(없는 테이블 6개, `restoration_status`의 `UNKNOWN`,
`procedure_step`·`support_item`의 없는 컬럼, `application_status` enum)까지 적었는데
**요청할 이유가 없는 것들이었습니다.** 문서대로 구현하면 그대로 풀립니다. 뺐습니다.

---

## 1. 판단과 근거를 잇는 곳이 없습니다 — 새 표 필요

**문제.** `EVIDENCE` 표는 있는데, **어느 판단이 어느 근거를 썼는지** 기록할 곳이 없습니다.

`schema_table.md` 전체에서 `EVIDENCE`를 가리키는 컬럼은 `EVIDENCE_LINEAGE`(근거끼리의
파생 관계) 하나뿐입니다. 아래 표 전부 근거 참조 컬럼이 없습니다.

| 표 | 근거 참조 |
|---|---|
| `DECISION_RECORD` | 없음 |
| `BLOCKER` | 없음 |
| `CASE_FIELD_HISTORY` | 없음 (`source`·`reason`이 그냥 문자열) |
| `SUPPORT_MATCH` | 없음 |
| `CONFLICT_REFERENCE` | 없음 |
| `CASE_HISTORY` | 없음 |

**왜 필요한가.** `EVIDENCE.case_id`가 있어 *"이 Case에 근거 20건이 있다"*까지는 압니다.
그런데 *"이 판단이 그중 어느 3건을 썼는지"*를 모릅니다.

사용자가 "왜 이걸 먼저 하라는 거죠?"라고 물으면 답할 수 없습니다. 루트 `CLAUDE.md`의
"뚫리면 안 되는 선" 5번 — **"왜 그 판단이 나왔는지 못 밝히는 상태"** 가 그대로 됩니다.

AI 쪽은 25개 모델이 `evidence_refs`를 들고 있습니다(`Blocker`, `NextAction`, `CaseFact`,
`SupportCheck`, `ProcedureFinding` 등). 저장하는 순간 그 연결이 버려집니다.

**왜 컬럼이 아니라 표인가.** 판단 하나가 근거 여럿을 쓰고, 근거 하나가 판단 여럿에 쓰입니다.
다대다입니다. `EVIDENCE_LINEAGE`가 근거끼리의 다대다를 같은 방식으로 풀고 있습니다.

**요청.** 연결 표 하나를 추가해 주세요. 형태는 BE 판단에 맡깁니다. 예시:

```
DECISION_EVIDENCE
  decision_record_id  BIGINT  FK -> DECISION_RECORD.id   (복합 PK)
  evidence_id         BIGINT  FK -> EVIDENCE.id          (복합 PK)
```

`BLOCKER`·`SUPPORT_MATCH`·`CASE_FIELD_HISTORY`의 근거도 같은 문제라, 표를 하나로 둘지
대상별로 나눌지는 함께 정해 주시면 AI 쪽이 맞추겠습니다.

---

## 2. `CASE.lease_status`에 "모름"이 없습니다 — 문서 변경 필요

| | 값 | NULL | DEFAULT |
|---|---|---|---|
| `schema_table.md:59` | `LEASED_PAID` / `LEASED_FREE` / `OWNED` | NOT NULL | 없음 |
| 실제 DB | 같음 | NOT NULL | 없음 |

문서와 구현이 **일치합니다.** 그래서 이건 구현 문제가 아니라 **기준을 바꿔야 하는 문제**이고,
AI가 단독으로 정하지 않습니다.

**왜 필요한가.** Turn 1에서 사용자는 "카페를 접으려고 합니다" 정도만 말합니다. 임대료를
내는지는 그 시점에 모릅니다. 셋 중 하나를 반드시 넣어야 하는데 넣을 값이 없어 **행을 만들 수
없습니다.**

실측: 정보분석은 이 값을 일관되게 미확인으로 남깁니다. "임대차 계약 기간이 아직 남았는데"
라는 말에는 유상/무상이 없고, 가드레일이 추정을 막는 것은 의도된 동작입니다.

> 참고: **Agent 실행 자체는 이 값 없이도 됩니다.** 2026-09-21 확인 — `lease_status`를 모르는
> 상태로 `REVIEWED_PLAN`까지 통과합니다. 막히는 것은 저장 층뿐입니다.

**요청.** 둘 중 하나를 정해 주세요.

| 안 | 내용 | 비고 |
|---|---|---|
| **(a)** | enum에 `UNKNOWN` 추가 + DEFAULT | `restoration_scope`·`demolition_required`와 같은 방식 |
| **(b)** | `NULLABLE`로 | AI 내부 표현(`status=UNKNOWN, value=null`)과 가까움 |

어느 쪽이든 **AI가 임의로 `LEASED_PAID`를 채우지는 않습니다.**

**함께:** 정해지기 전까지 Case 생성 API가 이 값을 필수로 요구하지 말아 주세요. 요구하면 FE가
첫 화면에서 "임대료를 내십니까"를 물어야 합니다.

---

## 3. `case_version`을 빼면 세 컬럼이 참조 대상을 잃습니다 — 문서 정리 필요

`CASE.case_version`은 구현하지 않기로 했습니다(2026-09-21). 그런데 `schema_table.md`는
그 컬럼을 `NOT NULL, DEFAULT 1`로 정의하고, **다른 세 표가 그 값을 NOT NULL로 담습니다.**

| 표 | 컬럼 |
|---|---|
| `CASE_FIELD_HISTORY` | `resulting_case_version` |
| `CONFLICT_REFERENCE` | `case_version` |
| `DECISION_RECORD` | `case_version` |

셋 다 구현 대상이라 **만들 때 넣을 값이 없습니다.**

**요청.**
1. `schema_table.md`에서 `CASE.case_version`을 빼고 위 세 컬럼도 함께 정리해 주세요.
2. 동시 수정 충돌을 무엇으로 막을지 정해 주세요. 원래 이 컬럼의 용도이고, 충돌 확인(C6)
   경로가 이 값을 쓰기로 돼 있습니다.

AI 쪽은 이 값을 선택 값(`int | None`)으로 다뤄 없어도 동작합니다. 실제 실행도
`case_version=null`로 통과했습니다.

---

## 4. 업종을 담는 두 컬럼의 타입이 다릅니다 — 확인 요청

| 컬럼 | 타입 | 값 |
|---|---|---|
| `case.business_type` | `VARCHAR(50)` | 자유 문자열, 문서 예시는 한글 `"카페"` |
| `procedure_step.applicable_business_type` | `ENUM` | `ALL`, `CAFE` |

같은 "업종"인데 한쪽은 한글 자유 문자열, 한쪽은 영문 enum입니다. "이 절차가 이 사업자에게
해당하는가"를 맞출 때 `"카페"`와 `CAFE`를 비교하게 됩니다.

급하지는 않지만 **절차 데이터를 넣기 전에** 정해져야 합니다. AI는 문서 기준대로
`business_type`을 자유 문자열로 다루며, 실제로 사용자 발화에서 `"작은 카페"`를 추출합니다.

---

## 요청하지 않는 것

- **`schema_table.md`에 있는 것은 요청하지 않습니다.** 없는 테이블 6개(`EVIDENCE`,
  `EVIDENCE_LINEAGE`, `DECISION_RECORD`, `CONFLICT_REFERENCE`, `CASE_FIELD_HISTORY`,
  `SUPPORT_MATCH`), 없는 컬럼 7개, `restoration_status`의 `UNKNOWN`,
  `application_status` enum 차이 — 전부 문서대로 구현하면 풀립니다.
- 지원 자격을 담는 컬럼을 만들지 말아 주세요. AI는 자격을 확정하지 않습니다.
  자격 관련 표현은 `SUPPORT_MATCH.match_status`의 "검토 대상 / 추가 확인 필요"로만 다룹니다.
- `DECISION_RECORD.decision_type`에 새 값을 추가하지 말아 주세요.

## AI 쪽 enum은 이미 맞습니다

구현하실 때 변환 코드가 필요 없습니다. 아래 셋은 AI 정의와 **글자까지 같습니다.**

| 컬럼 | 값 |
|---|---|
| `EVIDENCE.source_type` | `USER_INPUT` / `EXPERT_CONFIRMATION` / `REVIEWED_WIKI` / `OFFICIAL_DOCUMENT` / `OFFICIAL_API` / `CALCULATION_RESULT` / `SYSTEM_RECORD` |
| `EVIDENCE.freshness_status` | `CURRENT` / `STALE` / `UNKNOWN` |
| `SUPPORT_MATCH.match_status` | `POSSIBLY_RELEVANT` / `NEEDS_CONFIRMATION` / `NOT_RELEVANT` / `STALE` / `UNVERIFIABLE` |
