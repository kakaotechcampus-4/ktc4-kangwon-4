# 리본 개발 문서

카카오디벨로퍼스의 공개 문서 구성과 표기를 참고한 서비스 공식 설명서입니다. 서비스의 `/docs`는 사용자 서류함이므로 공개 문서는 **`/developers/`**로 제공합니다. 로그인 없이 읽을 수 있습니다.

이용자용 [리본 안심가이드](../safety/README.md)는 `/safety/`에서 운영철학·안심 이용·운영 기준·AI와 검수·정보 보호·사례와 질문을 7개 화면으로 안내합니다. 개발 문서와 함께 검사·생성되며 로그인 화면과 두 사이트의 메뉴로 서로 연결됩니다.

2026년 11월 7일 `develop b0fa738`까지 반영했습니다. 29개 페이지에 서비스와 화면 설명, 기능이 필요한 이유, 처리 흐름, API 24개, 로드맵 작업 26개, 정상·예외·복구 테스트와 현재 한계를 담았습니다. 캡처는 11월 7일 UI에 미리보기 데이터를 넣어 촬영한 화면입니다.

## 열기

```sh
cd frontend
npm ci
npm run dev
```

`http://localhost:5173/developers/`에 접속합니다. 로그인 화면의 **서비스 안내와 개발 문서** 링크로도 이동합니다. `npm run build`는 문서를 검사·생성해 `dist/developers/`에 포함합니다. Vite 개발·preview와 Vercel에서 문서 URL을 별도로 처리합니다.

## 11월 11일까지 갱신하기

사용자 요청에 따라 **2026년 11월 11일까지 서비스 변경 시 관련 문서를 함께 갱신**합니다. 이후 작업을 위한 지침은 [AGENTS.md](../../AGENTS.md)에도 남겼습니다. 예약 작업은 설정하지 않았습니다.

1. 최신 develop과 로컬 변경을 보존해 반영합니다.
2. 바뀐 코드·화면·API·테스트를 읽고 `content.mjs`의 설명·예제·변경 이력을 수정합니다.
3. 화면이 달라졌으면 미리보기 데이터로 캡처를 다시 찍고 `screenshots.json`의 파일·제목·기준일·소스 버전을 수정합니다. 실제 운영 데이터와 자격증명은 포함하지 않습니다. 과거 PDF의 이미지는 보존하고 새 캡처는 `images/`에 넣습니다.
4. 아래 명령으로 계약과 소스 해시를 다시 내보내고 문서를 검증합니다.
5. 영향받은 테스트와 브라우저 검증 결과를 `validation.json`에 기록합니다.

```sh
# 프로젝트 Backend 의존성이 설치된 Python 3.12 환경
cd backend
python scripts/export_documentation.py
python scripts/export_documentation.py --check

cd ../frontend
npm run docs:check
npm run docs:build
npm run build
npm run preview
# http://localhost:4173/developers/
```

내보내기는 앱의 lifespan을 실행하지 않으며 DB 초기화·모델 호출을 하지 않습니다. CI에는 Backend 계약 대조와 Frontend 소스 불일치 검사를 연결했습니다. 기능 소스 변경을 감지하면 관련 설명을 검토한 뒤 계약 파일을 다시 내보내야 통과합니다. 검사는 설명의 의미까지 자동으로 갱신하지 않습니다.

## 원본과 생성물

| 파일 | 역할 |
| --- | --- |
| `content.mjs` | 사람이 검토하는 기능·UX·기술 설명과 API별 주의점 |
| `generated/contracts.json` | OpenAPI, 검증된 요청 예제, 작업 정의, 확인일·소스 해시 |
| `docs.css` · `docs.js` | 반응형 화면, 목차, 검색, 최근 문서, 예제 복사 |
| `screenshots.json` · `images/` | 화면 캡처 파일, 제목과 촬영 기준 |
| `validation.json` | 실제로 수행한 검증의 기준과 결과 |
| `../../scripts/build-docs.mjs` | 문서 생성과 계약·연결·앵커·캡처 검사 |
| `../../frontend/public/developers/` | 빌드 생성물, Git 제외, 직접 수정하지 않음 |

검색은 공개 문서 인덱스만 읽고 API 실행 기능은 제공하지 않습니다. 최근 문서는 브라우저 localStorage에 문서 제목·주소만 최대 5개 저장하며 지울 수 있습니다. 실제 LLM·카카오 운영 로그인은 이번 문서 검증 범위에 포함하지 않았습니다.

참고: [카카오 문서 홈](https://developers.kakao.com/docs/ko), [문서 표기](https://developers.kakao.com/docs/ko/documentation-guideline/notation), [카카오 로그인 REST API](https://developers.kakao.com/docs/ko/kakaologin/rest-api). 카카오의 로고와 서비스 명칭 대신 RE:BORN 프로젝트의 브랜드를 표시합니다. 이전 PDF는 [11월 7일 설명서](../final-guide/설명서.md)로 보존합니다.
