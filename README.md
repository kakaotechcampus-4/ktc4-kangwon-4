# RE:BORN

카카오테크 캠퍼스 4기 강원대 4팀의 폐업 준비 도우미입니다. 가게 상황을 확인하고, 지금 할 일 하나를 안내한 뒤 실행 결과에 따라 같은 Case의 다음 할 일을 다시 판단합니다.

- [서비스 화면](https://ktc4-kangwon-4.vercel.app) · [대표 사용자 흐름](docs/hero-scenario.md)
- 현재 지원 범위는 비프랜차이즈 개인 카페입니다. 지원금 자격을 확정하거나 기관에 대신 신청·제출하지 않습니다.
- 상황 진단 → 지금 할 일 → 결과 제출 → 변경 내용·충돌 확인 → 다음 할 일로 이어집니다. 서류는 업로드·확인·누락 점검 뒤 제출용 ZIP을 준비합니다.
- 지원금 Agent는 현재 판단 실행 경로에서 호출하지 않습니다. [Agent 구조와 범위](docs/agent/architecture.md)를 참고하세요.

## 로컬 실행

- FE: Node.js 버전·설치·로컬 API 연결은 [Frontend README](frontend/README.md)를 따릅니다.
- BE: Python 3.12에서 `backend/requirements.txt`를 설치하고, 서류 기능은 `backend/app/agent/document_tool/requirements.txt`도 설치한 뒤 `backend/`에서 `python scripts/setup_agent_ocr.py`를 실행합니다. 루트의 `docker compose up -d db`는 개발용 MySQL만 실행합니다.
- 설정: AI 연결은 [루트 환경변수 예시](.env.example), 서버 인증·DB는 [backend 환경변수 예시](backend/.env.example)를 참고해 각각 `.env`와 `backend/.env`를 채웁니다. 비밀값은 커밋하지 않습니다.
- BE는 `backend/`에서 `uvicorn app.main:app --reload`로 실행합니다. **`ENVIRONMENT=dev`는 서버 시작 때 연결된 DB 테이블을 초기화하므로 개발 전용 DB를 사용합니다.**

## 검증과 배포

- [BE·Agent CI](.github/workflows/be-agent-ci.yml)는 모델 대역과 격리 MySQL로 검사합니다. [FE CI](.github/workflows/frontend-ci.yml)는 화면 검사와 빌드를 수행합니다.
- 실제 모델 평가와 과거 수치의 조건·한계는 [모니터링 기록](docs/agent/monitoring-results.md)에 있습니다. 코드 검사 통과와 실제 모델 품질·전체 화면 속도 검증을 구분합니다.
- [배포 Compose](docker-compose.prod.yml)와 [운영 환경변수 예시](.env.prod.example)를 사용합니다. [배포 절차 PR #225](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/225)는 검토 중이며, 운영 반영과 같은 Case의 전체 시연 확인은 [#229](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/229)·[#240](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/issues/240)에서 추적합니다.
