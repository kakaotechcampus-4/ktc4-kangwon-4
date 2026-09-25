# CLAUDE.md — Backend

공통 원칙은 [`/CLAUDE.md`](../CLAUDE.md)를 따릅니다. 이 문서는 백엔드에서만 적용되는 구현 규칙입니다.

## 기술 스택

정확한 버전·현재 사용 상태는 **`docs/tech-stack.md`**를 참고 — 이 문서에서는 숫자를 반복하지 않습니다.

- FastAPI + SQLModel(SQLAlchemy 기반) + pymysql (MySQL). Alembic은 설치돼 있으며 마이그레이션은 미구현
- 인증: 카카오 OAuth + 자체 발급 Access/Refresh JWT (PyJWT). 비밀번호 해싱 라이브러리는 없음(카카오 OAuth만 사용)
- 카카오 API(토큰 교환·사용자정보) 호출: httpx
- Agent: 현재 `httpx` 직접 LLM 호출 + LangGraph. Info와 Supervisor·독립 Review는 선택적으로 별도 endpoint·model을 쓰고(미설정 시 공용 설정), 모든 client는 실행당 LLM 호출 예산 하나를 공유합니다. LangChain은 설치만 됐고 runtime 미사용. Langfuse는 credential이 있을 때만 metadata를 전송합니다

## 런타임/버전

- Python: **3.12** (`backend/.python-version`, `Dockerfile` 베이스 이미지 `python:3.12-slim`)
- 패키지 관리: **plain pip + `backend/requirements.txt`**(정확 버전 고정, `==`) — 2026-09 BE가 실제로 설치·`pip check`·import 테스트까지 마친 확정본입니다. `requirements-dev.txt`는 테스트 전용(pytest, testcontainers).
- 온보딩: `pip install -r backend/requirements.txt`. `docker compose up -d db`는 MySQL만 실행하며 backend/Agent는 로컬 Python 프로세스로 실행합니다.
- AI 스택(langchain/langchain-openai/langgraph/langfuse/openai)도 이 파일 안에 함께 고정되어 있으며, BE가 나머지 8개 패키지와 같은 가상환경에 동시 설치해 충돌 없음을 확인했고, AI팀이 `backend/`에서 별도로 재현한 버전과 정확히 일치함을 교차 확인했습니다(자세한 버전은 `docs/tech-stack.md` §6).

## 개발/배포/테스트 환경 (BE 확정)

| 항목 | 결정 |
|---|---|
| 배포 | Docker, `backend/Dockerfile`(`python:3.12-slim` + `pip install -r requirements.txt`) |
| 로컬 개발 | 루트 `docker-compose.yml`은 `db`=`mysql:8.0`만 실행. backend+Agent는 로컬 Python 프로세스 |
| 배포 실행 | Compose와 분리해 추후 확정. `backend/Dockerfile`은 존재하지만 현재 db-only Compose가 app을 빌드하지 않음 |
| 테스트 DB | `testcontainers[mysql]` — 테스트마다 격리된 MySQL 컨테이너를 코드로 직접 실행(compose와 별개 메커니즘, 이미지 버전만 `mysql:8.0`으로 통일) |
| 테스트 범위 | API 엔드포인트 테스트 + 서비스 로직 단위 테스트 |
| Agent 호출부 테스트 | 실제 LLM 호출 대신 `unittest.mock`으로 목 처리 |
| 커버리지 측정 | 도입 안 함 |
| 스케줄러 | **미정** (APScheduler 내장 vs 외부 cron) |

Redis는 이 확정 스택에 포함되어 있지 않습니다.

## Agent ↔ DB 연동 방식

- Agent와 API 서버는 같은 DB를 사용하지만 Agent가 SQL·ORM을 직접 호출하지 않는다.
- DB 접근 함수와 API는 BE가 구현하고, AI는 필요한 Agent Tool·입출력 schema를 정의해 해당 함수를 호출한다.
- DB 접근은 BE 함수 하나를 라우터와 Agent 연동부가 재사용한다. 현재 BE 코드는 `app/be/`에 있으며 Agent 연동부는 아직 연결되지 않았다.

## 디렉토리 역할

- `app/common/config.py` — BE 환경설정
- `app/be/` — DB 연결(`db.py`), 도메인 테이블(`models/`), 인증 입출력(`schemas/`), DB 접근(`crud/`), 서비스(`services/`), 라우터(`routers/`)
- `app/main.py` — FastAPI 진입점. 현재 인증 라우터와 health 경로만 연결돼 있습니다.
- `app/agent/` — LangGraph 런타임. 최초 입력·행동 결과·충돌 확인 뒤 `Procedure→Info→Support→Supervisor→Review`를 실행합니다. 일반화된 자율 Tool 선택은 MVP 제외 범위입니다. 모든 정상 초안은 Review Tool을 반드시 거칩니다(`docs/agent/architecture.md`).
  - `graph.py`, `state.py` — 최상위 그래프/공유 상태 정의
  - `supervisor/` — 수집 결과 평가, Blocker 1개·Next Action 1개 초안, Review 재작업 조정
  - `info_agent/` — 정보분석 Agent-as-Tool. 자기 분석 범위의 bounded Local Loop만 허용
  - `support_agent/` — 지원금 Agent-as-Tool. 근거 확보를 위한 bounded Local Loop만 허용
    - `wiki/` — 호출자가 주입하는 검수 Wiki 조회 인터페이스. 조회 실패 시 다른 자료로 채우지 않음
  - `procedure_tool/` — 호출자가 메모리에 적재한 공식 절차 자료 조회와 절차 실행 제약 검사. 요청 중 인터넷 수집을 하지 않으며 우선순위·Next Action은 결정하지 않음
  - `review_tool/` — 제공된 초안·Evidence만 독립 검토하는 필수 Tool. 검색·직접 수정·자체 루프 없음
  - `llm.py`, `tracing.py` — OpenAI-compatible `httpx` client(공용·Info·Supervisor/Review 설정), 모든 client가 공유하는 실행당 호출 예산(`LLMCallBudget`, 기본 40회), metadata-only trace interface와 `LangfuseTraceSink`(credential이 있을 때만 활성화)
- 독립된 `app/rules/` Rule 엔진은 두지 않는다. 입력·상태 전이·출력의 결정 가능한 제약은 코드 Guardrail로, 절차 정보 조회는 절차조회 Tool로 분리한다.

## Case / 검증 규칙

- 상태 전이 유효성과 충돌 자동 덮어쓰기 방지는 코드로 강제한다. 절차 후보와 조건은 절차조회 Tool이 반환하고 최종 순서는 Supervisor가 판단한다.
- API naming, Case validation 세부 규칙은 추가 예정
