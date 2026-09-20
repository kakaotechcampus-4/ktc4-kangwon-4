# BE에 요청하는 것

> 소유: AI · 기준일: 2026-09-19 · 기준: `develop` (`e360ab3`)와 `docs/schema/ERD.png`
>
> 이 문서의 책임: **Agent가 동작하려면 필요한데 AI가 고칠 수 없는 것**만 모읍니다.

배경 계약과 논의 항목은 [`be-integration-requirements.md`](./be-integration-requirements.md)에 있습니다.
여기는 그중 **지금 바로 막고 있는 것**만 짧게 추립니다.

멘토 재리뷰(2026-09-19)에서 "DDL이나 SQLModel 클래스 아직 반영되지 않은 건들이 있으니 확인 후
구현 요청드립니다"라고 하신 부분이 1번입니다.

---

## 1. SQLModel이 ERD보다 뒤처져 있습니다

ERD와 `docs/schema/schema_table.md`에는 있는데 `backend/app/be/models/`에 없습니다.

**컬럼**

| 테이블 | 없는 컬럼 | Agent가 왜 필요한가 |
|---|---|---|
| `case` | `case_version` | 저장 직전 값이 바뀌었는지 확인하는 기준입니다. 없으면 오래된 판단으로 덮어쓰는 걸 막을 수 없습니다 |
| `procedure_step` | `step_name`, `utterance_aliases`, `registry_version`, `deprecated_at`, `replaced_by_procedure_step_id` | 앞 두 개는 **필수**입니다. Agent가 사용자 말을 절차 단계에 연결할 때 표시명과 별칭으로 맞춥니다(`schemas.py`의 `KnownProcedureStep`). 지금은 `step_code`만 있어서 연결할 수가 없습니다 |

**테이블 (클래스 자체가 없음)**

`evidence`, `evidence_lineage`, `conflict_reference`, `decision_record`, `case_field_history`, `support_match`

이 중 MVP에 꼭 필요한 건 **근거 저장**입니다. 다만 멘토가 "MVP 단계에서 MySQL에 구조화된 방식으로
저장하는 것은 필수가 아니다, evidence가 포함된 llm 응답을 json 형식으로 저장해두는 것만으로도
evidence 추적이 이미 동작한다"고 하셨으니 **3번 방식으로 갈음할 수 있습니다.**

## 2. 절차 원문의 출처를 담을 자리가 없습니다

`procedure_step`에는 담당기관·기한규칙·필요서류·주의사항이 있는데,
**"이 내용을 어느 공식 문서에서 언제 가져왔고 원문이 무엇이었는지"**가 없습니다.

Agent는 기한이나 서류를 말할 때 반드시 근거(URL·발췌·해시·수집시각)를 함께 내야 하고,
근거가 없으면 Review Tool이 막습니다. 그래서 이 자리가 없으면 절차를 DB에서 읽어도
**"확인 필요"로만 답할 수 있습니다.**

`evidence` 테이블이 딱 그 모양인데 `case_id`가 붙어 있어 **케이스 전용**입니다.
절차 원문은 모든 케이스가 공유하는 자료라 케이스마다 복제해야 합니다.

셋 중 하나면 됩니다. **BE가 편한 쪽으로 정해주세요.**

1. `evidence.case_id`를 nullable로 — 케이스에 속하지 않는 공용 근거를 허용
2. `procedure_step`에 출처 컬럼 추가 — `source_url`, `source_excerpt`, `content_hash`, `retrieved_at`, `reviewed_by`, `reviewed_at`
3. 절차 원문 전용 테이블 1개

현재 AI 쪽은 이 데이터를 JSON 스냅샷으로 들고 있습니다
(`backend/app/agent/procedure_tool/data/reviewed-procedures.ko-KR.json`).
읽는 통로가 한 겹 분리돼 있어서, 위가 정해지면 **그 통로 구현만 바꾸면 됩니다.**
자세한 구조는 [`procedure-knowledge.md`](./procedure-knowledge.md)에 있습니다.

## 3. 판단 결과를 통째로 저장할 자리 (근거·판단기록 대안)

멘토 답변에 따른 **MVP 최소안**입니다. 구조화 테이블 대신 이것만 있어도 됩니다.

- `decision_record`(또는 `case_history`)에 **JSON 컬럼 1개**
- 거기에 Agent가 돌려준 `REVIEWED_PLAN` 결과를 그대로 넣습니다

Agent 결과에는 이미 **판단·검수 대상·근거가 전부 닫힌 형태로** 들어 있습니다
(`ReviewSubject` + `ReviewProof` + evidence 집합). 따로 조립할 필요가 없습니다.

`decision_record`와 `evidence`를 잇는 매핑이 ERD에 없다고 하신 부분도 이걸로 해소됩니다 —
매핑을 만드는 대신 **판단 하나를 근거까지 통째로 한 덩어리로 저장**하는 방식입니다.

## 4. enum에서 `UNKNOWN`을 빼주세요

팀 결정(2026-09-19)입니다. **미확인은 값이 아니라 상태입니다.**

- 대상: `case.restoration_status`, `case.restoration_scope`, `case.demolition_required`
- 지금은 `UNKNOWN`이 enum 값이자 기본값입니다 (`backend/app/be/models/case.py`)
- 요청: 값 집합에서 빼고, 미확인은 `NULL` + 확인 상태로 표현

Agent는 이미 이 방식입니다 — 값은 typed 값이거나 `null`이고, 확인 여부는 따로 표현합니다.

**기본값이 바뀌는 변경이라 BE 판단이 필요합니다.** 마이그레이션 비용이 크면
`UNKNOWN`을 두되 Agent 경계에서 `null`로 변환하는 방법도 있습니다. 다만 그 변환 규칙은
adapter가 임의로 정하면 안 되고 합의가 필요합니다.

## 5. `sqlmodel`이 `backend/requirements.txt`에 없습니다

`backend/app/be/models/`의 모든 모델이 `from sqlmodel import ...`를 하는데
requirements 세 파일 어디에도 고정돼 있지 않습니다.
깨끗한 환경에서 `pip install -r backend/requirements.txt`만 하면 `app.be.models`를 import할 수 없습니다.

(`backend/requirements.txt`는 BE 소유라 직접 고치지 않았습니다. 현재 venv에는 `0.0.42`가 설치돼 있습니다.)

## 6. `procedure_step`에 행을 넣을 방법이 없습니다

Alembic 설정도, seed 스크립트도, SQL 파일도 없습니다.
1·2번이 정리돼도 **데이터를 넣는 경로**가 있어야 Agent가 DB에서 절차를 읽을 수 있습니다.

---

## 다른 파트에 전달할 것 (AI 소유가 아님)

### PM

- `/CLAUDE.md:133` — `docs/interface-spec.md`를 가리키는데 **그 파일을 삭제했습니다.**
  → `docs/agent/be-integration-requirements.md`로 바꿔주세요
- `docs/hero-scenario.md` — 없는 테이블 이름 2개: `subsidy_application` → `SUPPORT_ITEM_APPLICATION`,
  `support_check_result` → `SUPPORT_MATCH`

### FE

- `frontend/CLAUDE.md:46`, `frontend/src/pages/ConfirmChangePage.tsx:60`, `frontend/src/mocks/resultFlow.ts:172`
  — `interface-spec.md §5`를 가리킵니다. 그 파일은 삭제됐고 해당 항목은
  [`open-decisions.md`](./open-decisions.md)와 `be-integration-requirements.md` §4로 옮겼습니다

### BE (문서)

- `backend/CLAUDE.md:55-56` — `support_agent/wiki/`, `support_agent/rag/`를 있는 것처럼
  설명하지만 **둘 다 존재하지 않습니다.** 지원사업 자격은 검수 카탈로그로 비교하고 있고,
  Wiki·RAG는 구현 0입니다

- `backend/CLAUDE.md:44-56` — 없는 디렉토리를 설명합니다:
  `app/shared/{db,models,schemas,functions}`, `app/api/`, `support_agent/wiki/`, `support_agent/rag/`.
  실제 위치는 `app/be/models/`이고 wiki·rag는 구현되지 않았습니다
- `backend/CLAUDE.md:56` — `docs/tech-stack.md §4.4`를 가리키는데 그런 절이 없습니다

### 공동 (논의 필요)

- `case_history.raw_input`이 사용자 발화 원문을 `NOT NULL`로 저장합니다.
  팀 개인정보 원칙과 충돌합니다 — [`open-decisions.md`](./open-decisions.md) OD-05
- 지원금 자격조건을 Wiki에서 읽는지 검수 catalog에서 읽는지 문서가 반대로 적혀 있습니다 — OD-01
