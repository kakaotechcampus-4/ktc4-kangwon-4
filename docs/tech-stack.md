# RE:BORN 기술 스택 & 프로젝트 구조 (팀 공유용)

> 2026-09 기준 확정 사항. 실제 운영 문서(에이전트 지침)는 레포의 `/CLAUDE.md`, `/frontend/CLAUDE.md`, `/backend/CLAUDE.md`이고, 이 문서는 그 내용을 팀 공유용으로 요약한 것입니다 — 원문과 어긋나면 항상 CLAUDE.md 쪽이 맞습니다.

## 1. 프론트엔드

| 구분 | 기술 |
|---|---|
| 개발 방향 | Mobile-First 반응형 웹앱 |
| 핵심 프레임워크 | React |
| 개발 언어 | TypeScript |
| 빌드/개발 환경 | Vite |
| 라우팅 | React Router |
| 스타일링 | Tailwind CSS 4 (필요 시 Kakao·Toss 디자인 시스템 참고) |
| 서버 통신 | Fetch API |
| 상태 관리 | React 기본 상태 관리 |
| 배포 | Vercel |
| Node.js | 22 LTS |
| React 버전 | 19 |
| TypeScript 버전 | 5.x 최신 stable |
| Vite 버전 | 6 |

## 2. 백엔드

| 구분 | 기술 |
|---|---|
| API 서버 | FastAPI |
| Agent ↔ DB 연동 | 백엔드와 동일 DB를 공유하며, Agent가 DB 접근을 **함수 호출(tool/function-calling)** 형태로 수행 (별도 데이터 레이어 없음) |
| DB / ORM | **MySQL 8.0 + SQLAlchemy 2.0 + pymysql** (2026-09 BE 확정) + **Alembic**(마이그레이션) |
| 인증 | **카카오 OAuth + 자체 발급 Access/Refresh JWT**(PyJWT, 2026-09 BE 확정). 비밀번호 해싱 라이브러리 없음(카카오 OAuth만 사용, 자체 비밀번호 인증 없음) |
| 카카오 API 호출 | httpx (토큰 교환·사용자정보 조회) |
| 패키지 관리 | **plain pip + `backend/requirements.txt`**(정확 버전 고정, `==`) — BE가 실제 설치·`pip check`·import까지 검증 완료. `uv`/`pyproject.toml`은 쓰지 않음(이전 계획에서 변경) |
| 배포 | **Docker** — `backend/Dockerfile`(`python:3.12-slim` + `pip install`), 루트 `docker-compose.yml`로 로컬/배포 실행. 호스팅 플랫폼(EC2 등)은 AWS 크레딧 활용 예정이나 구체 서비스는 추가 확인 필요 |
| 테스트 | `testcontainers[mysql]`로 격리된 MySQL 컨테이너 실행 + pytest. LLM 호출은 `unittest.mock`으로 목 처리. 커버리지 측정 도입 안 함 |
| 스케줄러 | 미정 (APScheduler 내장 vs 외부 cron) |
| Python 버전 | 3.12 |

Redis는 이 확정 스택에 포함되어 있지 않습니다 — `config.py`/`.env`의 `REDIS_URL`은 현재 실제 사용처가 없는 선점 변수입니다.

## 3. Agent

| 구분 | 기술 | 비고 |
|---|---|---|
| LLM Provider | OpenAI API (mlapi.run 프록시 경유, `OPENAI_API_KEY` 직접 호출 아님 — §6 참고) | |
| 에이전트 프레임워크 | LangChain | LLM 체인·툴 연동 |
| 에이전트 오케스트레이션 | LangGraph | 멀티스텝/상태 기반 워크플로우 |
| 관측성(Observability) | Langfuse | 실제 구현 착수 시점에 연동 예정 (아직 미연동), 셀프호스팅 — EC2에 백엔드와 함께 배포 예정(서드파티 SaaS로 사용자 원문이 외부로 나가는 것을 피하기 위함, `config.py` 주석 근거) |
| 지원금(정책) 도메인 지식베이스 | LLM Wiki + Obsidian | Obsidian 볼트에 지식 축적 + LLM Wiki 패턴으로 질의. 검증된 `support_item` 레코드에 없는 지원사업명·조건은 생성하지 않음 |
| 벡터스토어/임베딩 | **Chroma**(2026-09 확정) | 셀프호스팅(임베디드로 시작, 필요 시 컨테이너로 분리) — Pinecone은 데이터 외부 반출로 Langfuse 셀프호스팅 원칙과 배치, Weaviate는 MVP 규모 대비 운영 부담 과함. `langchain-chroma` 통합. 아래 4.4 참고, 상시 사용 아니고 Wiki miss/업데이트 시점에만 사용 |
| Agent 구성 | Supervisor + 정보분석 Agent + 지원금 Agent (LLM 기반), 행정지원은 Rule 엔진 기반 | 아래 4.3 참고 |

정확한 버전은 §6(단일 출처)을 참고하세요 — Agent 5개 패키지는 BE가 자신들의 8개 패키지와 함께 설치해 충돌 없음을 확인했고, AI팀이 독립적으로 얻은 버전과 정확히 일치합니다.

## 4. 프로젝트 문서/디렉토리 구조

### 4.1 CLAUDE.md 2단 구조

- **루트 `/CLAUDE.md`**: FE/BE/Agent 공통 원칙 (서비스 정의, Hero Loop, 하지 않는 것, 역할 경계, 개인정보, 용어, 참조 문서, 레포 운영, 문서 소유권)
- **파트별 `CLAUDE.md`**: 각 파트에서만 필요한 구현 규칙 (`frontend/CLAUDE.md`, `backend/CLAUDE.md`)
- 초기에는 `.claude/rules/`, `.claude/skills/`는 만들지 않고, 실제 필요가 확인될 때 추가

### 4.2 디렉토리 구조

```
ktc4-kangwon-4/
├─ CLAUDE.md
├─ README.md
├─ .gitignore
├─ .github/
├─ docker-compose.yml       # 로컬/배포 공용 — db(MySQL) + app(backend+agent)
│
├─ docs/
│  ├─ hero-scenario.md      # 사용자 시나리오 / Hero Loop 상세
│  ├─ interface-spec.md     # FE/BE API 인터페이스 정의
│  ├─ data-model.md         # Case 상태/데이터 모델
│  ├─ architecture.md       # 전체 시스템 아키텍처
│  └─ tech-stack.md         # 이 문서
│
├─ frontend/
│  ├─ CLAUDE.md
│  └─ src/
│
└─ backend/
   ├─ CLAUDE.md
   ├─ Dockerfile
   ├─ requirements.txt      # 정확 버전 고정 (BE+Agent 전체)
   ├─ requirements-dev.txt  # pytest, testcontainers
   └─ app/
      ├─ main.py            # FastAPI 진입점
      ├─ config.py          # 설정/환경변수
      │
      ├─ shared/            # BE와 Agent가 공동으로 쓰는 영역
      │  ├─ db.py           # DB 세션/커넥션 (SQLAlchemy + pymysql, MySQL 접속)
      │  ├─ models/         # Case, SupportItem 등 도메인 모델(테이블 정의)
      │  ├─ schemas/        # Pydantic 스키마 — API 응답 ↔ Agent tool 입출력 공용
      │  └─ functions/      # DB 접근 함수 본체 — Agent가 "함수 호출"로 쓰는 바로 그 함수,
      │                     # api/ 라우터도 동일 함수를 재사용 (구현이 두 곳에 따로 없음). 최소 함수 목록은 backend/CLAUDE.md 참고
      │
      ├─ api/               # BE 전용 — API 라우터 (shared/functions 호출)
      │
      ├─ agent/             # Agent 전용 — Supervisor + Sub-agent 구조 (§4.3)
      │  ├─ graph.py        # 최상위 LangGraph 그래프 — Supervisor가 Sub-agent를 라우팅
      │  ├─ state.py        # 공유 State 스키마 (필드 목록은 docs/architecture.md §4 참고)
      │  │
      │  ├─ supervisor/     # Supervisor Agent — Rule/대조 결과 + Sub-agent 결과 종합 → Blocker 1개·Next Action 1개
      │  │  └─ prompts/
      │  │
      │  ├─ info_agent/     # 정보분석 Agent — 사용자 입력을 사실 후보로 해석
      │  │  ├─ tools/       # shared/functions를 LangChain 툴로 감싼 어댑터
      │  │  └─ prompts/
      │  │
      │  ├─ support_agent/  # 지원금 Agent
      │  │  ├─ wiki/        # LLM Wiki(Obsidian) 조회 — Wiki 우선 경로 (§4.4)
      │  │  ├─ rag/         # Wiki miss·업데이트 시 RAG (§4.4)
      │  │  ├─ tools/
      │  │  └─ prompts/
      │  │
      │  ├─ llm.py          # OpenAI 클라이언트 초기화
      │  └─ tracing.py      # Langfuse 연동
      │
      └─ rules/             # Case 상태 전이 validation + 행정지원(Rule 엔진 기반, LLM Agent 아님). Rule 시그니처는 docs/data-model.md §5~6 참고
                             # shared/functions가 쓰기 전에 호출 — Agent는 이 검증을 우회할 수 없음
```

- **`shared/`가 필요한 이유**: Agent는 DB를 "함수처럼 호출"하기로 했는데, 그 함수의 실제 구현이 `api/`에도 있고 `agent/`에도 따로 있으면 두 곳이 어긋날 수 있음. `shared/functions/`에 구현을 하나만 두고 `api/` 라우터와 `agent/tools/`가 같은 함수를 각자 호출하는 방식으로 정리.
- **`rules/`와의 관계**: `shared/functions/`가 쓰기 작업 전에 `rules/`의 validation을 거치므로, Agent가 `agent/tools/` → `shared/functions/` 경로로만 DB에 접근하는 한 상태 전이 invariant를 우회할 수 없음.

### 4.3 Agent 내부 구조 (Supervisor + Sub-agent)

MVP 기준 Agent 구성은 **Supervisor + 정보분석 Agent + 지원금 Agent**(LLM 기반)이고, **행정지원**은 별도 LLM Agent가 아니라 **Rule 엔진**(코드)으로 처리합니다. "Agent" = 자체 tool 선택·재추론 루프 없는 LangGraph 노드 1개(bounded 파이프라인 스텝) — 상세 정의·다이어그램·역할 경계는 **`docs/architecture.md` §4**를 참고하세요(여기서 재서술하지 않음).

### 4.4 지원금 지식 흐름 (LLM Wiki + RAG)

지원금 조회는 기본적으로 **Wiki 우선**이고, LLM/RAG는 Wiki miss·정보 업데이트 시에만 개입합니다. 상세 흐름도와 저장소 구조는 **`docs/architecture.md` §6**을 참고하세요(여기서 재서술하지 않음). 검증된 `support_item`에 없는 지원사업명·조건은 생성하지 않습니다(`/CLAUDE.md` 역할 경계 원칙).

### 4.5 문서 소유권

문서 소유권은 `/CLAUDE.md` "문서 소유권" 표가 canonical입니다(여기서 복제하지 않음).

## 5. 핵심 제품 원칙

전체 원칙(서비스 정의, Hero Loop, 하지 않는 것, 역할 경계)은 `/CLAUDE.md`가 canonical입니다 — 이 문서는 기술 스택 요약이므로 제품 원칙을 복제하지 않습니다.

## 6. 확정 버전 전체 (백엔드+Agent, 단일 출처)

> 2026-09, `BE기술스택.html`(BE 실 테스트) + `backend/`에서 AI팀이 독립 실행한 `uv sync` 결과 교차검증. 모든 문서(이 문서, `backend/CLAUDE.md`)는 버전을 여기 한 곳에서만 관리합니다 — 다른 곳에 숫자를 다시 적지 마세요.

| 패키지 | 버전 | 역할 | 비교 검토한 대안 |
|---|---|---|---|
| fastapi | 0.141.1 | 웹 프레임워크 본체 | Django, Flask (이미 확정) |
| uvicorn[standard] | 0.52.4 | ASGI 서버 | hypercorn, daphne |
| pydantic | 2.13.5 | 요청/응답 검증 (FastAPI 필수 의존성) | — |
| sqlalchemy | 2.0.52 | ORM | SQLModel, Tortoise ORM |
| pymysql | 1.2.0 | MySQL 통신 드라이버 | mysqlclient, asyncmy/aiomysql |
| alembic | 1.19.2 | DB 스키마 마이그레이션 이력 관리 | 수동 SQL 관리 (비권장) |
| pyjwt | 2.13.0 | 자체 Access/Refresh JWT 발급·검증 | python-jose, authlib |
| httpx | 0.28.1 | 카카오 API 호출 클라이언트 | requests, aiohttp |
| pydantic-settings | 2.15.0 | 설정 로더 | — |
| python-dotenv | 1.2.3 | `.env` 로드 | — |
| langchain | 1.4.0 | LLM 체인·툴 연동 | — |
| langchain-openai | 1.6.0 | LangChain-OpenAI 연동 | — |
| langgraph | 1.2.11 | 멀티스텝/상태 기반 워크플로우 | — |
| langfuse | 4.15.1 | 관측성 | LangSmith(서드파티 SaaS라 배제) |
| openai | 3.8.0 | LLM Provider SDK | — |
| langchain-chroma | 1.1.0 | Chroma-LangChain 통합 | — |
| chromadb | 1.5.9 | 벡터스토어(RAG, Wiki miss 폴백 전용) | Pinecone(SaaS·데이터 외부반출), Weaviate(운영부담) |

Python 3.12(`backend/.python-version`), `backend/Dockerfile` 베이스 이미지도 `python:3.12-slim`. 온보딩: `pip install -r backend/requirements.txt`.

---

## 출처

| 섹션 | 원본 |
|---|---|
| §1 프론트엔드 | `IDEATHON/docs/tech-stack.md` 그대로 이식 |
| §2 DB/인증/패키지관리/배포/테스트 | 사용자가 공유한 `BE기술스택.html`(2026-09, BE 실제 테스트 완료본) — `uv`→`pip` 전환, MySQL 8.0, PyJWT 인증, testcontainers 반영 |
| §3 Agent | `IDEATHON/docs/tech-stack.md` §4.3 요약, 버전 표는 §6으로 통합(중복 제거) |
| §4.3~4.5 | `docs/architecture.md`로 상세 이관, 이 문서는 링크만 유지(중복 제거 — 검증 워크플로우 지적사항 반영) |
| §5 | `/CLAUDE.md`로 전면 위임(중복 제거) |
| §6 확정 버전 전체 | `BE기술스택.html` §1 표 + AI팀 `uv sync` 교차검증 결과 병합 |
