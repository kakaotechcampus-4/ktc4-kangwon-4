# CLAUDE.md — Backend

공통 원칙은 [`/CLAUDE.md`](../CLAUDE.md)를 따릅니다. 이 문서는 백엔드에서만 적용되는 구현 규칙입니다.

## 기술 스택

정확한 버전·선택 이유·대안 비교는 **`docs/tech-stack.md` §6**(단일 출처)을 참고 — 이 문서에서는 숫자를 반복하지 않습니다.

- FastAPI + SQLAlchemy 2.0 + pymysql (MySQL) + Alembic(마이그레이션)
- 인증: 카카오 OAuth + 자체 발급 Access/Refresh JWT (PyJWT). 비밀번호 해싱 라이브러리는 없음(카카오 OAuth만 사용)
- 카카오 API(토큰 교환·사용자정보) 호출: httpx
- Agent: LangChain + LangGraph, 관측성: Langfuse(실제 구현 착수 시점에 연동)

## 런타임/버전

- Python: **3.12** (`backend/.python-version`, `Dockerfile` 베이스 이미지 `python:3.12-slim`)
- 패키지 관리: **plain pip + `backend/requirements.txt`**(정확 버전 고정, `==`) — 2026-09 BE가 실제로 설치·`pip check`·import 테스트까지 마친 확정본입니다. `requirements-dev.txt`는 테스트 전용(pytest, testcontainers).
- 온보딩: `pip install -r backend/requirements.txt` (또는 `docker-compose up`으로 컨테이너째 실행).
- AI 스택(langchain/langchain-openai/langgraph/langfuse/openai)도 이 파일 안에 함께 고정되어 있으며, BE가 나머지 8개 패키지와 같은 가상환경에 동시 설치해 충돌 없음을 확인했고, AI팀이 `backend/`에서 별도로 재현한 버전과 정확히 일치함을 교차 확인했습니다(자세한 버전은 `docs/tech-stack.md` §6).

## 개발/배포/테스트 환경 (BE 확정)

| 항목 | 결정 |
|---|---|
| 배포 | Docker, `backend/Dockerfile`(`python:3.12-slim` + `pip install -r requirements.txt`) |
| 로컬 개발 · 배포 실행 | 루트 `docker-compose.yml` (`db`=`mysql:8.0`, `app`=backend 빌드) — AI팀도 동일 파일로 `docker-compose up` |
| 테스트 DB | `testcontainers[mysql]` — 테스트마다 격리된 MySQL 컨테이너를 코드로 직접 실행(compose와 별개 메커니즘, 이미지 버전만 `mysql:8.0`으로 통일) |
| 테스트 범위 | API 엔드포인트 테스트 + 서비스 로직 단위 테스트 |
| Agent 호출부 테스트 | 실제 LLM 호출 대신 `unittest.mock`으로 목 처리 |
| 커버리지 측정 | 도입 안 함 |
| 스케줄러 | **미정** (APScheduler 내장 vs 외부 cron) |

Redis는 이 확정 스택에 포함되어 있지 않습니다 — `config.py`/`.env`의 `REDIS_URL`은 현재 실제 사용처가 없는 선점 변수입니다.

## Agent ↔ DB 연동 방식

- Agent와 API 서버는 같은 DB를 사용하지만 Agent가 SQL·ORM을 직접 호출하지 않는다.
- DB 접근 함수와 API는 BE가 구현하고, AI는 필요한 Agent Tool·입출력 schema를 정의해 해당 함수를 호출한다.
- DB 함수의 실제 구현은 `app/shared/functions/`에 하나만 두고, `app/api/` 라우터와 Agent Tool adapter가 같은 함수를 재사용한다.

## 디렉토리 역할

- `app/shared/` — BE와 Agent가 공동으로 쓰는 영역
  - `db.py` — DB 세션/커넥션 (SQLAlchemy Engine + pymysql, MySQL 접속)
  - `models/` — Case, SupportItem 등 도메인 모델(테이블 정의)
  - `schemas/` — BE API·DB 경계의 Pydantic 스키마. Agent 내부 입출력 스키마는 AI가 정의하고, BE 연동 DTO만 합의 후 공유
  - `functions/` — DB 접근 함수 본체. Case 생성, 소유권 조건을 포함한 조회, 확인된 변경 후보 반영, 충돌 확인 기능이 필요합니다. 함수명·인자·동시성 제어와 트랜잭션 경계는 BE 계약에서 확정합니다.
- `app/api/` — API 라우터 (`shared/functions` 호출)
- `app/agent/` — LangChain/LangGraph 런타임. **Supervisor가 전역 계획을 담당**하고 정보분석·지원금 Agent를 Agent-as-Tool로, 절차조회 Tool을 일반 Tool로 선택 호출한다. 모든 정상 초안은 Review Tool을 반드시 거친다(`docs/architecture.md`).
  - `graph.py`, `state.py` — 최상위 그래프/공유 상태 정의
  - `supervisor/` — 호출 대상 선택, 결과 평가, Blocker 1개·Next Action 1개 결정, 재호출·종료 판단
  - `info_agent/` — 정보분석 Agent-as-Tool. 자기 분석 범위의 bounded Local Loop만 허용
  - `support_agent/` — 지원금 Agent-as-Tool. 근거 확보를 위한 bounded Local Loop만 허용
    - `wiki/` — LLM Wiki(Obsidian) 조회 (Wiki 우선 경로)
    - `rag/` — Wiki miss·업데이트 시 RAG (`docs/tech-stack.md` §4.4 참고)
    - `tools/`, `prompts/`
  - `procedure_tool/` — 정형 절차 데이터 조회 Tool. 우선순위와 Next Action을 결정하지 않음
  - `review_tool/` — 제공된 초안·Evidence만 독립 검토하는 필수 Tool. 검색·직접 수정·자체 루프 없음
  - `llm.py`, `tracing.py` — OpenAI 클라이언트, Langfuse 연동
- 독립된 `app/rules/` Rule 엔진은 두지 않는다. 입력·상태 전이·출력의 결정 가능한 제약은 코드 Guardrail로, 절차 정보 조회는 절차조회 Tool로 분리한다.

## Case / 검증 규칙

- 상태 전이 유효성과 충돌 자동 덮어쓰기 방지는 코드로 강제한다. 절차 후보와 조건은 절차조회 Tool이 반환하고 최종 순서는 Supervisor가 판단한다.
- API naming, Case validation 세부 규칙은 추가 예정
