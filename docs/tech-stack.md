# RE:BORN 기술 스택과 현재 사용 상태

> 기준일: 2026-09-23
>
> 이 문서의 책임: 패키지 선언 버전과 현재 코드의 실제 사용 여부

패키지가 `requirements.txt`나 `package.json`에 있다고 해서 해당 기능이 구현됐거나 운영 중이라는 뜻은 아니다. 이 문서는 **설치 목록**과 **실제 실행 코드**를 구분한다.

## 1. 먼저 보는 결론

- 현재 Agent 실행은 **Pydantic, LangGraph, httpx**를 사용한다.
- LLM은 LangChain이나 OpenAI SDK가 아니라 `httpx`로 OpenAI-compatible endpoint를 호출한다. `SUPERVISOR_*` 환경변수를 설정하면 Supervisor와 독립 Review 호출이 같은 별도 client를 사용하고, 미설정 시 공용 endpoint 설정을 사용한다. 환경변수는 [`.env.example`](../.env.example)을 따른다.
- LangChain·OpenAI SDK·Chroma는 `backend/requirements.txt`에 고정돼 있지만 Agent 코드에 import가 없다. Langfuse는 credential이 설정된 경우에만 metadata 전송에 사용한다.
- 루트 `docker-compose.yml`은 **MySQL 8.0 DB만** 실행한다. Backend와 Agent container는 없다.
- 현재 작업 트리에는 SQLModel 테이블, DB 세션, FastAPI 진입점과 카카오 인증 라우터가 있다. Agent를 호출하는 라우터와 Case 저장·재조회 연동, migration은 아직 없다.
- Support Agent는 생성 시 주입된 검수 catalog를 사용한다.
- 기업마당 adapter·공식 문서 crawler·RAG는 Agent에 없다. 지원·절차 자료는 사람이 검수해 주입한다.

## 2. 상태를 읽는 기준

- **현재 코드에서 사용:** 실제 실행 경로가 import하고 호출한다.
- **구현됐지만 미연결:** 코드와 테스트는 있지만 현재 application이나 `AgentGraph`가 호출하지 않는다.
- **설정만 존재:** 설정 파일은 있지만 실제 실행·배포 여부는 별도 확인이 필요하다.
- **버전만 선언:** manifest에 설치 버전만 고정돼 있다.
- **미구현:** 목표나 dependency는 있지만 기능 코드가 없다.
- **저장소에 없음:** 확인한 저장소 경로에 필요한 진입점이나 코드가 없다.
- **미정:** 팀 공동 결정이 필요하다.

상태가 충돌하면 실제 import와 호출 경로, 자동화 테스트, 설정, 이 문서 순서로 판단한다.

## 3. 현재 코드에서 사용하는 기술

### Agent 실행

#### Pydantic `2.13.5`

- **상태:** 현재 코드에서 사용
- **용도:** Agent·Tool의 strict schema와 validator

#### LangGraph `1.2.11`

- **상태:** 현재 코드에서 사용
- **용도:** 현재 코드로 정한 실행 경로와 Review 재작업 수행

#### httpx `0.28.1`

- **상태:** 현재 코드에서 사용
- **용도:** LLM 호출

#### python-dotenv `1.2.3`

- **상태:** 현재 코드에서 사용
- **용도:** Agent 환경변수 파일 로드

#### `TraceSink`

- **상태:** 추적 인터페이스 + credential이 있을 때 Langfuse 전송 사용
- **용도:** 실행·호출 metadata를 받을 수 있는 경계
- **현재:** credential이 없으면 아무 곳에도 보내지 않는 `NullTraceSink`, 있으면 `LangfuseTraceSink`가 구성요소별 상태·지연 시간·시도 횟수·model·token 수를 전송한다. prompt 원문과 evidence는 보내지 않는다.
- **제한:** token 수는 보내지만 비용 금액은 계산하지 않는다. 실행당 LLM 호출 횟수 상한(`llm.py`의 `LLMCallBudget`, 기본 40회)은 호출 수를 세어 막는 장치이지 비용 측정이 아니다.

현재 구조를 “LangChain과 LangGraph를 함께 사용한다”고 설명하면 부정확하다. 실행 순서 관리는 LangGraph, LLM HTTP 통신은 `httpx`가 담당한다.

### Frontend

- **React / React DOM `^19.2.8`:** entrypoint와 component에서 사용
- **React Router `^7.18.3`:** route 구성과 화면 이동에 사용
- **TypeScript `~6.0.2`:** TS/TSX source와 build에 사용
- **Vite `^8.2.2`:** script와 설정이 존재
- **Tailwind CSS `^4.3.3`:** CSS import와 Vite plugin 설정에 사용
- **Vercel:** `frontend/vercel.json` 설정이 존재하며 실제 배포 상태는 별도 확인 대상

### 로컬 실행 환경

- **Python `3.12`:** `backend/.python-version`과 Dockerfile 기준
- **MySQL `8.0`:** 루트 Compose가 DB service만 실행

Agent standalone은 MySQL을 사용하지 않는다. manifest와 lockfile은 설치 요청 상태를 보여주며 실제 빌드·배포 성공은 별도 검증이 필요하다.

## 4. 버전은 선언됐지만 현재 Agent 실행에서 사용하지 않는 기술

### Agent 관련 패키지

- **langchain `1.4.0`:** 버전만 선언. Agent runtime import 없음
- **langchain-openai `1.6.0`:** 버전만 선언. Agent runtime import 없음
- **openai `3.8.0`:** 버전만 선언. Agent runtime import 없음
- **pydantic-settings `2.15.0`:** `backend/app/common/config.py`에서 사용하지만 Agent runtime은 import하지 않음

### Application·DB 관련 패키지

- **FastAPI `0.141.1`:** `backend/app/main.py`가 인증 라우터와 health 경로를 연결
- **Uvicorn `0.52.4`:** FastAPI 실행 서버로 선언
- **SQLModel `0.0.42`:** `backend/app/be/models/`의 테이블과 `app/be/db.py`의 DB 세션에 사용. SQLAlchemy를 내부적으로 사용
- **PyMySQL `1.2.0`:** MySQL 연결에 사용
- **Alembic `1.19.2`:** migration 미구현
- **PyJWT `2.13.0`:** `backend/app/be/services/auth.py`에서 서비스 JWT 발급에 사용

DB 연결 코드의 존재가 Agent 변경 후보의 저장·재조회 완료를 뜻하지는 않는다.

### 후속 AI 기능용 패키지

- **Langfuse `4.15.1`:** `LangfuseTraceSink`로 metadata 전송 구현. 비용 금액 산출은 없음
- **langchain-chroma `1.1.0` / ChromaDB `1.5.9`:** Agent 코드에 import가 없다. MVP 제외 범위라 `backend/requirements.txt`에서 빼도 되는지 BE 확인 필요

### 개발 도구

- **pytest `9.1.1`:** 현재 Agent 테스트에 사용
- **testcontainers[mysql] `4.15.0`:** 버전만 선언. DB 통합 테스트는 아직 없음


### Agent와 공식 데이터

Agent 호출 구조는 [`agent/architecture.md`](./agent/architecture.md), 포함·제외 범위는 [`agent/README.md`](./agent/README.md)를 따른다. 여기서는 패키지와 직접 관련된 것만 적는다.

- **MVP 제외:** 기업마당 adapter, 미검수 공고 corpus·index·검색(`chromadb`), 공식 원문 crawler·parser, 요청 경로 RAG. 범위는 [`agent/README.md`](./agent/README.md)
- **미구현:** Langfuse 비용 금액 산출, masking 정책 승인

Support Agent의 입력은 생성 시 주입된 reviewed catalog뿐이다.


## 6. 관련 문서

- **Agent 문서 전체:** [`agent/README.md`](./agent/README.md)
- **Agent 호출 구조:** [`agent/architecture.md`](./agent/architecture.md)
- **Agent·Tool 입·출력:** `backend/app/agent/schemas.py` (문서가 아니라 검증자가 계약이다)
- **Agent 실행 경계:** [`agent/README.md`](./agent/README.md#실행-경계), [`runtime.py`](../backend/app/agent/runtime.py)

## 7. 버전과 상태의 근거

- **Python package:** `backend/requirements.txt`, `backend/requirements-dev.txt`
- **Frontend package:** `frontend/package.json`과 lockfile
- **Agent 실제 import와 호출:** `backend/app/agent/`
- **Python·container 설정:** `backend/.python-version`, `backend/Dockerfile`, `docker-compose.yml`

`==` 또는 frontend version range는 설치 요청 버전이다. 실제 기능 사용 여부는 import, 호출 경로와 테스트로 별도 확인한다.
