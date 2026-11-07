# RE:BORN 리본

카카오테크 캠퍼스 4기 강원대 4팀의 **40~50대 개인 카페 사장님을 핵심 대상으로 설계한 폐업 준비 도우미**입니다. 내 가게 상황에 맞는 다음 행동과 필요한 서류를 정리하고, 실행 결과에 따라 같은 Case의 다음 할 일을 다시 판단합니다.

- [서비스 화면](https://ktc4-kangwon-4.vercel.app) · [대표 사용자 흐름](docs/hero-scenario.md)
- 현재 지원 범위는 비프랜차이즈 개인 카페입니다. 지원금 자격을 확정하거나 기관에 대신 신청·제출하지 않습니다.
- 상황 진단 → 지금 할 일 → 결과 제출 → 변경 내용·충돌 확인 → 다음 할 일로 이어집니다. 서류는 점검 직전에 가게 이름을 확인하고, 업로드·확인·누락 점검 뒤 제출용 ZIP을 준비합니다.
- 지원금 Agent는 현재 판단 실행 경로에서 호출하지 않습니다. [Agent 구조와 범위](docs/agent/architecture.md)를 참고하세요.

## 누구의 어떤 문제를 푸는가

핵심 대상은 **폐업을 결정하고 임대차·원상복구·직원 정산·신고·서류 준비를 직접 챙기는 40~50대 비프랜차이즈 개인 카페 사장님**입니다. 문제는 정보를 찾는 데서 끝나지 않습니다. 여러 기관과 계약에 흩어진 안내를 내 가게에 적용해 **무엇을 먼저 하고, 어떤 결과와 서류를 남겨야 하는지 연결하는 부담**입니다.

리본은 상황 진단 → 지금 먼저 확인할 일 → 실행 결과 입력 → 재판단으로 이 부담을 줄이고자 합니다. 전체 진행은 로드맵으로, 현재 집중할 행동은 별도 카드로 보여줍니다.

**40~50대를 고려한 UI/UX도 이 문제정의의 일부입니다.** Pretendard, 홈 할 일 제목 26px, 주요 버튼 글자 18~19px·높이 56~60px, 질문을 나눠 보여주는 배치와 선택형·모름·직접 입력을 적용했습니다. 읽기·선택·입력의 부담을 줄이려는 설계이며, [구현 근거와 사용자 확인 과제](frontend/docs/ui-guidelines.md#4050대-핵심-사용자와-설계-이유)를 함께 기록합니다.

40~50대는 제품 설계의 핵심 대상이며 연령에 따른 가입 제한은 아닙니다. 연령만으로 디지털 숙련도를 단정하지 않으며, 해당 연령대의 수요·사용성 검증이 완료됐다고 주장하지 않습니다.

## 서비스 개발 문서

- **개발 문서:** 로그인 없이 **`/developers/`**에서 서비스 흐름·화면·기능·API·테스트를 확인합니다. 카카오디벨로퍼스의 문서 구성을 참고한 29개 페이지입니다. [실행·수정·갱신 방법](docs/developers/README.md)
- **운영철학·안심 이용:** `/safety/` — 사장님의 선택, 서류 보호와 AI 검수를 설명하는 [리본 안심가이드](docs/safety/README.md)
- 로컬: `cd frontend && npm run dev` 후 `http://localhost:5173/developers/`
- API와 로드맵 작업 목록은 코드에서 생성하고, 코드가 바뀌었는데 문서를 갱신하지 않으면 빌드·CI가 멈춥니다.

### 서비스 설명과 멘토 발표 자료 (11월 7일 보관본)

2026년 11월 7일 `develop 4e64e0e` 기준으로 화면과 구현을 대조한 보관본입니다. 이후 변경은 위 `/developers/`와 코드가 기준입니다.

- [사진 포함 서비스 전체 설명서 PDF](docs/final-guide/리본_서비스_전체_설명서.pdf)
- [검색 가능한 오프라인 HTML 설명서](docs/final-guide/리본_서비스_전체_설명서.html)
- [수정 가능한 Markdown 설명서](docs/final-guide/설명서.md)
- [화면과 기능별 테스트 시나리오 92개](docs/final-guide/테스트_케이스.csv)

## 로컬 실행

- FE: Node.js 버전·설치·로컬 API 연결은 [Frontend README](frontend/README.md)를 따릅니다.
- BE: Python 3.12에서 `backend/requirements.txt`를 설치하고, 서류 기능은 `backend/`에서 `python scripts/setup_agent_ocr.py`를 실행해 OCR을 준비합니다. 루트의 `docker compose up -d db`는 개발용 MySQL만 실행합니다.
- 설정: AI 연결은 [루트 환경변수 예시](.env.example), 서버 인증·DB는 [backend 환경변수 예시](backend/.env.example)를 참고해 각각 `.env`와 `backend/.env`를 채웁니다. 비밀값은 커밋하지 않습니다.
- BE는 `backend/`에서 `uvicorn app.main:app --reload`로 실행합니다. **`ENVIRONMENT=dev`는 서버 시작 때 연결된 DB 테이블을 초기화하므로 개발 전용 DB를 사용합니다.**

## 검증과 배포

- [BE·Agent CI](.github/workflows/be-agent-ci.yml)는 모델 대역과 격리 MySQL로 검사합니다. [FE CI](.github/workflows/frontend-ci.yml)는 화면 검사와 빌드를, [E2E](.github/workflows/e2e.yml)는 실제 FE·BE·MySQL을 띄운 브라우저 검사를 수행합니다.
- 실제 모델 평가와 과거 수치의 조건·한계는 [모니터링 기록](docs/agent/monitoring-results.md)에 있습니다. 코드 검사 통과와 실제 모델 품질·전체 화면 속도 검증을 구분합니다.
- 배포는 [배포 절차](docs/deploy.md)와 [배포 Compose](docker-compose.prod.yml), [운영 환경변수 예시](.env.prod.example)를 사용합니다. 운영 반영과 같은 Case의 전체 시연 확인은 [#229](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/229)·[#240](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/240)에서 추적합니다.
