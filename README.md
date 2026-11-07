# RE:BORN 리본

카카오테크 캠퍼스 4기 강원대 4팀 프로젝트. 폐업을 결심한 개인 카페 사장님의 상황과 실행 결과를 받아 지금 할 일 하나를 다시 안내합니다.

## 서비스 개발 문서

- **운영철학·안심 이용:** `/safety/` — 사장님의 선택, 서류 보호와 AI 검수를 설명하는 [리본 안심가이드](docs/safety/README.md)

`develop 366617a`까지 최신화하고 카카오디벨로퍼스의 문서 구성을 참고해 29개 페이지로 구현했습니다. 로그인 없이 **`/developers/`**에서 서비스 흐름·화면·기능·API·테스트를 확인합니다.

- [문서 실행·수정·11월 11일까지 갱신하는 방법](docs/developers/README.md)
- 로컬: `cd frontend && npm run dev` 후 `http://localhost:5173/developers/`
- API 24개와 로드맵 26개 작업은 코드에서 생성하고 변경 감지 검사를 빌드·CI에 연결했습니다.

## 서비스 설명과 멘토 발표 자료 (11월 7일 보관본)

2026년 11월 7일 `develop 4e64e0e` 기준으로 화면과 구현을 대조했습니다.

- [사진 포함 서비스 전체 설명서 PDF](docs/final-guide/리본_서비스_전체_설명서.pdf)
- [검색 가능한 오프라인 HTML 설명서](docs/final-guide/리본_서비스_전체_설명서.html)
- [수정 가능한 Markdown 설명서](docs/final-guide/설명서.md)
- [화면과 기능별 테스트 시나리오 92개](docs/final-guide/테스트_케이스.csv)
- [현재 기술 스택과 사용 상태](docs/tech-stack.md)

설명서에는 UI/UX 의도, 기술 구조, API 연결, 테스트, 10분 발표 대본, 예상 질문과 현재 한계를 담았습니다. 화면 사진은 11월 7일 로컬 UI에 저장소의 미리보기 데이터를 넣은 예시이며, 운영 데이터나 실제 모델 정확도 검증 결과와 구분합니다.

## 개발 문서

- [Frontend 설치와 실행](frontend/README.md)
- [사용자 시나리오와 결정 이력](docs/hero-scenario.md)
- [Agent 실행 경계](docs/agent/README.md)
- [Agent 구조](docs/agent/architecture.md)

로컬 Compose는 MySQL을 실행하며 Backend·Agent는 Python 3.12, Frontend는 Node와 Vite로 별도 실행합니다. 자세한 설정은 파트별 문서를 따릅니다. 서비스 기능과 상태 계약의 최종 기준은 실제 코드와 테스트입니다.
