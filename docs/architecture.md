# RE:BORN 아키텍처

> 전체 시스템 아키텍처, Agent-DB-API 경계. 이 문서는 `docs/tech-stack.md`(스택/디렉토리)와 `docs/data-model.md`(enum/테이블/Rule)를 전제로 하며, 그 내용을 재서술하지 않고 인용합니다. Hero Loop 서사는 `docs/hero-scenario.md`를 참고하세요.

이 문서는 로컬 초안 저장소에만 있던 이전 설계 메모(`agent설계.md`)를 대체하는 최신 기준입니다.

## 1. 서비스 한 줄 요약

폐업을 결심한 소상공인의 폐업 과정을 하나의 **Closure Case**로 관리하는 Agent. 조건이 바뀔 때마다 Blocker와 Next Action을 재계산합니다. MVP 타깃은 1~5인·비프랜차이즈·임차형 카페 사업자입니다. 전체 원칙은 `/CLAUDE.md`, Hero Loop 상세는 `docs/hero-scenario.md`를 참고하세요.

## 2. 시스템 개요

```
FE (React/Vite, Vercel)
   │  Fetch API, camelCase JSON
   ▼
BE API (FastAPI)
   │
   ▼
app/shared/functions/  ◀───────── app/agent/*/tools/ (Agent도 같은 함수를 호출)
   │
   ▼
DB (MySQL, SQLAlchemy + pymysql)
```

Agent는 별도 서비스가 아니라 BE와 **같은 프로세스, 같은 DB**를 공유하며, DB 접근을 함수 호출(tool/function-calling)로 수행합니다. 이것이 `RE_BORN_기술멘토링_사전질문.md` Q1("Supervisor·Rule Engine·지원사업 조회를 BE 내부 모듈로 둘지 별도 AI 서버로 분리할지")에 대한 답입니다 — `docs/tech-stack.md` 확정 시점에 "동일 프로세스, 함수 호출"로 이미 결정되었으므로 이 질문은 재론하지 않습니다.

### 2.1 실행/배포 환경

- **로컬 개발 · 배포 둘 다 동일 방식(BE 확정)**: 루트 `docker-compose.yml`이 `db`(MySQL 8.0)와 `app`(backend+Agent, `backend/Dockerfile`로 빌드)을 함께 띄웁니다. `docker-compose up` 한 번으로 AI팀도 전체 서버+DB를 동일 환경에서 구동할 수 있습니다 — §2 다이어그램의 "같은 프로세스" 전제가 로컬·배포 모두에서 유지됩니다(Agent용 별도 컨테이너/서비스를 두지 않음).
- **테스트**: `testcontainers[mysql]`로 테스트마다 격리된 MySQL 컨테이너를 코드로 직접 실행(compose와 별개 메커니즘, 이미지 버전은 `mysql:8.0`으로 동일하게 맞춤).
- **호스팅 플랫폼은 AWS EC2로 확정**(BE, 2026-09) — 단일 인스턴스에서 루트 `docker-compose.yml`을 그대로 `docker-compose up`으로 실행하는 방식이 위 "동일 방식" 전제와 맞습니다(ECS/Fargate처럼 compose를 태스크 정의로 재변환할 필요 없음). Langfuse는 별도 컨테이너 스택(공식 셀프호스팅 가이드 기준)으로 같은 EC2 호스트에 함께 배포될 예정입니다.
- DB 엔진은 **MySQL**로 확정(2026-09 BE, SQLAlchemy + pymysql) — `docker-compose.yml`의 `db` 서비스도 MySQL 8 기준입니다.

## 3. Agent-DB 접근 불변식

Agent는 `agent/tools/` → `shared/functions/` 경로로만 DB에 접근합니다. `shared/functions/`는 쓰기 작업 전에 `app/rules/`의 validation을 거치므로, Agent는 이 상태 전이 검증을 우회할 수 없습니다. `api/` 라우터와 `agent/tools/`는 서로 다른 구현을 갖지 않고 동일한 `shared/functions/`를 호출합니다.

## 4. Agent 구조 — 3-노드 파이프라인

### 4.1 "Agent"의 정의 (이 문서의 핵심 결정)

이 문서에서 **"Agent"는 LangGraph 노드 하나**를 뜻하며, 각 노드는:
- 한 번의 bounded LLM 호출, 또는
- §6의 고정된 Wiki→RAG 조회 시퀀스

만 수행하는 파이프라인 스텝입니다. **자체적으로 tool을 선택하거나 여러 단계를 스스로 재추론하는 자율 에이전트가 아닙니다.**

### 4.2 노드 구성

| 노드 | 역할 | 하지 않는 일 |
|---|---|---|
| Supervisor Agent | 정보분석/지원금 Agent + Rule 엔진 결과 종합 → Blocker 1개·Next Action 1개 | 법률·세무·채무 전문 판단 |
| 정보분석 Agent | 자연어 입력 → 사실 후보 해석 (단일 LLM 호출) | Case 직접 갱신 |
| 지원금 Agent | Wiki 우선 + RAG fallback (§6) | 지원 자격/금액 최종 확정 |
| Rule 엔진(행정지원) | 상태 전이·적용조건 계산 — **LLM 노드 아님, 순수 코드** (`app/rules/`) | 문장에 없는 사실·날짜·금액 추정 |

```
                     ┌────────────────────┐
Case 저장소 ───────▶ │  Supervisor Agent   │
                     └─────────┬──────────┘
                               │ 조정
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌───────────────┐     ┌────────────────┐     ┌──────────────────┐
│ 정보분석 Agent │     │  지원금 Agent   │     │  Rule 엔진(행정지원)│
│ (사실 후보 해석)│     │ (Wiki+RAG, §6) │     │  — LLM Agent 아님  │
└───────────────┘     └────────────────┘     └──────────────────┘
        │                      │                      │
        └──────────────────────┴──────────────────────┘
                               ▼
                Blocker 1개 + Next Action 1개 (Supervisor가 종합)
```

### 4.3 명명 정리

`SupportResearchTool`이라는 옛 이름이 하던 일(공식 API·페이지·원문 검색 + Evidence 반환)은 지금 `support_agent/wiki/` + `support_agent/rag/`가 담당합니다 — 아키텍처 레벨 명칭은 이 이름으로 통일하되, 내부 헬퍼 함수명으로는 옛 이름을 계속 써도 됩니다.

### 4.4 공유 State 스키마 (`agent/state.py`)

`docs/tech-stack.md` §4.2가 "필드 목록은 이 문서 §4 참고"라고 가리키는 대상인데 실제로는 어디에도 없었습니다 — 여기서 신규 정의합니다(AI 리드, 2026-09).

| 필드 | 타입 | 설명 |
|---|---|---|
| `case_id` | int | |
| `requester_id` | int | 소유권 검증용(`/CLAUDE.md` 개인정보 invariant) |
| `raw_input` | str | 사용자 입력 원문 |
| `expected_version` | int | 낙관적 잠금(`docs/data-model.md` §3) |
| `client_event_id` | str | |
| `fact_candidate` | `FactCandidate` | 정보분석 Agent 출력(`docs/interface-spec.md` §11.1) |
| `validation_result` | `ValidationResult` | Validator 출력(§11.2) |
| `rule_decision` | `RuleDecision` \| `None` | Rule 엔진 출력(§11.3) |
| `support_check_result` | `SupportCheckResult` \| `None` | 지원금 Agent 출력(§11.4) — §5 흐름에서 조건부로만 채워짐 |
| `final_response` | dict | Response Writer(Supervisor)가 조립한 최종 응답 — §5 FE 응답 shape과 동일 |

각 노드는 이 State 중 자기 담당 필드만 채워서 반환합니다(§4.1 "bounded 파이프라인 스텝" 정의와 일관 — 노드가 State 전체를 임의로 고치지 않음).

## 5. 요청 라이프사이클 — `POST /cases/{caseId}/results`

```
FE
 │ rawInput, expectedVersion, clientEventId
 ▼
BE API — 현재 Case·버전·소유권 확인
 │
 ▼
정보분석 Agent — FactCandidate 생성
 │
 ▼
Validator (app/rules/) — Schema·기존 값·Conflict 확인
 │       ├─ NEEDS_MORE_INFO / CONFLICT → 사용자 응답 대기
 │       └─ 정상 → Case UPDATE
 │
 ▼
Rule 엔진 — 적용 Step·의존성·Blocker·Next Action 후보 계산
 │
 ├─ 지원정보가 필요하면 지원금 Agent 호출 → SupportCheckResult
 │
 ▼
Response Writer (Supervisor) — 확정된 결과만 쉬운 문장으로 표현
 │
 ▼
History INSERT → FE 응답
```

세부 요청/응답 JSON은 `docs/interface-spec.md`를 참고하세요.

**명시적 TBD**: LLM/외부 조회를 긴 DB 트랜잭션 안에서 실행하지 않는 것이 바람직하다는 원칙은 있지만, `Case UPDATE`·`History INSERT`·Replan 결과 저장의 정확한 트랜잭션 경계는 아직 확정되지 않았습니다(`RE_BORN_기술멘토링_사전질문.md` Q2, 미해결 상태로 남아있음) — **BE와 회의하여 확정 필요**.

## 6. 저장소 구조 — Wiki-first + RAG-fallback

### 6.1 4단 저장소

| Store | 역할 |
|---|---|
| RDS | Case 현재 상태, 절차 진행상태, 지원항목 구조화 정보, 신청 상태, Case History |
| S3 | 공식 원문 HTML/JSON/XML/PDF, 문서 hash·snapshot, 생성된 Markdown |
| Vector Index | **Chroma**(2026-09 확정, 셀프호스팅 — 임베디드로 시작, 필요 시 컨테이너로 분리). RAG 검색용 chunk·embedding·metadata |
| Obsidian | 사람이 검수하는 Markdown Wiki |

### 6.2 지원금 조회 흐름

**Wiki 조회는 벡터 검색이 아닙니다** — Rule 엔진이 이미 어느 `support_item_id`를 봐야 하는지 알고 있으므로, `support_agent/wiki/`는 그 ID를 frontmatter 키로 가진 Markdown 노트를 **정확 매칭(파일/키 lookup)** 으로 찾습니다. Chroma(임베딩 검색)는 아래 "없음(miss)" 분기, 즉 원문(S3의 PDF/HTML)에서 다시 찾아야 할 때만 사용합니다.

```
사용자 질문 → support_item_id로 Wiki(Obsidian) 노트 직접 lookup (ID 매칭, 벡터 검색 아님)
  ├─ 있음 → 바로 응답 (LLM 호출 최소화)
  └─ 없음(miss) → Chroma로 원본(S3 PDF/HTML) 청크 임베딩 검색(RAG) → LLM 정리 → Wiki 반영

(별도 트리거) 정보 업데이트 필요 시 → Chroma로 원본 재검색 → LLM 정리 → Wiki 갱신
```

RAG chunk metadata 예시 — `docs/data-model.md` §8 `Evidence` 스키마와 필드명을 통일합니다(`document_type` enum, `source_version`, `page_or_section` 단일 필드 — 벡터DB 전용 필드 이름을 새로 만들지 않음):

```json
{
  "document_id": "hope-return-2026-v2-pdf",
  "source_url": "https://...",
  "document_type": "PDF",
  "program_code": "HOPE_RETURN",
  "support_item_id": "STORE_DEMOLITION_2026",
  "source_version": "2026-revision-2",
  "page_or_section": "4p 지원제외",
  "collected_at": "2026-08-31T10:00:00+09:00",
  "document_hash": "sha256:...",
  "review_status": "REVIEWED"
}
```

검색 결과는 반드시 `evidence_refs`, `source_url`, `notice_version`을 함께 반환합니다. 출처가 없거나 `STALE`이면 확정적인 문장을 만들지 않습니다.

### 6.3 Obsidian을 Agent가 직접 조회하는 방법

지원금 Agent는 실제로 Wiki를 조회 경로로 사용합니다(팀 확정). 구체적으로:

> Obsidian Vault는 Markdown + YAML frontmatter로 이루어진 폴더일 뿐입니다. 따라서 "Agent가 Wiki를 직접 조회한다"는 것은 `support_agent/wiki/`가 **개발자 개인 PC의 Obsidian.app**이 아니라, **서버(백엔드 프로세스)에 동기화된 동일 Markdown 파일 사본**을 파일시스템으로 읽는다는 뜻입니다.

**명시적 TBD (답을 지어내지 않음)**: 이 서버측 사본을 어떻게 최신 상태로 유지할지 — 후보는 (1) private Git 저장소에 push 후 서버에서 `git pull`, (2) 서버에서 도는 S3-sync worker, (3) 별도 Obsidian plugin/bridge — 그리고 최신성(staleness) 감지 방법은 어느 문서에서도 확정되지 않았습니다. **BE/DevOps 결정 필요**.

## 7. 세무(tax) 트랙은 MVP 범위 밖

현재 3-노드 구조(§4)에는 세무 관련 Agent나 트랙이 없습니다. 다음 두 원칙에 따라 이 아키텍처에는 세무 트랙을 포함하지 않습니다:

- 유료 API 배제 원칙 (`웹사이트 정리.md`: "홈택스 증명서/세금계산서/신고결과 — CODEF·팝빌로 접근 가능하나 유료라 제외, 무료 대안 없음")
- `/CLAUDE.md` "하지 않는 것": 법률·세무·채무·지원자격의 최종 판단을 하지 않는다

`config.py`의 `REQUIRED_BY_AGENT`에는 세무/CODEF 관련 항목이 없습니다 — `LLM (전체 공통)`, `정보분석 / 행정`, `철거 보조`, `지원금` 4개 그룹 모두 무료 API(`data_go_kr_service_key`, `bizinfo_api_key`)만 요구해 위 원칙과 일치합니다. ("철거 보조" 그룹명은 `정보분석 / 행정`과 동일 키만 요구하는 참고용 라벨입니다.)

**절차 목록(`procedure_step`)에도 세무 신고를 넣지 않습니다** — 세무보조 Agent가 생기기 전까지는 체크리스트 항목으로도 노출하지 않고, 확장 시점에만 추가하는 확장 지점으로 남겨둡니다(`docs/data-model.md` §2 `procedure_step` 참고, AI 리드 확정 2026-09).

## 8. 명시적 TBD 요약

- **트랜잭션 경계** (§5): Case UPDATE / History INSERT / Replan 저장의 정확한 경계
- **Obsidian 서버 동기화 메커니즘** (§6.3): Git pull vs S3 sync worker vs plugin/bridge, 최신성 감지 방법
- **Agent 분리 배포 여부**: 현재는 동일 프로세스(§2)로 확정되었으나, 향후 Agent가 별도 배포 단위가 될 가능성은 열어두되 지금 결정하지 않음

~~호스팅 플랫폼~~ → **해소됨**: AWS EC2로 확정(§2.1, 2026-09).

---

## 출처

| 섹션 | 원본 |
|---|---|
| §1~3 시스템 개요, DB 접근 불변식 | `docs/tech-stack.md` §2, §4.2 / `backend/CLAUDE.md` "Agent ↔ DB 연동 방식" |
| §2.1 실행/배포 환경 | 신규 작성 — 사용자가 직접 확정한 Docker 범위(로컬+배포 둘 다)를 반영, `docker-compose.yml`/`backend/Dockerfile` 실제 생성 |
| §2 DB 엔진 명시 | 사용자가 공유한 "백엔드 기술스택 최종 확정" 표(2026-09) — MySQL + SQLAlchemy + pymysql 확정 반영 |
| §4 3-노드 구조, Agent 정의, 명명 정리 | `docs/tech-stack.md` §4.3 / `agent설계.md` §2(이제 이 문서로 대체됨, 상세 이력은 트리밍) / `RE_BORN_AI리드_설계안.md` §2.1 (`SupportResearchTool`) |
| §5 요청 라이프사이클 | `RE_BORN_AI리드_설계안.md` §2.2, §9.3 / `BE_AI_역할분담_및_연동스펙.md` §7 |
| §5 TBD (트랜잭션 경계) | `RE_BORN_기술멘토링_사전질문.md` Q2 |
| §6.1 4단 저장소 | `RE_BORN_AI리드_설계안.md` §8.1 / `BE_AI_역할분담_및_연동스펙.md` §9.1 |
| §6.1~6.2 벡터스토어 Chroma 확정, Wiki=ID lookup·벡터DB=miss 폴백 구분 | 신규 결정 — 사용자 질문에 대한 AI 리드 추천(Pinecone/Weaviate 대비 셀프호스팅·저운영부담 근거) 확정 |
| §6.2 Wiki-first/RAG-fallback | `docs/tech-stack.md` §4.4 |
| §6.3 Obsidian 직접조회 상충 해소 | `RE_BORN_AI리드_설계안.md` §8.1, §8.4 / `BE_AI_역할분담_및_연동스펙.md` §9.2 (원 우려) + 이번 확정 사항(해소) |
| §7 세무 트랙 제외 | `웹사이트 정리.md`, `/CLAUDE.md` "하지 않는 것"; `todo.md`(9/1)가 지적한 `config.py` 모순은 2026-09-07 이 저장소로 이관된 `config.py` 재확인 결과 이미 해소됨 확인 |
