# RE:BORN 기술 선택·현재 구현·목표 구조 상태표 (팀 공유용)

> 이 문서는 기술 **선택**, manifest **버전 선언**, 현재 **코드 구현**, 앞으로의 **제안**을 구분합니다. 아래 표기를 생략한 문장을 구현 완료로 해석하면 안 됩니다.
>
> - `[CURRENT_CODE]`: 저장소에 코드가 있고 현재 호출 경로에서 사용됨
> - `[IMPLEMENTED_NOT_WIRED]`: 구현·테스트 코드는 있으나 현재 application 호출 경로에는 연결되지 않음
> - `[CURRENT_CONFIG]`: 저장소에 설정 파일이 있음. 배포·운영 성공까지 뜻하지 않음
> - `[PINNED_MANIFEST]`: manifest에 버전이 선언됨. 현재 환경 설치나 기능 구현을 뜻하지 않음
> - `[OBSERVED_YYYY-MM-DD]`: 해당 날짜의 제한된 실행·API 관찰. 운영 보장을 뜻하지 않음
> - `[REPORTED]`: 외부 전달 자료나 파일 주석에 기록된 결과. 이 저장소에서 재현 증거를 확인한 상태가 아님
> - `[DECIDED_NOT_IMPLEMENTED]`: 기술 방향은 선택됐지만 해당 기능 코드가 없음
> - `[TARGET_UNIMPLEMENTED]`: 팀 합의가 더 필요할 수 있는 목표·제안이며 현재 코드가 없음
> - `[NOT_PRESENT]`: 확인한 manifest·경로에 존재하지 않음
> - `[PARTIAL_VIEW]`: 관련 경로만 보여 주며 전체 저장소 구조를 뜻하지 않음
> - `[TBD]`: 미결정
>
> 실제 운영 지침은 `/CLAUDE.md`, `/frontend/CLAUDE.md`, `/backend/CLAUDE.md`가 우선입니다.

## 0. 현재 실행 경계

- `[CURRENT_CODE]` BE/Agent Python 영역에서 현재 제공되는 application 실행 진입점은 `backend/app/agent/cli.py`뿐입니다. 이 CLI는 `--live`와 LLM 환경변수가 필요한 `AgentGraph` 기반 standalone 실행이며 Agent 테스트도 존재합니다.
- `[NOT_PRESENT]` `backend/app/main.py`, `backend/app/api/`, `backend/app/shared/`가 없으므로 현재 FastAPI 서버, 인증 API, DB persistence, BE↔Agent HTTP 연동은 실행할 수 없습니다.
- `[CURRENT_CONFIG]` `backend/Dockerfile`은 존재하지만 진입점으로 지정한 `app.main:app`이 `[NOT_PRESENT]`이므로 현재 상태 그대로는 API 컨테이너 실행 근거가 되지 않습니다.
- 이 경계는 **BE/Agent Python 영역**에 대한 설명입니다. 프론트엔드의 화면별 기능 동작은 이 문서에서 감사하지 않았습니다.

## 1. 프론트엔드 manifest 확인 결과

> `[PINNED_MANIFEST]` 아래 내용은 `frontend/package.json`과 `frontend/package-lock.json`을 대조한 결과입니다. 화면 기능·API 연동·배포 성공 여부를 확인한 표가 아닙니다.

| 구분 | 상태 | 저장소에서 확인된 내용 |
|---|---|---|
| React | `[PINNED_MANIFEST]` | 선언 `^19.2.8`, lockfile 해석 버전 `19.2.8` |
| React DOM | `[PINNED_MANIFEST]` | 선언 `^19.2.8`, lockfile 해석 버전 `19.2.8` |
| TypeScript | `[PINNED_MANIFEST]` | 선언 `~6.0.2`, lockfile 해석 버전 `6.0.3` |
| Vite | `[PINNED_MANIFEST]` | 선언 `^8.2.2`, lockfile 해석 버전 `8.2.2` |
| Tailwind CSS | `[PINNED_MANIFEST][CURRENT_CONFIG]` | `tailwindcss`와 `@tailwindcss/vite`가 `^4.3.3`; Vite plugin 설정 존재 |
| 라우팅 | `[NOT_PRESENT]` | React Router package와 router 설정이 없음. 현재 `App.tsx`는 URL query를 직접 읽음 |
| 서버 통신 | `[NOT_PRESENT]` | 별도 API client 또는 현재 `src`의 `fetch` 호출을 확인하지 못함 |
| 배포 | `[CURRENT_CONFIG]` | `frontend/vercel.json` rewrite 설정은 존재. 실제 Vercel 배포 상태는 감사하지 않음 |
| Node.js 기준 | `[TBD]` | `package.json`에 `engines` 선언이 없어 22 LTS를 확정값으로 볼 수 없음 |
| 제품 방향 | `[TARGET_UNIMPLEMENTED]` | Mobile-First·상태 관리 방식 등은 별도 제품/FE 합의와 구현 확인이 필요 |

## 2. 백엔드

| 구분 | 상태 | 저장소에서 확인된 내용 / 제안 |
|---|---|---|
| API 서버 | `[PINNED_MANIFEST][NOT_PRESENT]` | FastAPI·Uvicorn 버전은 선언됐지만 `app.main:app`과 API route가 없음 |
| Agent ↔ DB 연동 | `[TARGET_UNIMPLEMENTED]` | BE `shared/functions`를 단일 DB 접근 경계로 두자는 제안. 현재 standalone Agent에는 DB 함수·persistence가 없음 |
| DB / ORM | `[CURRENT_CONFIG][DECIDED_NOT_IMPLEMENTED]` | MySQL 8.0 Compose는 존재. SQLAlchemy·PyMySQL·Alembic pin은 있으나 model·migration·Agent 연결 코드는 없음 |
| 인증 | `[DECIDED_NOT_IMPLEMENTED]` | 카카오 OAuth + 자체 Access/Refresh JWT(PyJWT) 방향. auth route·token 정책은 미구현/TBD |
| 카카오 인증 API 호출 | `[DECIDED_NOT_IMPLEMENTED]` | `httpx` 사용 방향만 있으며 카카오 인증 호출 코드는 없음 |
| 패키지 선언 방식 | `[PINNED_MANIFEST]` | `backend/requirements.txt`의 `==` pin과 plain pip 설치 명령을 사용. `pyproject.toml`/`uv.lock`은 없음 |
| 설치 호환성 | `[REPORTED]` | `backend/requirements.txt` 주석과 외부 BE 기술 자료에 `pip check`·import 교차검증 결과가 기록됨. pin 자체와 달리 이 문서는 그 과거 환경을 재현 증명하지 않음 |
| 로컬 인프라 | `[CURRENT_CONFIG]` | 루트 `docker-compose.yml`은 MySQL 8.0 서비스만 정의. backend와 Agent는 Compose에 없음 |
| 배포 | `[TBD]` | 호스팅/배포 방식 미결정. 현재 Dockerfile은 누락된 FastAPI 진입점 때문에 실행 가능한 API 증거가 아님 |
| 테스트 | `[CURRENT_CODE]` | Agent pytest가 존재하며 provider mock을 사용. `[PINNED_MANIFEST][TARGET_UNIMPLEMENTED]` BE DB 통합 테스트 코드는 없고 `testcontainers[mysql]` pin만 존재 |
| 스케줄러 | `[TBD]` | APScheduler 내장 또는 외부 cron 중 미결정 |
| Python 기준 | `[CURRENT_CONFIG]` | `backend/.python-version`과 `backend/Dockerfile`은 Python 3.12를 지정 |

`[NOT_PRESENT]` Redis 실행 서비스와 사용 코드는 이 저장소에서 확인되지 않았습니다. 환경변수 예시는 기능 구현 근거가 아닙니다.

## 3. Agent

| 구분 | 상태·기술 | 현재 코드와의 관계 |
|---|---|---|
| LLM Provider | `[CURRENT_CODE]` OpenAI-compatible chat endpoint | `StructuredLLMClient`가 환경변수로 받은 endpoint를 `httpx`로 직접 호출. OpenAI SDK/LangChain 경유 아님 |
| 모델 | `[OBSERVED_2026-09-15]` proxy에서 GPT-4.1 mini 확인 | 생산 모델/endpoint는 `[TBD]`; 간헐적 safe failure 존재 |
| LangChain | `[PINNED_MANIFEST]` | 버전만 선언됨. 현재 `backend/app/agent` runtime import 없음 |
| 에이전트 오케스트레이션 | `[CURRENT_CODE]` LangGraph | `AgentGraph`의 고정 dependency와 Review routing에 사용 |
| 관측성 | `[CURRENT_CODE]` metadata-only `TraceSink`; `[TARGET_UNIMPLEMENTED]` Langfuse adapter | Langfuse 버전 pin은 있으나 trace·token·비용 전송 adapter는 없음 |
| 지원금 지식베이스 | `[TARGET_UNIMPLEMENTED]` LLM Wiki + Obsidian | 현재 Support Agent는 합성 reviewed catalog 주입 |
| 벡터스토어/임베딩 | `[DECIDED_NOT_IMPLEMENTED][PINNED_MANIFEST]` Chroma 방향 | index·resolver·RAG 호출 경로 없음 |
| Agent 구성 | `[CURRENT_CODE]` Supervisor + 정보분석·지원금 + 절차조회 + Review | AgentGraph가 호출 순서와 재작업 routing을 집행. 동적 Supervisor planning은 `[TARGET_UNIMPLEMENTED]` |

정확한 **선언 버전**은 §6을 참고합니다. `[REPORTED]` 과거 동시 설치·충돌 검증 내용은 `backend/requirements.txt` 주석과 외부 자료에 기록돼 있지만, 이는 `[PINNED_MANIFEST]`라는 저장소 사실이나 각 기능의 `[CURRENT_CODE]` 여부와 별개입니다.

## 4. 프로젝트 문서/디렉토리 구조

### 4.1 `[CURRENT_CONFIG]` CLAUDE.md 2단 구조

- **루트 `/CLAUDE.md`**: FE/BE/Agent 공통 원칙 (서비스 정의, Hero Loop, 하지 않는 것, 역할 경계, 개인정보, 용어, 참조 문서, 레포 운영, 문서 소유권)
- **파트별 `CLAUDE.md`**: 각 파트에서만 필요한 구현 규칙 (`frontend/CLAUDE.md`, `backend/CLAUDE.md`)
- CLAUDE.md에는 변하지 않는 원칙만 둡니다. `[TARGET_UNIMPLEMENTED]` 반복되는 디렉터리·작업 지침을 Skill로 분리할 경우 정확한 Skill 구조는 해당 구현 작업에서 별도로 정합니다.

### 4.2 `[PARTIAL_VIEW]` 현재 존재하는 관련 경로

```
ktc4-kangwon-4/
├─ docker-compose.yml          # MySQL 8.0 서비스만 정의
├─ frontend/
│  ├─ package.json
│  ├─ package-lock.json
│  ├─ vite.config.ts
│  ├─ vercel.json
│  └─ src/
└─ backend/
   ├─ Dockerfile             # 파일은 있으나 app.main:app은 없음
   ├─ requirements.txt       # runtime dependency pin
   ├─ requirements-dev.txt   # test dependency pin
   ├─ tests/agent/           # Agent 테스트
   └─ app/
      └─ agent/
         ├─ cli.py             # standalone 실행 진입점
         ├─ graph.py           # 고정 LangGraph orchestration
         ├─ state.py           # 현재 AgentGraph 내부 state
         ├─ schemas.py         # 현재 Agent 내부 schema
         ├─ supervisor/        # 수집 결과 기반 초안 생성
         ├─ info_agent/        # 정보분석
         ├─ support_agent/     # 지원금 분석 + 미연결 공식 후보 discovery adapter
         ├─ procedure_tool/    # 인터넷 절차조회
         ├─ review_tool/       # 필수 Review
         ├─ llm.py             # httpx 기반 structured LLM client
         └─ tracing.py         # metadata-only sink 경계
```

이 트리는 **현재 저장소 전체 목록이 아니라 이번 경계 판단에 필요한 일부 경로**입니다. 특히 `main.py`, `api/`, `shared/`를 단순 생략한 것이 아니라 실제로 존재하지 않음을 §0에서 별도로 명시했습니다.

### 4.3 `[TARGET_UNIMPLEMENTED][PARTIAL_VIEW]` BE 연동 시 제안하는 추가 책임

> 아래는 현재 파일 목록이 아니라 **공동 검토가 필요한 목표 구조 예시**입니다. 경로명과 최종 소유자는 BE/AI 합의 전까지 확정 계약이 아닙니다.

```
backend/app/
├─ main.py                  # FastAPI 진입점 제안
├─ config.py                # BE runtime 설정 경계 제안
├─ api/                     # 인증·Case·Agent route 제안
├─ shared/
│  ├─ db.py                 # DB session 제안
│  ├─ models/               # BE 영속 모델 제안
│  ├─ schemas/              # 승인된 HTTP/DB 경계 schema 제안
│  └─ functions/            # API와 Agent adapter가 공유할 DB 함수 제안
└─ agent/
   ├─ integrations/          # 승인된 BE 함수/HTTP adapter 제안
   ├─ support_agent/
   │  ├─ wiki/               # 검토된 지원금 지식 저장소 제안
   │  └─ rag/                # Wiki miss/갱신용 RAG 제안
   └─ langfuse_adapter.py    # 기존 TraceSink 구현체 제안
```

`shared/functions/` 제안의 근거는 DB 접근 구현을 API와 Agent adapter에 중복하지 않기 위해서입니다. 다만 함수 목록·transaction 경계·경로는 BE가 구현 전에 승인해야 합니다. 독립 Rule 엔진 디렉터리를 두지 않는 방향도 제안이며, Input / State Transition / Output Guardrail의 실제 코드 위치와 소유자는 구현 PR에서 확정해야 합니다.

### 4.4 Agent 내부 책임 — 현재와 목표 분리

| 영역 | `[CURRENT_CODE]` 현재 책임 | `[TARGET_UNIMPLEMENTED]` 제안 책임 |
|---|---|---|
| Graph | AgentGraph가 첫 호출, 고정 순서, Review 재작업 routing 집행 | Supervisor 계획을 검증한 뒤 동적으로 호출·재호출하는 router |
| Supervisor | 이미 수집된 결과로 초안 생성 | 전역 호출 계획 제안 |
| 정보분석·지원금 | 각각 bounded Local Loop 수행 | 승인된 BE adapter와 공식 catalog 갱신 경로 사용 |
| 절차조회·Review | 서로를 호출하지 않는 일반 Tool; 정상 Supervisor 초안은 Review 필수 | 현재 불변식 유지 |
| Tracing | metadata-only TraceSink/Null·Memory 구현 | Langfuse 전송 adapter와 운영 정책 |
| Persistence | 없음 | 승인된 BE 경계를 통한 저장·CAS·idempotency |

### 4.5 `[TARGET_UNIMPLEMENTED]` 지원금 지식 흐름 (LLM Wiki + RAG)

현재 이 경로는 구현되지 않았습니다. 도입 시에는 Wiki 우선, Wiki miss·정보 업데이트 때만 RAG를 사용하는 목표이며 상세 흐름은 **`docs/architecture.md` §6**을 참고합니다.

### 4.6 문서 소유권

문서 소유권은 `/CLAUDE.md` "문서 소유권" 표가 canonical입니다(여기서 복제하지 않음).

## 5. 핵심 제품 원칙

전체 원칙(서비스 정의, Hero Loop, 하지 않는 것, 역할 경계)은 `/CLAUDE.md`가 canonical입니다 — 이 문서는 기술 스택 요약이므로 제품 원칙을 복제하지 않습니다.

## 6. `[PINNED_MANIFEST]` Python 패키지 선언 버전 — 설치·기능 구현과 무관

> 이 표의 단일 출처는 `backend/requirements.txt`입니다. `==` pin은 설치를 요청할 버전일 뿐, 모든 개발 환경에 실제 설치됐거나 `pip check`를 통과했다는 뜻이 아닙니다. `[REPORTED]` 과거 호환성 검증 기록과 현재 코드 사용 여부도 별도 열로 구분합니다.

| 패키지 | 선언 버전 | 현재 코드 사용/기능 상태 |
|---|---|---|
| fastapi | 0.141.1 | `[NOT_PRESENT]` FastAPI app·route 없음 |
| uvicorn[standard] | 0.52.4 | `[NOT_PRESENT]` 실행할 `app.main:app` 없음 |
| pydantic | 2.13.5 | `[CURRENT_CODE]` Agent 내부 schema·validation |
| sqlalchemy | 2.0.52 | `[DECIDED_NOT_IMPLEMENTED]` model·session 없음 |
| pymysql | 1.2.0 | `[DECIDED_NOT_IMPLEMENTED]` Agent/BE DB 연결 코드 없음 |
| alembic | 1.19.2 | `[DECIDED_NOT_IMPLEMENTED]` migration 환경·revision 없음 |
| pyjwt | 2.13.0 | `[DECIDED_NOT_IMPLEMENTED]` 인증 발급·검증 코드 없음 |
| httpx | 0.28.1 | `[CURRENT_CODE]` Agent LLM·절차조회 HTTP client. `[IMPLEMENTED_NOT_WIRED]` 지원금 후보조회 adapter. 카카오 인증 API는 미구현 |
| pydantic-settings | 2.15.0 | `[NOT_PRESENT]` BE `app/config.py` 없음 |
| python-dotenv | 1.2.3 | `[CURRENT_CODE]` Agent LLM 환경파일 로드 |
| langchain | 1.4.0 | `[PINNED_MANIFEST]` 현재 Agent runtime import 없음 |
| langchain-openai | 1.6.0 | `[PINNED_MANIFEST]` 현재 Agent runtime import 없음 |
| langgraph | 1.2.11 | `[CURRENT_CODE]` AgentGraph orchestration |
| langfuse | 4.15.1 | `[TARGET_UNIMPLEMENTED]` adapter 없음 |
| openai | 3.8.0 | `[PINNED_MANIFEST]` SDK는 현재 Agent runtime에서 사용하지 않음 |
| langchain-chroma | 1.1.0 | `[TARGET_UNIMPLEMENTED]` RAG adapter·index 없음 |
| chromadb | 1.5.9 | `[TARGET_UNIMPLEMENTED]` vector store 초기화·조회 경로 없음 |

`[CURRENT_CONFIG]` Python 기준은 `backend/.python-version`의 3.12와 `backend/Dockerfile`의 `python:3.12-slim`입니다. 선언된 패키지 설치 명령은 `pip install -r backend/requirements.txt`이며, 실행 환경별 설치·호환성 검증은 별도로 수행해야 합니다.

---

## 출처

| 범위 | 상태 | 근거·출처 |
|---|---|---|
| §0 BE/Agent 실행 경계 | `[CURRENT_CODE][NOT_PRESENT]` | `backend/app/agent/`, `backend/tests/agent/`의 존재와 `backend/app/main.py`, `backend/app/api/`, `backend/app/shared/`의 부재 |
| §1 프론트엔드 버전·설정 | `[PINNED_MANIFEST][CURRENT_CONFIG]` | `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, `frontend/vercel.json` |
| §2 BE manifest·로컬 인프라 | `[PINNED_MANIFEST][CURRENT_CONFIG]` | `backend/requirements.txt`, `backend/requirements-dev.txt`, `backend/Dockerfile`, `docker-compose.yml`, `backend/.python-version` |
| §2 기술 선택·과거 설치 검증 | `[REPORTED]` | 이전에 공유된 BE 기술스택 자료와 `backend/requirements.txt` 주석. 현재 저장소가 보장하는 재현 결과로 취급하지 않음 |
| §3 Agent 현재 사용 | `[CURRENT_CODE]` | `backend/app/agent/graph.py`, `llm.py`, `tracing.py`, 각 Agent/Tool 구현과 `backend/tests/agent/` |
| §3 dated provider 관찰 | `[OBSERVED_2026-09-15]` | 당시 팀 proxy의 `/models` 및 제한된 호출 결과. 운영 가용성·SLO 근거가 아님 |
| §4.2 현재 경로 | `[PARTIAL_VIEW]` | 해당 경로의 실제 존재 여부를 기준으로 작성 |
| §4.4 현재 Agent 책임 | `[CURRENT_CODE]` | `backend/app/agent/graph.py`, Supervisor/Agent/Tool 구현, `tracing.py` |
| §4.3, §4.4 목표 열, §4.5 | `[TARGET_UNIMPLEMENTED]` | `docs/architecture.md`, `docs/agent-tool-io-schema.md`, `docs/be-agent-integration-requirements.md`의 제안 사항 요약 |
| §5 제품 원칙 | `[CURRENT_CONFIG]` | `/CLAUDE.md`에 위임 |
| §6 Python 선언 버전 | `[PINNED_MANIFEST]` | `backend/requirements.txt`; 실제 설치·호환성은 환경별 별도 검증 |
