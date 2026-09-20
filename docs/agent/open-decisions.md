# Agent 미정 사항 대장

> 소유: AI · 기준일: 2026-09-20 · 기준 브랜치: `develop`
>
> 이 문서의 책임: **무엇이 아직 안 정해졌는지**를 한 곳에 모으는 것.
> 멘토 리뷰(PR #14, 2026-09-19) 요청 사항입니다.

문서마다 "미구현"과 "미정"이 섞여 있어서 읽는 사람이 무엇을 믿어야 할지 알기 어려웠습니다.
그래서 **결정 대기 항목은 전부 여기로 모읍니다.** 다른 문서는 이 파일을 가리키기만 합니다.

## 읽는 법

| 칸 | 뜻 |
|---|---|
| **누가 남긴 미정인가** | `검토됨` = 담당자나 멘토가 실제로 보고 판단을 미룬 것 / `문서에만 있음` = 설계하며 적어둔 뒤 아무도 검토하지 않은 것 |
| **MVP** | `필수` = MVP 전에 정해야 함 / `연기 가능` = 정하지 않아도 MVP가 돌아감 |
| **누가 정하나** | `AI 단독` / `BE 단독` / `공동` |
| **결정 전 안전 기본값** | 정해지기 전까지 코드가 취하는 동작. 이게 있으면 미정 상태로도 안전하게 돌아갑니다 |

"미구현"은 미정이 아닙니다. 무엇이 구현됐고 무엇이 안 됐는지는 [`architecture.md`](../architecture.md) §8을 보세요.

---

## 1. 이번 리뷰로 결정된 것

더 논의하지 않습니다. 근거와 함께 남깁니다.

| 항목 | 결정 | 근거 |
|---|---|---|
| 절차 지식 출처 | MVP는 **미리 저장·검수한 절차만** 서비스. 요청 경로에서 인터넷 조회 안 함 | 멘토 리뷰 2번. 구현은 [`procedure-knowledge.md`](./procedure-knowledge.md) |
| 실행당 LLM 호출 상한 | **40회 유지.** 실측하며 조정 | 멘토: "값은 판단하신대로 픽스하고 40회로 테스트해보시길 권고" |
| 전체 실행 시간 상한 | **60초.** `AGENT_RUN_DEADLINE_SECONDS`로 조정 | 멘토 권고값. 실측은 [`runtime-limits.md`](./runtime-limits.md) |
| Supervisor 모델 분리 | `SUPERVISOR_*` 환경변수로 분리 가능. 미설정 시 공용 설정 | 멘토: "비싼 모델에서 저렴한 모델로 테스트하는 방향" |
| Evidence·판단기록 저장 구조 | MVP는 **판단 결과 JSON을 통째로 저장**해도 됨. 구조화는 MVP 이후 | 멘토 재리뷰: "evidence가 포함된 llm 응답을 json 형식으로 저장해두는 것만으로도 evidence 추적이 이미 동작합니다" |
| 정규식 가드레일 고도화 | **MVP 이후.** 설계·구현 그대로 둠 | 멘토: "설계 및 구현 모두 그대로 두시고 MVP 릴리즈 이후에 필요하다면 고도화" |
| Guardrail 위치 | **Agent 안.** 저장 직전 version·소유권 확인만 BE | 팀 결정(2026-09-19). `be-integration-requirements.md` §5.5를 이에 맞게 정정함 |
| enum에 `UNKNOWN` | **넣지 않음.** 미확인은 값이 아니라 상태(`status=UNKNOWN`, `value=null`) | 팀 결정(2026-09-19). Agent는 이미 이 방식. DB 쪽 정리는 [`be-requests.md`](./be-requests.md) 4번 |
| 실행 단위 예산·시간 격리 | contextvar로 실행마다 분리 | 동시 요청에서 카운터가 섞이는 문제. `run_scope.py`, `llm.py` |
| 모델이 근거 ID를 틀리게 쓰던 문제 | 고를 수 있는 값을 요청 스키마에서 닫아 provider가 그 밖을 생성하지 못하게 함 | 검증으로 걸러내면 생성 한 번과 예산이 이미 날아간 뒤다. 멘토 리뷰 1번의 "응답 전에 후보를 추리는" 방향. 로컬 검증은 그대로 돈다 |
| Review가 "아직 모른다"는 Blocker에 근거를 요구하던 문제 | `NEEDS_MORE_INFO` 결정의 Blocker는 근거 요구 대상에서 제외 | 모르는 것을 증명하는 근거는 없다. Case의 해당 fact가 `UNKNOWN`인 것이 그 근거다. 금액·날짜·법률·세무·자격 주장이 섞이면 제외하지 않는다 |
| 충돌 확인 후 재계획 | 확인된 값도 Review를 거치는 `CONFLICT_CONFIRMED` 경로로 구현 | 확인을 바로 저장하면 Case 변경이 Review를 건너뛴다. 그 사이 값이 바뀌었으면 덮어쓰지 않고 `STALE_CONFLICT_CONFIRMATION`으로 끝낸다 |

---

## 2. 아직 정해지지 않은 것

### OD-01 · 지원금 지식을 어디서 읽는가

- **미정인 내용:** 지원사업 자격조건을 **LLM Wiki(Obsidian)**에서 읽는가, 코드가 주입한 **검수 catalog**에서 읽는가
- **누가 남긴 미정인가:** **문서에만 있음.** 아무도 이 충돌을 안건으로 올린 적이 없습니다
- **쟁점:** 문서 두 갈래가 **서로 반대**입니다
  - Wiki 쪽: `../schema/schema_table.md`(SUPPORT_ITEM이 uuid로 Wiki와 매핑, "판정은 LLM+Wiki가 담당"), `backend/CLAUDE.md:55-56`, `../hero-scenario.md:49`
  - catalog 쪽: `../architecture.md` §3.2, [`official-data-sources.md`](./official-data-sources.md) §8 ("RAG 유사도만으로 `ELIGIBLE`을 만들지 않는다")
  - 코드에는 `support_agent/wiki/`도 `support_agent/rag/`도 **없습니다.** 실제로는 catalog 방식만 구현돼 있습니다
- **MVP:** **필수.** SUPPORT_ITEM 스키마와 검수 절차가 여기서 갈립니다
- **누가 정하나:** **공동** (AI·BE·PM)
- **2026-09-20 경과:** 카탈로그 쪽 경로를 구현했다. 기업마당에서 실제 공고 7건을 찾아왔고,
  사람이 자격조건을 써 넣기 전까지는 서비스되지 않는다([`support-knowledge.md`](./support-knowledge.md)).
  Wiki·RAG는 여전히 구현 0이다 — `support_agent/wiki/`도 `rag/`도 없고 결과의 `wiki_lookup`은
  항상 `NOT_REQUESTED`다. **이 결정이 나야 Wiki를 만들지 말지가 정해진다**
- **결정 전 안전 기본값:** 검수된 카탈로그만 비교에 쓴다. 검수된 항목이 없으면 "후보 없음"으로 끝낸다

### OD-02 · 절차 스냅샷을 언제 갱신하는가

- **미정인 내용:** 갱신 주기(수동 / 매일 00시 배치 / 릴리즈마다)와 누가 검수하는가
- **누가 남긴 미정인가:** **검토됨.** 멘토가 "fetch에 대해서는 MVP 이후에 결정해도 늦지 않습니다"라고 명시
- **쟁점:** 자동 갱신은 검수 없이 반영될 위험이 있고, 수동은 오래된 자료를 계속 쓸 위험이 있음
- **MVP:** **연기 가능**
- **누가 정하나:** **AI 단독** (스케줄러를 붙이면 BE와 공동)
- **결정 전 안전 기본값:** 수동 갱신. 검수 안 된 자료는 `UNKNOWN`으로 나가고 Review가 단정을 막음

### OD-03 · `runId`와 deadline을 누가 만드는가

- **미정인 내용:** Agent가 내부 생성할지, BE coordinator가 주입할지
- **누가 남긴 미정인가:** **문서에만 있음** (`be-integration-requirements.md` §4)
- **쟁점:** BE에 자체 gateway timeout이 있으면 상한이 두 개가 되어 어느 쪽이 먼저 끊을지 모호해짐
- **MVP:** **필수** (BE 연동 시)
- **누가 정하나:** **공동**
- **결정 전 안전 기본값:** `runId`는 Agent가 생성. deadline은 Agent 기본 60초이되 `run_planning(deadline_seconds=...)`로 호출자가 덮어쓸 수 있음

### OD-04 · Case 필드 enum 값 집합

- **미정인 내용:** `lease_status`, `restoration_scope`의 값 집합이 DB와 Agent에서 다름
  - `lease_status` — DB `LEASED_PAID|LEASED_FREE|OWNED` / Agent `ACTIVE|TERMINATION_NOTIFIED|TERMINATED|OWNED`
  - `restoration_scope` — DB `PARTIAL|FULL|NOT_REQUIRED` / Agent `AGREEMENT_REQUIRED|TENANT_ALL|LANDLORD_ALL|SHARED|NOT_REQUIRED`
- **누가 남긴 미정인가:** **검토됨** (`be-integration-requirements.md` §4에 명시적으로 올려둠)
- **쟁점:** 어느 쪽을 공통 기준으로 삼을지. adapter에서 임의로 변환하면 안 됨
- **MVP:** **필수**
- **누가 정하나:** **공동**
- **결정 전 안전 기본값:** 변환하지 않음. 실제 Case 연동 전까지 합성 fixture만 사용
- 참고: `UNKNOWN`을 값으로 둘지는 **결정됐습니다**(§1). 이 항목은 나머지 값 집합 얘기입니다

### OD-05 · `CASE_HISTORY.raw_input`에 사용자 발화 원문을 저장하는가

- **미정인 내용:** 사용자가 말한 문장을 그대로 DB에 남길지
- **누가 남긴 미정인가:** **문서에만 있음.** 스키마에는 이미 `NOT NULL`로 들어가 있고 아무도 이견을 낸 적이 없습니다
- **쟁점:** 팀 원칙(`/CLAUDE.md` "개인정보")과 `be-integration-requirements.md` §7-8이 **원문 PII 복제를 금지**합니다. 폐업 상담 발화에는 상호·주소·금액이 섞여 들어옵니다
- **MVP:** **필수** (보안)
- **누가 정하나:** **공동**
- **결정 전 안전 기본값:** Agent는 비식별 텍스트(`RedactedInput`)만 받고 원문을 저장·전송하지 않음

### OD-06 · `CASE` 예약어

- **미정인 내용:** MySQL 예약어인 테이블명 `CASE`를 `CASES`로 바꿀지, quoting 규칙을 강제할지
- **누가 남긴 미정인가:** **문서에만 있음** (`be-integration-requirements.md` §7-1)
- **쟁점:** migration 후에 바꾸면 비용이 큼
- **MVP:** **필수** (migration 전)
- **누가 정하나:** **BE 단독**
- **결정 전 안전 기본값:** Agent는 물리 테이블명을 모름. 내부적으로 `case_id` 의미만 유지

### OD-07 · Supervisor가 호출 계획을 스스로 세우는가

- **미정인 내용:** 지금은 `AgentGraph` 코드가 호출 순서를 정합니다(`graph.py`). 목표는 Supervisor가 필요한 Agent·Tool을 고르는 것
- **누가 남긴 미정인가:** **검토됨.** 멘토가 현재 구조를 approve했고 "MVP 이후로 미룰 수 있는 설계 포인트는 과감히 미루라"고 함
- **쟁점:** 동적 계획은 호출 수와 지연 시간을 예측하기 어렵게 만듭니다. 지금은 40회/60초 안에 들어오는지 겨우 재고 있는 단계입니다
- **MVP:** **연기 가능**
- **누가 정하나:** **AI 단독**
- **결정 전 안전 기본값:** trigger별 고정 경로. 모든 초안은 Review를 반드시 거침

### OD-08 · 정규식 가드레일의 실제 구멍

- **미정인 내용:** 언제, 어디까지 고도화할지
- **누가 남긴 미정인가:** **검토됨.** 멘토 리뷰 1번 → MVP 이후
- **쟁점:** 구체적인 구멍이 하나 확인됐습니다 — **금액 뒤에 조사가 붙으면 탐지하지 못합니다.**
  `_AMOUNT_PATTERN`이 화폐 단위 뒤에 `\b`를 요구하는데 한국어 조사도 단어 문자라서, `1,200,000원이`·`300만원을`·`30000원입니다`가 전부 빠져나갑니다. 실제 문장은 대부분 이 모양입니다.
  `backend/tests/agent/test_claim_safety.py::test_known_gap_an_amount_followed_by_a_particle_is_missed`에 현재 동작으로 고정해 뒀습니다
- **MVP:** **연기 가능** — Review가 2차로 막습니다. 다만 결정적 1차 방어가 금액에서는 사실상 비어 있습니다
- **누가 정하나:** **AI 단독**
- **결정 전 안전 기본값:** Review Tool의 독립 검증. `guardrails.py`의 민감정보 패턴도 3개뿐(주민번호·Bearer·API key)이라 전화번호·이메일·사업자등록번호·주소는 못 잡습니다

### OD-09 · 기업마당 raw 공고를 검수 catalog로 발행하는 절차

- **미정인 내용:** 수집 → 구조화 → 검수 → 발행을 누가 어떤 기준으로 하는지
- **누가 남긴 미정인가:** **문서에만 있음** ([`official-data-sources.md`](./official-data-sources.md))
- **쟁점:** 공고 문구("예산 소진 시까지" 등)를 날짜·Boolean으로 바꾸면 오판이 생김
- **MVP:** **연기 가능**
- **누가 정하나:** **AI 단독** (검수 인력은 공동)
- **결정 전 안전 기본값:** 미검수 후보를 Support Agent에 주입하지 않음. discovery 도구는 구현돼 있지만 실행 흐름에 연결하지 않음

### OD-10 · 스케줄러

- **미정인 내용:** APScheduler 내장 vs 외부 cron
- **누가 남긴 미정인가:** **문서에만 있음** (`backend/CLAUDE.md`)
- **MVP:** **연기 가능** — MVP에 배치 기능이 없습니다
- **누가 정하나:** **BE 단독**
- **결정 전 안전 기본값:** 배치 없음. 절차 갱신은 수동 명령

---

## 3. 이 문서를 고치는 규칙

- 항목이 결정되면 §2에서 지우고 §1에 근거와 함께 옮깁니다. 근거 없이 §1에 넣지 않습니다.
- 새 미정 항목은 다른 문서에 "TBD"라고만 적지 말고 여기에 행을 추가합니다.
- "누가 남긴 미정인가"를 반드시 채웁니다. `문서에만 있음`이 오래 남아 있으면 그건 안건으로 올릴 때가 됐다는 뜻입니다.
