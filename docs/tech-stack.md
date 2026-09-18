# RE:BORN 기술 스택과 현재 사용 상태

> 기준일: 2026-09-15
>
> 이 문서의 책임: 패키지 선언 버전과 현재 코드의 실제 사용 여부

패키지가 `requirements.txt`나 `package.json`에 있다고 해서 해당 기능이 구현됐거나 운영 중이라는 뜻은 아니다. 이 문서는 **설치 목록**과 **실제 실행 코드**를 구분한다.

## 1. 먼저 보는 결론

- 현재 Agent 실행은 **Pydantic, LangGraph, httpx**를 사용한다.
- LLM은 LangChain이나 OpenAI SDK가 아니라 `httpx`로 OpenAI-compatible endpoint를 호출한다. endpoint는 하나로 고정돼 있지 않다 — `SUPERVISOR_*` 환경변수를 설정하면 Supervisor만 별도 provider·model을 쓰는 client를 따로 받고, 설정하지 않으면 전 구성요소가 공용 endpoint 하나를 그대로 공유한다(환경변수는 `agent-standalone-runtime-requirements.md`가 단일 출처).
- LangChain, OpenAI SDK와 Chroma는 설치 목록에 있지만 현재 Agent 실행에서는 사용하지 않는다. Langfuse는 credential이 설정된 경우에만 metadata 전송에 사용한다.
- 루트 `docker-compose.yml`은 **MySQL 8.0 DB만** 실행한다. Backend와 Agent container는 없다.
- FastAPI route, ORM, migration, 인증과 실제 Case 읽기·쓰기는 아직 구현되지 않았다.
- Support Agent는 생성 시 주입된 검수 catalog를 사용한다.
- 기업마당 raw 공고조회는 구현됐지만 전체 Agent 흐름에 연결되지 않았다.
- 공식 문서 crawler와 RAG도 아직 구현되지 않았다.

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
- **용도:** LLM, 공식 절차 원문과 기업마당 API 호출

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
- **pydantic-settings `2.15.0`:** 루트 `config.py`에서는 사용하지만 현재 Agent runtime은 import하지 않음

### Application·DB 관련 패키지

- **FastAPI `0.141.1`:** 버전은 선언됐지만 `backend/app/main.py`와 route가 없음
- **Uvicorn `0.52.4`:** 버전은 선언됐지만 실행 가능한 FastAPI app이 없음
- **SQLAlchemy `2.0.52`:** model과 session 미구현
- **PyMySQL `1.2.0`:** application DB 연결 미구현
- **Alembic `1.19.2`:** migration 미구현
- **PyJWT `2.13.0`:** Kakao OAuth와 서비스 JWT route·정책 미구현

MySQL은 container 설정만 존재한다. DB model, migration, transaction과 통합 테스트가 생겨야 DB 기능이 구현됐다고 판단한다.

### 후속 AI 기능용 패키지

- **Langfuse `4.15.1`:** `LangfuseTraceSink`로 metadata 전송 구현. 비용 금액 산출은 없음
- **langchain-chroma `1.1.0`:** corpus, index와 retriever 미구현
- **ChromaDB `1.5.9`:** Agent 조회 경로 미구현

### 개발 도구

- **pytest `9.1.1`:** 현재 Agent 테스트에 사용
- **testcontainers[mysql] `4.15.0`:** 버전만 선언. DB 통합 테스트는 아직 없음

## 5. 아직 없거나 연결되지 않은 기능

### Application과 DB

- FastAPI app과 API route
- SQLAlchemy model, DB session과 repository
- Alembic migration과 transaction
- Kakao OAuth와 서비스 JWT 인증
- 실제 Case snapshot adapter, 동시성 제어, 저장과 재조회
- Redis service와 Redis 사용 코드
- Compose의 Backend·Agent service
- 저장소에 없는 `app.main:app` 실행 진입점
- 아직 결정되지 않은 운영 호스팅과 배포 방식

### Agent와 공식 데이터

- **구현됐지만 미연결:** 기업마당 API의 raw 공고 후보를 조회하는 독립 adapter
- **미구현:** raw 공고 검수 → reviewed catalog 발행 → `AgentGraph` 연결 pipeline
- **미구현:** 승인된 공식 원문 crawler, parser, versioned corpus, index, retriever와 RAG 연결
- **미구현:** Supervisor가 필요한 Agent·Tool을 고르는 동적 호출 계획
- **미구현:** Langfuse 비용 금액 산출, masking 정책 승인

Support Agent의 현재 입력은 생성 시 주입된 reviewed catalog다. 검수 corpus, versioned index, retriever 평가, Evidence 변환과 Graph 연결이 모두 있어야 RAG가 완료됐다고 판단한다.

### Frontend

- 현재 `frontend/src`에서 별도 API client 또는 fetch 경계는 확인되지 않았다.

## 6. 관련 문서

- **Agent 호출 구조:** [`architecture.md`](./architecture.md)
- **Agent·Tool 공개 호출 입·출력:** [`agent-tool-io-schema.md`](./agent-tool-io-schema.md)
- **standalone 실행과 검증:** [`agent-standalone-runtime-requirements.md`](./agent-standalone-runtime-requirements.md)
- **공식 API·crawler·RAG 계획:** [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)
- **외부 연동 공동 검토 요청:** [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)

## 7. 버전과 상태의 근거

- **Python package:** `backend/requirements.txt`, `backend/requirements-dev.txt`
- **Frontend package:** `frontend/package.json`과 lockfile
- **Agent 실제 import와 호출:** `backend/app/agent/`
- **Agent 회귀 테스트:** `backend/tests/agent/`
- **Python·container 설정:** `backend/.python-version`, `backend/Dockerfile`, `docker-compose.yml`

`==` 또는 frontend version range는 설치 요청 버전이다. 실제 기능 사용 여부는 import, 호출 경로와 테스트로 별도 확인한다.
