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

- Agent와 API 서버는 동일 DB를 공유한다.
- Agent는 별도 데이터 레이어를 거치지 않고, DB 접근을 **함수 호출(tool/function-calling)** 형태로 수행한다.
- 그 함수의 실제 구현은 `app/shared/functions/`에 하나만 두고, `app/api/` 라우터와 `app/agent/tools/`가 각자 같은 함수를 호출한다. API와 Agent에 구현이 따로 존재하지 않는다.

## 디렉토리 역할

- `app/shared/` — BE와 Agent가 공동으로 쓰는 영역
  - `db.py` — DB 세션/커넥션 (SQLAlchemy Engine + pymysql, MySQL 접속)
  - `models/` — Case, SupportItem 등 도메인 모델(테이블 정의)
  - `schemas/` — Pydantic 스키마 (API 응답 ↔ Agent tool 입출력 공용)
  - `functions/` — DB 접근 함수 본체. Hero Loop에 필요한 최소 함수(시그니처는 확정 아님, 구현 시 이름 그대로 사용 권장):
    ```python
    def create_case(owner_id: int, initial_facts: dict) -> Case: ...
    def get_case(case_id: int, requester_id: int) -> Case: ...  # requester_id != case.member_id면 조회 거부(개인정보 invariant)
    def apply_fact_candidates(case_id: int, expected_version: int, facts: list[FactCandidate]) -> ValidationResult: ...
    def confirm_conflict(case_id: int, expected_version: int, confirmed_changes: list[dict]) -> ValidationResult: ...
    ```
- `app/api/` — API 라우터 (`shared/functions` 호출)
- `app/agent/` — LangChain/LangGraph 에이전트. MVP 구성은 **Supervisor + 정보분석 Agent + 지원금 Agent**(`docs/tech-stack.md` §4.3 참고). 행정지원은 여기 없고 `app/rules/`의 Rule 엔진으로 처리한다. **각 Agent 노드는 자체 tool-selection이나 재추론 루프 없이 단일 LLM 호출(또는 정해진 Wiki→RAG 순서)만 수행한다 — 상세 정의는 `docs/architecture.md` §4 참고.**
  - `graph.py`, `state.py` — 최상위 그래프/공유 상태 정의
  - `supervisor/` — Rule 엔진·정보분석·지원금 Agent 결과를 종합해 Blocker 1개·Next Action 1개로 정리
  - `info_agent/` — 정보분석 Agent: 사용자 입력을 사실 후보로 해석 (Case를 직접 갱신하지 않음)
  - `support_agent/` — 지원금 Agent
    - `wiki/` — LLM Wiki(Obsidian) 조회 (Wiki 우선 경로)
    - `rag/` — Wiki miss·업데이트 시 RAG (`docs/tech-stack.md` §4.4 참고)
    - `tools/`, `prompts/`
  - `llm.py`, `tracing.py` — OpenAI 클라이언트, Langfuse 연동
- `app/rules/` — Case 상태 전이 validation, 절차 적용조건 등 시스템 invariant를 코드로 강제하는 영역. **행정지원(신고·말소 등 정형 절차)도 여기서 Rule 엔진으로 처리하며 LLM Agent로 만들지 않는다.** `shared/functions`가 쓰기 작업 전에 호출하므로 Agent가 이 검증을 우회할 수 없다.

## Case / 검증 규칙

- 상태 전이 유효성, 선행조건은 이 레이어(코드)에서 검증하며 LLM에 위임하지 않는다. (루트 CLAUDE.md "역할 경계" 참고)
- API naming, Case validation 세부 규칙은 추가 예정
