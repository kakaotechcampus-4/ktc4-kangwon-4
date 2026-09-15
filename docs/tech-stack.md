# RE:BORN 기술 스택 상태표

> 기준일: 2026-09-15
>
> 이 문서의 책임: **manifest 선언 버전과 현재 코드 사용 여부**

아키텍처, Agent schema, 실행법, 크롤링·RAG 구현 계획, BE 계약은 각각의 전용 문서에서 관리한다. 이 문서에 package가 있다고 해서 해당 기능이 구현됐거나 운영 중이라는 뜻은 아니다.

## 0. 상태 표기

| 표기 | 의미 |
|---|---|
| `[CURRENT_CODE]` | 현재 호출 경로에서 import·사용됨 |
| `[IMPLEMENTED_NOT_WIRED]` | 코드·테스트는 있으나 현재 application/Graph 경로에는 미연결 |
| `[CURRENT_CONFIG]` | 설정 파일이 존재함; 배포 성공을 뜻하지 않음 |
| `[PINNED_MANIFEST]` | manifest에 버전이 고정됨; 기능 구현·설치 성공을 뜻하지 않음 |
| `[PLANNED_NOT_IMPLEMENTED]` | 채택 방향 또는 구현 목표지만 현재 기능 코드가 없음 |
| `[NOT_PRESENT]` | 확인한 경로에 구현이 없음 |
| `[TBD]` | 공동 결정 전 |

## 1. 프론트엔드 manifest

| 기술 | 선언 | 상태·근거 |
|---|---:|---|
| React / React DOM | `^19.2.8` | `[PINNED_MANIFEST]` `frontend/package.json` |
| TypeScript | `~6.0.2` | `[PINNED_MANIFEST]` |
| Vite | `^8.2.2` | `[PINNED_MANIFEST][CURRENT_CONFIG]` scripts와 config 존재 |
| Tailwind CSS | `^4.3.3` | `[PINNED_MANIFEST][CURRENT_CONFIG]` Vite plugin 설정 존재 |
| React Router | 없음 | `[NOT_PRESENT]` 현재 URL query를 직접 읽음 |
| API client | 없음 | `[NOT_PRESENT]` 현재 `frontend/src`에 별도 client/fetch 경계 없음 |
| Vercel | 버전 대상 아님 | `[CURRENT_CONFIG]` `frontend/vercel.json` 존재; 실제 배포 상태는 별도 |

lockfile의 해석 버전과 실행·배포 검증은 package 선언과 별개다. 프론트엔드 구현 상세는 이 문서 범위가 아니다.

## 2. BE와 로컬 인프라

| 영역 | 상태 | 현재 사실 |
|---|---|---|
| FastAPI/Uvicorn | `[PINNED_MANIFEST][NOT_PRESENT]` | package는 있으나 `backend/app/main.py`와 API route가 없음 |
| DB/ORM/migration | `[PINNED_MANIFEST][PLANNED_NOT_IMPLEMENTED]` | SQLAlchemy·PyMySQL·Alembic은 선언됐지만 model/session/migration 없음 |
| 인증 | `[PINNED_MANIFEST][PLANNED_NOT_IMPLEMENTED]` | PyJWT는 선언됐지만 Kakao OAuth·JWT route/정책 없음 |
| MySQL | `[CURRENT_CONFIG]` | 루트 `docker-compose.yml`이 MySQL 8.0 DB만 실행 |
| Backend/Agent container | `[NOT_PRESENT]` | Compose에 포함되지 않음; `backend/Dockerfile`의 `app.main:app` 진입점은 현재 없음 |
| Redis | `[NOT_PRESENT]` | service와 사용 코드 없음 |
| Python | `[CURRENT_CONFIG]` | `backend/.python-version`, Dockerfile 모두 3.12 |
| 배포 | `[TBD]` | 운영 호스팅·배포 방식 미결정 |

DB-only Compose는 합의된 로컬 인프라 경계다. Agent standalone은 DB를 사용하지 않는다.

## 3. Agent runtime

| 영역 | 상태 | 현재 사실 |
|---|---|---|
| Pydantic | `[CURRENT_CODE]` | strict Agent/Tool schema와 validation |
| LangGraph | `[CURRENT_CODE]` | 고정 dependency와 Review 재작업 orchestration |
| LangChain | `[PINNED_MANIFEST]` | 현재 `backend/app/agent` runtime import 없음 |
| LLM transport | `[CURRENT_CODE]` | `httpx`로 OpenAI-compatible endpoint 직접 호출 |
| `openai` SDK | `[PINNED_MANIFEST]` | 현재 Agent runtime import 없음 |
| `langchain-openai` | `[PINNED_MANIFEST]` | 현재 Agent runtime import 없음 |
| tracing | `[CURRENT_CODE]` | metadata-only `TraceSink`; 기본 `NullTraceSink` |
| Langfuse | `[PINNED_MANIFEST][PLANNED_NOT_IMPLEMENTED]` | adapter와 token/cost 전송 경로 없음 |
| BizInfo discovery | `[IMPLEMENTED_NOT_WIRED]` | raw 후보 adapter가 Graph·CLI 판정과 분리됨 |
| Chroma/RAG | `[PINNED_MANIFEST][PLANNED_NOT_IMPLEMENTED]` | corpus·index·retriever·Graph 연결 없음 |

현재 프레임워크를 “LangChain과 LangGraph를 모두 사용한다”고 표현하면 부정확하다. 현재 실행 orchestration은 LangGraph이고, LLM 호출은 `httpx` 직접 구현이다. LangChain·OpenAI SDK·Langfuse·Chroma는 dependency 선언과 현재 기능 사용을 구분해야 한다.

자세한 호출 구조는 [`architecture.md`](./architecture.md), 실행 상태는 [`agent-standalone-runtime-requirements.md`](./agent-standalone-runtime-requirements.md), 크롤링·RAG 단계는 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md)를 따른다.

## 4. 기술별 현재/목표 경계

### 4.1 BE application과 DB

| 기술 | 현재 | 목표가 완료되는 조건 |
|---|---|---|
| MySQL | DB container만 구성 | BE model·migration·transaction·통합 테스트 존재 |
| FastAPI | package만 선언 | app/route/auth/Agent adapter와 endpoint test 존재 |

### 4.2 Agent orchestration과 공식 데이터

| 기술 | 현재 | 목표가 완료되는 조건 |
|---|---|---|
| LangGraph | 현재 Graph에서 사용 | 현재 기능은 완료; 동적 Supervisor planning은 별도 목표 |
| 외부 공식 API | Procedure fetch와 BizInfo adapter 일부 | 출처별 adapter·실측·failure semantics·Evidence 연결 완료 |

### 4.3 관측성

| 기술 | 현재 | 목표가 완료되는 조건 |
|---|---|---|
| Langfuse | package만 선언 | masking 정책 승인 + adapter + token/cost/latency 전송 검증 |

### 4.4 지원금 지식/RAG 상태

`[CURRENT_CODE]` Support Agent는 주입된 reviewed catalog만 읽고, `[IMPLEMENTED_NOT_WIRED]` BizInfo adapter는 raw 후보만 만든다. Chroma와 `langchain-chroma`는 `[PINNED_MANIFEST][PLANNED_NOT_IMPLEMENTED]`이며 아직 index나 조회 경로가 없다. 검수 corpus + versioned index + retriever + 평가 + Graph 연결이 모두 생겨야 완료다. 구현 순서와 완료 조건은 [`agent-official-data-source-strategy.md`](./agent-official-data-source-strategy.md) §7을 기준으로 한다.

## 5. 문서 경계

| 내용 | 관리 문서 |
|---|---|
| 구성요소와 호출 방향 | `docs/architecture.md` |
| Agent/Tool exact schema | `docs/agent-tool-io-schema.md` |
| standalone 명령·환경변수·검증 | `docs/agent-standalone-runtime-requirements.md` |
| 공식 API·크롤링·RAG 구현 | `docs/agent-official-data-source-strategy.md` |
| BE shared/HTTP/저장 계약 제안 | `docs/be-agent-integration-requirements.md` |

## 6. `[PINNED_MANIFEST]` Python package 선언 버전

이 §6은 사람이 읽는 팀 공용 버전·상태 요약표이고, 설치에 적용되는 machine-readable 최종 권위는 `backend/requirements.txt`와 `backend/requirements-dev.txt`다. 두 곳의 숫자가 다르면 drift이며 같은 PR에서 고친다. `==` pin은 설치 요청 버전이고 기능 사용 여부는 마지막 열에서 따로 판단한다.

| package | 선언 버전 | 현재 기능 상태 |
|---|---:|---|
| fastapi | 0.141.1 | `[NOT_PRESENT]` app·route 없음 |
| uvicorn[standard] | 0.52.4 | `[NOT_PRESENT]` 실행 가능한 app 없음 |
| pydantic | 2.13.5 | `[CURRENT_CODE]` Agent schema |
| sqlalchemy | 2.0.52 | `[PLANNED_NOT_IMPLEMENTED]` |
| pymysql | 1.2.0 | `[PLANNED_NOT_IMPLEMENTED]` |
| alembic | 1.19.2 | `[PLANNED_NOT_IMPLEMENTED]` |
| pyjwt | 2.13.0 | `[PLANNED_NOT_IMPLEMENTED]` |
| httpx | 0.28.1 | `[CURRENT_CODE]` LLM·절차조회·BizInfo adapter |
| pydantic-settings | 2.15.0 | `[PINNED_MANIFEST]` 현재 `backend/app/config.py` 없음 |
| python-dotenv | 1.2.3 | `[CURRENT_CODE]` Agent 환경파일 로드 |
| langchain | 1.4.0 | `[PINNED_MANIFEST]` runtime import 없음 |
| langchain-openai | 1.6.0 | `[PINNED_MANIFEST]` runtime import 없음 |
| langgraph | 1.2.11 | `[CURRENT_CODE]` AgentGraph |
| langfuse | 4.15.1 | `[PLANNED_NOT_IMPLEMENTED]` |
| openai | 3.8.0 | `[PINNED_MANIFEST]` runtime import 없음 |
| langchain-chroma | 1.1.0 | `[PLANNED_NOT_IMPLEMENTED]` |
| chromadb | 1.5.9 | `[PLANNED_NOT_IMPLEMENTED]` |
| pytest (dev) | 9.1.1 | `[CURRENT_CODE]` Agent tests |
| testcontainers[mysql] (dev) | 4.15.0 | `[PINNED_MANIFEST]` BE DB 통합 test 없음 |

## 7. 근거 우선순위

1. 실제 import와 호출 경로
2. 자동화 test
3. package manifest와 config
4. 이 문서

따라서 manifest 주석이나 Markdown이 현재 코드와 충돌하면 코드와 test를 기준으로 상태를 수정한다. package 버전 변경은 manifest가 기준이다.
