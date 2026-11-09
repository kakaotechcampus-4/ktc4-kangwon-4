# RE:BORN 기술 스택과 현재 사용 상태

기준일은 2026년 11월 9일이며, `develop`의 `52807ae` 구현을 확인했습니다. 패키지 설치 여부와 실제 실행 경로를 구분합니다. 화면별 설명과 테스트 시나리오는 [서비스 전체 설명서](final-guide/설명서.md)를 참고합니다.

## 현재 동작하는 전체 흐름

```text
React 화면 → FastAPI 인증과 요청 검증 → Case와 PENDING 저장
  → BackgroundTasks → Case snapshot과 검수 자료 → LangGraph
  → Procedure → Info → Supervisor → Review
  → 검수 결과를 BE가 MySQL에 저장 → 화면이 상태 조회
```

Case 생성, 실행 결과, 충돌 확인, 서류의 원상복구 조항 변경이 판단에 연결되어 있습니다. 공식 기관 신청·신고·연락은 사용자가 직접 합니다.

## Frontend

| 기술 | 현재 역할 |
| --- | --- |
| React 19와 TypeScript | 모바일 UI, 상태와 API 계약 타입 |
| Vite 8 | 개발 서버와 번들 빌드 |
| Tailwind CSS 4 | 의미 기반 디자인 토큰과 스타일 |
| React Router 7 | 인증 가드와 16개 경로 패턴 |
| Zustand 5 | 여러 진단 화면에 걸친 답만 sessionStorage에 저장 |
| Fetch API | `/api` 통신, Access-Token 헤더, 요청 제한 시간 |
| Motion 14.4.0 | 시트와 버튼 등 상호작용, 동작 줄이기 설정 반영 |
| Pretendard | 앱에 포함된 한글 본문 글꼴 |
| 다음 우편번호 | 주소 찾기를 열 때 불러오는 외부 스크립트 |

서버 데이터는 화면마다 다시 조회하고 `types/api.ts → adapters → types/view.ts → components`로 바꿔 표시합니다. FE에서 절차 우선순위를 계산하거나 저장 성공 전에 확정 상태를 바꾸지 않습니다.

Access·Refresh 토큰은 sessionStorage에 둡니다. OAuth state를 FE에서 생성·일회 검증하고, 401 재발급은 동시에 온 요청끼리 공유합니다. 토큰 저장은 XSS 보호의 완결을 뜻하지 않으며 Access 메모리 보관은 코드의 후속 과제입니다.

## Backend와 DB

| 기술 | 선언 버전 | 현재 역할 |
| --- | --- | --- |
| Python | 3.12 | API·Agent 공통 프로세스 |
| FastAPI | 0.141.1 | 인증·Case·로드맵·서류 라우터, OpenAPI |
| Uvicorn | 0.52.4 | ASGI 서버 |
| SQLModel | 0.0.42 | 도메인 모델·SQLAlchemy 세션·쿼리 |
| PyMySQL | 1.2.0 | MySQL 접속 |
| MySQL | 8.0.46 | 로컬·운영 Compose와 격리 테스트 DB |
| PyJWT | 2.13.0 | 카카오 인증 뒤 자체 JWT 발급·검증 |
| httpx | 0.28.1 | 카카오 API와 LLM HTTP 통신 |
| Pydantic | 2.13.5 | 요청·Agent 계약 검증 |
| python-multipart | 0.0.20 | 서류 업로드 요청 파싱 |

AI 대기 중에는 DB 커넥션을 반환하며 읽기·모델 대기·저장을 분리합니다. pool_size는 10, max_overflow는 20입니다. 같은 Case의 제출은 잠금으로 직렬화하고 저장 전 최신 상태를 대조합니다.

Case 상태·입력과 판단 이력·공식 자료·근거·충돌·검수 기록·절차 진행은 MySQL에 저장합니다. 공식 본문은 문서·버전별로 공유하고 Case 근거가 참조합니다. 전체 판단 snapshot을 DB에 영구 보관해 완전 재현하는 구조는 아직 아닙니다.

## Agent 실행

| 기술과 구성요소 | 현재 역할 |
| --- | --- |
| LangGraph 1.2.11 | 정해진 처리 경로와 제한된 재작업 연결 |
| httpx | OpenAI 호환 endpoint 직접 호출 |
| Pydantic | 입력·출력·근거·상태 전이 검사 |
| Procedure Tool | 주입된 검수 공식 자료 조회와 절차 제약 |
| Info | 입력 사실·진행·충돌 후보, 가능한 경로는 검수 정리본 또는 선택값으로 처리 |
| Supervisor | 검증된 후보에서 다음 행동 하나 선택 |
| Review | 필수 검수 경계, 제한된 조건의 코드 검수 또는 모델 검수와 코드 검사 |
| Langfuse 4.15.1 | credential이 있을 때 모델·토큰·지연·상태 등 metadata 추적 |

지원금 Agent는 구현이 남아 있지만 현재 MVP Graph에서 호출하지 않습니다. BE가 넘기는 지원 catalog도 비어 있습니다. 지원 자격·금액·현재 접수 가능 여부를 자동 확정하는 기능으로 설명하면 안 됩니다.

Info·Supervisor·Review는 환경 설정에 따라 별도 client를 사용할 수 있습니다. 한 실행의 기본 LLM 호출 예산은 40회, 실행 시간 제한은 420초, Review 재작업은 최대 2회입니다. 실제 호출 횟수나 지연의 보장값은 아닙니다.

검수된 정리본을 사용하는 첫 판단·충돌 확인 뒤 Info와 선택형 원상복구 입력은 모델 호출을 줄일 수 있습니다. 모델이 만든 사실·문장이 없고 첫 검수인 등의 조건에서는 code-only Review를 사용합니다. 모든 정상 결과는 Review 경계를 통과하지만 모든 결과가 Review LLM 호출을 거치는 것은 아닙니다.

- **상태:** 추적 인터페이스 + credential이 있을 때 Langfuse 전송 사용
- **용도:** 실행·호출 metadata를 받을 수 있는 경계
- **현재:** credential이 없으면 아무 곳에도 보내지 않는 `NullTraceSink`, 있으면 `LangfuseTraceSink`가 구성요소별 상태·지연 시간·시도 횟수·model·token 수와 `case_id`·선택 행동 코드·검수 이슈 코드/경로/심각도/담당 구성요소·재작업 대상을 전송한다. `case_id`는 외부 추적 기록을 해당 Case와 연결하는 값이다. 검수 이슈는 앞 20개와 전체 개수를 기록하며, prompt·evidence·사장님 글·검수의 자유 이유 문장은 보내지 않는다.
- **제한:** token 수는 보내지만 비용 금액은 계산하지 않는다. 실행당 LLM 호출 횟수 상한(`llm.py`의 `LLMCallBudget`, 기본 40회)은 호출 수를 세어 막는 장치이지 비용 측정이 아니다.

## 서류 처리

PyMuPDF 1.28.2와 로컬 한국어·영어 OCR로 PDF·사진을 읽습니다. 스캔 판독에는 가린 이미지의 모델 판독 경로도 있습니다. 문서 분류·추출·안전 검사를 거쳐 불확실한 값을 사용자에게 확인받습니다. 누락·금액·이름·날짜 대조는 코드 규칙으로 실행합니다.

서류는 PDF·PNG·JPG/JPEG, 20,000,000바이트 이하, 암호 없는 30쪽 이하를 받습니다. 서류 목록·추출값·점검 context는 MySQL의 `case_document_context`에, 원본·가림 PDF 등 파일 산출물은 Case별 파일 디렉터리에 저장합니다. 제출용 PDF는 현재 API에서 주민번호 뒷자리 가림 정책을 사용하며 모델용 가림과 구분합니다. 점검 통과와 현재 digest·정책·산출물을 대조한 뒤 ZIP을 제공합니다.

안전 검사 차단은 422의 detail.code로 AGENT_SAFETY_REFUSE·AGENT_SAFETY_CRISIS_SUPPORT를 전달하며 FE는 일반 재시도와 구분합니다.

카드 결제 대체 서류 경로는 아직 없습니다. 파일 업로드·점검·ZIP 다운로드는 기관 제출·접수 완료와 다릅니다.

## 선언돼 있지만 현재 Agent 실행에서 사용하지 않는 기술

LangChain·langchain-openai·OpenAI SDK·Chroma 관련 패키지는 requirements에 있지만 현재 Agent의 LLM 통신과 검색 경로를 구성하지 않습니다. 요청 중 웹 검색, 미검수 공고 수집, 벡터 검색 RAG는 현재 경로가 아닙니다. Alembic도 설치돼 있으나 버전별 migration 체계가 완성된 상태는 아닙니다. `backend/sql/`과 개별 migration 스크립트는 별도로 존재합니다.

## 실행과 배포

로컬 `docker-compose.yml`은 MySQL만 실행합니다. FE는 Vite, BE와 Agent는 로컬 Python 프로세스로 실행합니다. 운영 `docker-compose.prod.yml`은 MySQL과 FastAPI 컨테이너, DB·서류 볼륨을 구성합니다. Caddy와 Vercel 프록시 설정이 저장소에 있습니다. 설정의 존재는 현재 운영 배포 성공의 증거와 구분합니다.

`BackgroundTasks`는 영구 작업 큐가 아닙니다. 재시작 시 남은 PENDING을 실패로 풀어 복구합니다. `/health`는 앱 풀과 별도인 연결로 `SELECT 1`을 확인합니다. 성공은 200·`status: ok`, DB 오류는 503·`status: unavailable`이며 연결·읽기·쓰기 제한은 각각 2초입니다. `ENVIRONMENT=dev` 시작 시에는 테이블 초기화 코드가 있으므로 운영 DB에 연결해 실행하면 안 됩니다.

## 공개 개발 문서

로그인 없이 `/developers/`에서 29개 페이지를 제공합니다. API 24개·스키마·로드맵 26개 작업은 코드에서 내보내고, 소스 해시 변경·누락된 링크를 검사합니다. 문서는 Frontend 빌드에 포함되며 Vite·Vercel의 SPA 경로와 분리해 제공합니다. [갱신 방법](developers/README.md)에 11월 11일까지의 동기화 기준을 기록했습니다.

## 이번 버전 검증

아래 숫자는 `develop 366617a`에서 실행한 결과입니다. 그 뒤 추가된 테스트(E2E 시나리오 등)는 포함하지 않으며, 최신 결과는 GitHub CI 기록이 기준입니다.

- FE는 46개 파일·660개 테스트, 빌드·린트를 통과했습니다.
- BE는 1,112개 테스트 통과, PERF 전용 7개 건너뜀, 7개 경고입니다. 격리 MySQL 테스트가 포함됩니다.
- 실제 LLM·카카오 운영 로그인·사용자 테스트는 이번에 새로 실행하지 않았습니다.
- 전체 기록은 [현재 검증 기록](developers/validation.json), 점검 시나리오는 [테스트 CSV](final-guide/테스트_케이스.csv)에 있습니다.

정확한 설치 버전은 `frontend/package.json`, lockfile, `backend/requirements.txt`가 기준이고 현재 동작은 실제 import·라우터·호출 경로와 테스트가 기준입니다.
