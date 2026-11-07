# 리본 개발 문서 구성 시안

기존 서비스에 적용할 문서 구조를 검토하기 위한 정적 HTML 시안입니다. [index.html](index.html)을 브라우저에서 열면 됩니다. 배포와 실제 서비스 라우트 연결은 하지 않았습니다.

## 검토할 네 화면

1. 문서 홈 — 시작하기, 기능별 가이드와 작성 범위
2. 결과 알려주기 이해하기 — 기능의 이유, 실제 UI 사진, 흐름, 예외와 테스트
3. 결과 알려주기 REST API — 기본 정보, 요구 사항, 요청·응답, 예제와 에러 코드
4. 카카오 로그인 — 공식 문서 링크, 리본의 인증 흐름, 설정·코드 위치와 테스트

검색, 메뉴·목차 이동, 요청 예제 전환, 예제 복사, 접이식 테스트 항목과 모바일 메뉴가 동작합니다. API 예제는 실제 서버로 전송하지 않습니다.

## 참고한 카카오 공식 문서

- [문서 홈](https://developers.kakao.com/docs/ko) — 기능별 탐색과 이해하기·REST API 등 문서 구분
- [표기 안내](https://developers.kakao.com/docs/ko/documentation-guideline/notation) — 기본 정보표, 이름·타입·설명·필수, 조건부 필수 `X*`, 자리 표시자와 코드 표기
- [카카오 로그인 이해하기](https://developers.kakao.com/docs/ko/kakaologin/common)
- [카카오 로그인 REST API](https://developers.kakao.com/docs/ko/kakaologin/rest-api)

문서의 구조와 표기 방식을 참고한 리본 프로젝트 시안입니다. 카카오의 로고·공식 서비스 명칭으로 리본을 표시하지 않으며, 카카오 내부의 문서 운영 방식까지 확인한 것은 아닙니다.

## 실제 구현과 구분할 점

- 리본 API는 `Access-Token` 헤더로 자체 JWT를 받습니다. 카카오 토큰과 구분합니다.
- 결과 접수는 현재 HTTP 200과 `case_history_id`를 반환합니다. 반영 완료는 별도 상태 조회로 확인합니다.
- `raw_input`과 `restoration_answer`는 하나만 보냅니다.
- 예제 번호·응답은 설명용입니다. 사진은 저장소의 UI 미리보기 데이터입니다.
- 표의 필드와 조건은 `backend/app/be/schemas/case.py`, `routers/case.py`, `services/case.py`와 `frontend/src/lib/resultSubmit.ts`를 확인했습니다.

## 이 방향으로 확장할 때

상황 진단, 홈·다음 할 일, 충돌 확인, 로드맵, 서류함·점검, 기록을 같은 기능별 문서 구조로 옮깁니다. 기존 전체 설명서는 서비스 가이드로 연결하고, 개발 문서는 계약·예제·에러·검증을 중심으로 나눕니다. 실제 서비스에 문서 진입점을 두거나 별도 문서 사이트로 배포하는 단계는 시안 검토 후 진행할 수 있습니다.
