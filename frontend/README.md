# RE:BORN Frontend

폐업을 결심한 소상공인의 폐업 과정을 하나의 Closure Case로 관리하는 Agent, RE:BORN의 프론트엔드.

## 시작하기

**Node.js `^20.19.0` 또는 `>=22.12.0`** 이 필요합니다 (Vite 8 요구사항).

```bash
node -v          # 위 버전 확인
cd frontend
npm ci           # lockfile 그대로 설치. 처음이거나 CI라면 이쪽
npm run dev
```

패키지를 추가·변경할 때만 `npm install`을 씁니다.

http://localhost:5173

### 서버 주소는 따로 설정하지 않아도 됩니다

화면은 서버를 `/api/...` 로 부르고, 개발 서버와 배포 환경이 각각 그 요청을 서버로 넘깁니다
(`vite.config.ts` · `vercel.json`). **로컬도 배포와 같은 길로 나가므로 "로컬에서는 되는데
배포에서만 안 되는" 차이가 생기지 않습니다.**

**로컬 BE 에 붙일 때만** `frontend/.env.local` 을 만듭니다.

```bash
cp .env.example .env.local
# VITE_API_BASE_URL=http://localhost:8000
```

**`frontend/` 안에 만들어야 합니다.** 레포 루트의 `.env*` 는 BE 와 docker compose 것이라
Vite 가 읽지 않습니다. 고친 뒤에는 개발 서버를 다시 띄웁니다 — 환경변수는 시작할 때 한 번 읽습니다.

### 로컬에서는 카카오 로그인이 끝까지 되지 않습니다

카카오는 **돌아올 주소가 정확히 일치할 때만** 로그인을 돌려보내고, BE는 그 주소를
환경변수 하나로 들고 있어 **한 번에 하나만** 씁니다. 그래서 배포 BE에 붙이면 카카오가
배포된 화면으로 돌아가고 로컬 화면으로는 오지 않습니다.

- **끝까지 보려면** BE도 로컬로 띄우고 BE의 `KAKAO_REDIRECT_URI`를
  `http://localhost:5173/login/callback`으로 둡니다
- **그게 어려우면** 로그인 화면의 "가짜로 로그인" 버튼을 씁니다. 개발·Preview에만 나옵니다

## 스택

| 기술 | 비고 |
|---|---|
| React 19 + TypeScript | UI · 컴포넌트 |
| Vite | 빌드 도구 |
| Tailwind CSS 4 | `tailwind.config.js`와 PostCSS 설정이 **없습니다**. `@tailwindcss/vite` 플러그인과 `src/index.css`의 `@import "tailwindcss";` 로 동작합니다 |
| React Router | 라우팅. v7부터 `react-router-dom`이 아니라 `react-router` 한 패키지입니다 |
| Fetch API | 통신 |
| React 내장 | 상태관리 (`useState` / `useContext`) |
| Motion (`motion`, 14.4.0 고정) | 시트 끌기·용수철, 버튼 누르기, 로드맵 펼치기. 화면 이동은 브라우저 View Transitions, 나머지 움직임은 CSS ([UI 가이드라인 "움직임"](docs/ui-guidelines.md)) |
| Zustand | 화면 여러 장에 걸쳐 이어지는 답만 (`src/stores/`). 지금은 상황 진단 답 하나. 서버 데이터는 넣지 않습니다 |
| Pretendard | 본문 글꼴. npm 패키지로 직접 배포 (`src/main.tsx`) |
| 다음 우편번호 서비스 | 통합 폐업 신고의 가게 주소 찾기. 패키지가 아니라 공식 스크립트를 주소 찾기를 열 때만 받습니다 (`src/lib/postcode.ts`) |

Mobile-first 반응형, 기준 폭 375px.

서버 통신은 `src/lib/api.ts` 한곳을 거칩니다. 주소와 `Access-Token` 헤더를 여기서 붙이고,
인증이 통하지 않으면 로그인 화면으로 돌려보냅니다. 파일 올리기(`FormData`)와 요청별 제한 시간(`timeoutMs`)도
여기서 받습니다.

색·글자 크기·모서리·그림자는 `src/styles/tokens.css`의 토큰으로 씁니다. 규칙은 `docs/ui-guidelines.md`에 있습니다.

상황 진단의 이모지는 Microsoft Fluent Emoji(MIT)입니다. 라이선스는 `src/assets/emoji/LICENSE`에 있습니다.

## 화면

| 경로 | 화면 | 내용 |
|---|---|---|
| `/login` | 로그인 | 소개 4장 + 카카오로 시작하기. 인증 가드 밖 |
| `/login/callback` | 로그인 처리 | 카카오가 돌려보내는 자리. 역시 가드 밖 |
| `/` | 진입 분기 | 보낼 곳만 정하고 화면은 없다 |
| `/cases/new` | 상황 진단 | Case가 없는 사용자만 본다. 질문 한 장씩(`?step=`), 답에 따라 질문이 생기고 빠진다. 마지막에 가입 요청을 보내고 저장하는 동안 "만드는 중" |
| `/case` | 현재 Case (홈) | 하단 탭. 지금 할 일 하나, 또는 리본이 일하는 중인지. 서버가 다시 해볼 수 있다고 한 판단 실패면 [다시 판단하기](`POST /cases/retry`, #196). 기록과 어긋나 확인이 필요하면 [확인하러 가기] → 결과 입력이 충돌 확인으로 넘긴다. 폐업 정리를 마쳤으면(`case_status` `COMPLETED`, #167) 할 일 대신 완료 카드와 [전체 기록 보기] |
| `/task` | 할 일 상세 | 할 일과 "이렇게 물어보세요" 목록. 폐업 정리를 마친 가게는 홈으로 보낸다 |
| `/results` | 결과 입력 | 할 일의 결과를 글로 전달. 서버가 원상복구 답을 골라서 받겠다고 하면(`result_input_kind`, #197) 범위·철거 보기를 고르고, [직접 쓸게요]로 글로도 쓸 수 있다. 리본이 되물었으면 그 질문에 답하고, 더 알려주셔야 하는 실패면 다시 적는다. 보내는 글은 2,000자까지(질문에 답할 때는 질문까지 묶은 전체, 넘으면 자르지 않고 보내기를 막음). 보낸 뒤 판단이 끝날 때까지 처리 화면 |
| `/confirm` | 충돌 확인 | 기존 기록과 어긋날 때만 들른다. 고른 쪽을 보내고(`POST /cases/results/decision`, #136) 결과 입력과 같은 처리 중 화면으로 판단을 기다린다 |
| `/replan` | 반영 결과 | 무엇이 바뀌었고, 로드맵에 새로 생긴 할 일(#182)과 다음 할 일은 무엇인가. 주소의 판단 번호(`?history=`)로 다시 묻는다 |
| `/docs` | 서류함 | 하단 탭. 올린 서류 목록 · 올리기 시트 · 확인 필요 서류 고치기 · 빼기(서류 API #159). 올리기는 서버가 다 읽을 때까지 기다려 최대 110초(배포의 Vercel 120초 제한보다 먼저 끊음) |
| `/docs/check` | 서류 점검 | 정산 서류 점검. 점검 직전 신청인 이름 · 실제 폐업일을 묻는다 |
| `/docs/done` | 정산 제출 파일 | 점검을 통과했을 때만. [파일 받기]로 ZIP 을 받는다(Mock 에서는 꺼짐) |
| `/log` | 작업 기록 | 하단 탭. 사장님 · 리본이 한 일을 최근 것부터(`GET /cases/logs`). 홈 띠도 여기서 리본 줄만 쓴다 |
| `/roadmap` | 폐업 전체 순서 | 다섯 단계와 할 일 상태(`GET /cases/roadmap`, #178). 지금 단계(#179)만 펼친다. 홈 단계 카드로 들어온다 |
| `/roadmap/:taskId` | 할 일 | 로드맵에서 그 할 일을 찾아 체크 · 첨부 · 철거비 심사 결과 · 통합 폐업 신고(폐업일 · 사유 · 주소) · 보증금 · 결과 알려주기 중 하나를 연다. 저장은 실서버 API(#149 · #168). 통합 폐업 신고 · 보증금은 저장해 둔 값(`GET /cases`)으로 채워 연다. 서버가 "확인 필요"로 준 체크 항목은 [다 했어요]를 꺼 둔다(#181) |
| `/notifications` | 알림 | 탭 화면의 종 버튼으로 들어온다. 아직 빈 상태 |

로그인 화면 둘을 뺀 전부가 인증 가드 아래에 있습니다. 로그인하지 않고 열면 `/login`으로 갑니다.

`/`는 화면이 아니라 분기입니다. 로그인 여부와 Case 유무를 보고 `/login`·`/cases/new`·`/case` 중
하나로 보냅니다. 판단을 한곳에 모아두면 새 화면이 늘어도 규칙이 갈라지지 않습니다.

`/confirm`은 이전 화면에서 라우터 state로 충돌 목록을 받습니다. 주소로 직접 열면
개발·Preview에서는 Mock으로, 그 외에는 `/`로 이동합니다. 보낸 뒤 반영되면 `/replan?history=<번호>&from=confirm`(반영 결과가 "이해했어요" 대신 고른 것을 반영했다고 말함), 되물으면 `/results`, 다시 해볼 수 있는 실패면 고른 채로 머물고, 그 밖의 실패는 `/case` 로 갑니다. 결정이 실패해도 서버는 충돌을 그대로 남겨 다시 고를 수 있습니다.

`/replan`은 결과를 넘겨받지 않고 주소의 판단 번호로 `GET /cases/results/status` 를 다시 부릅니다.
그 뒤로 새 판단이 생겼으면(409) 지난 결과 대신 그렇다고 알리고, 번호가 이상하거나 반영된 결과가
아니면 `/case` 로 보냅니다. Mock 으로 볼 때만 넘겨받은 결과로 그립니다.

`/cases/new`의 `?step=`은 주소로 직접 고쳐 열 수 있어서, 앞 질문에 답하지 않았으면 답하지 않은
첫 질문으로 바꿔 끼웁니다. 고른 답은 `sessionStorage`(Zustand)에 두어 질문을 넘기거나 새로고침해도
남고, 가입 요청이 받아들여지면 비웁니다. 로그인이 만료되거나 저장에 실패하면 남겨 두어 이어서 보냅니다.

**Case 가 있는지는 서버에 물어봅니다.** `/` · `/cases/new` · `/case` · `/task` 가 들어올 때마다
`GET /cases` 를, `/results` 는 `GET /cases/results` 를, `/replan` 은 `GET /cases/results/status` 를, `/log` 와 홈 띠는
`GET /cases/logs` 를, `/roadmap` · `/roadmap/:taskId` 와 홈 단계 카드는 `GET /cases/roadmap` 을, `/docs` · `/docs/check` · `/docs/done` 은 `GET /cases/documents` 를 부릅니다. 앞 화면에서 받은 값을 넘겨받지 않는 것은, 그 값이 히스토리에 남아
오래된 Case 가 "지금 상황"인 척 다시 뜨기 때문입니다.

로그인 토큰은 `sessionStorage`에 둡니다. 탭을 닫으면 풀립니다 — 가게나 공용 PC에서 쓰는
사용자가 있어 브라우저를 껐다 켜도 남는 쪽은 피했습니다.

## 화면 설계 근거

화면마다 **어떻게 동작하는지**와 **왜 그렇게 만들었는지**를 적었습니다. 번호는 Figma 화면 지도와 같습니다
([리본 프로토타입 UI · 코드 근거](https://www.figma.com/design/RTIdc8DreOtrAT33xTQAy3/%EB%A6%AC%EB%B3%B8-%ED%94%84%EB%A1%9C%ED%86%A0%ED%83%80%EC%9E%85-UI?node-id=406-3), 118장).

- "왜"는 코드 주석에 남긴 이유입니다. 주석이 없어 코드를 보고 짐작한 것은 "(추론)"이라고 표시했습니다
- 사용자 테스트로 효과를 확인한 것은 아닙니다. 만든 사람이 의도한 이유입니다
- 코드 위치는 `src/` 기준이고, 그 자리에 이유를 적은 주석이 있습니다

| 번호 | 화면 | 이렇게 동작한다 | 왜 | 코드 |
|---|---|---|---|---|
| A-01 | 로그인 · 서비스 소개 | 소개 4장 아래 카카오 로그인. 성공하면 진입 분기로, 실패하면 다시 로그인 | 진단 답을 저장하려면 로그인이 먼저 필요하다. 로그인 방법을 하나로 두어 고르다 헷갈리지 않게 한다 | `pages/LoginPage.tsx:10` |
| A-02 | 진단 · 업종과 가게 상황 | 업종을 골라야 [다음]이 켜진다. 다른 음식점일 때만 프랜차이즈인지 묻고, 가게 상황은 여러 개 고른다 | 앞 답으로 답할 필요가 없어진 질문은 뺀다. 여러 개 고르는 질문에서 "해당 없음"도 답으로 친다 | `lib/diagnosisSteps.ts:27` |
| A-03 | 진단 · 임차와 원상복구 | 가게를 빌려 쓴다고 고른 경우에만 월세와 원상복구 조항을 묻는다. 조항은 "모름"도 고를 수 있다 | 빌린 가게가 아니면 월세처럼 답할 수 없는 질문은 거른다. (추론) 조항에 "모름"을 둔 것은 확실하지 않은 답을 억지로 고르게 하지 않으려는 것이다 | `lib/diagnosisSteps.ts:34` |
| A-04 | 진단 · 직원과 사업장 보험 | 직원이 있으면 인원을 받고, 없으면 예전 직원이 있었는지 묻는다. 보험은 여러 개·없음·모름 | 지금 직원과 예전 직원 질문이 서로 어긋나지 않게 나눈다. "가게 이름으로"를 강조해 개인 보험과 헷갈리지 않게 한다 | `pages/CaseCreatePage.tsx:224` |
| A-05 | 진단 · 폐업 시기와 가입 | 시기를 고르면 가입 요청. 저장하는 동안 별도 화면. 고른 답은 새로고침해도 남는다 | 가입 때는 예상 시기만 받는다. 실제로 하지 않은 일을 시간이 됐다고 완료로 표시하지 않는다 | `pages/CaseCreatePage.tsx:287` |
| B-01 | 홈 · 지금 할 일 | 홈은 지금 할 일 하나를 크게 보여준다. 상세에서는 "이렇게 물어보세요"를 번호로 보여준다 | 사장님이 막히는 곳은 "연락해야지"가 아니라 "뭐라고 말하지"다. 그래서 할 일과 할 말을 나눠 보여준다 | `pages/TaskPage.tsx:11` |
| B-02 | 홈 · 활동 띠와 단계 카드 | 리본이 한 일을 3.5초마다 넘긴다. 한 줄뿐이거나 "동작 줄이기" 설정이면 넘기지 않는다 | 읽던 글이 넘어가 사라지는 일을 줄인다. 지금 몇 단계인지는 화면이 짐작하지 않고 서버 값을 따른다 | `components/ui/HomeBanner.tsx:15` |
| B-03 | 홈 · 판단 기다리기 | 판단 중이면 3초마다 다시 묻고, 10분이 넘으면 멈춘다. [상태 다시 확인]을 둔다 | 서버가 다시 켜지는 등으로 끝나지 않는 판단에서 끝없이 기다리고 끝없이 묻는 것을 막는다 | `hooks/useCase.ts:73` |
| B-04 | 홈 · 추가 질문과 기록 충돌 | 리본이 되물으면 [답하러 가기], 기록과 어긋나면 기록 확인으로 보낸다 | 기다리기·더 답하기·기록 고르기는 사장님에게 서로 다른 일이다. 상태마다 맞는 다음 행동을 준다 | `pages/CurrentCasePage.tsx:21` |
| B-05 | 홈 · 실패했을 때 | 실패 이유에 따라 "더 알려 주세요"·"다시 해볼 수 있음"·"저희 쪽 문제"·"할 수 있는 것 없음"·"이유 모름"으로 나눈다 | 실패는 이유마다 할 말이 달라 한 문구로 뭉치지 않는다. 사장님이 할 수 있는 일에 맞춰 안내와 버튼을 다르게 둔다 | `pages/CurrentCasePage.tsx:436` |
| B-06 | 홈 · 완료와 알림 | 폐업 정리를 마쳤는지를 마지막 판단보다 먼저 본다. 알림은 빈 화면만 있다 | 마친 가게에 [결과 알려주기]를 다시 띄우지 않는다. 아직 없는 알림을 진짜처럼 꾸미지 않는다 | `pages/CurrentCasePage.tsx:74` |
| C-01 | 결과 입력 · 기본 흐름 | 들어올 때 서버에 지금 판단을 먼저 묻는다. 빈 글은 못 보낸다. 반영되면 반영 결과 화면으로 간다 | 지난 할 일에 결과를 보내지 않도록 매번 새로 묻는다. "다르게 이해했어요"로 고치는 것도 되돌리기가 아니라 새 결과 입력이다 | `pages/ResultInputPage.tsx:66` |
| C-02 | 결과 입력 · 글자 수 | 1,800자를 넘으면 남은 글자를 보여주고, 2,000자를 넘으면 보내기를 막는다 | 몰래 잘라 보내면 사장님이 쓴 뒷부분이 사라진다. 평소 짧은 답에는 숫자를 띄우지 않는다 | `lib/resultSubmit.ts:23` |
| C-03 | 결과 입력 · 되물은 질문에 답하기 | 질문 일부에만 답해도 보낼 수 있다. 답한 질문과 답만 묶어 보낸다 | 모르는 것까지 채우게 하면 지어낸 답이 들어간다. AI가 무엇을 물었는지 알도록 질문을 같이 보낸다 | `pages/ResultInputPage.tsx:188` |
| C-04 | 충돌 확인 | 기존 기록과 새로 알려 주신 내용을 나란히 둔다. 미리 골라 두지 않고, 모든 항목을 골라야 넘어간다 | 반영한 뒤 되돌리는 기능이 없어 여기서 확인해야 한다. 읽지 않고 기본값으로 넘기는 일을 막는다 | `pages/ConfirmChangePage.tsx:17` |
| C-05 | 결과 입력 · 실패와 오래 기다림 | 다시 보낼 수 있는 실패만 입력을 열어 둔다. 저희 쪽 문제·할 수 있는 것 없음·상황 바뀜·오래 걸림·응답 못 읽음은 잠근다 | 보내지 못한 것과 접수된 뒤 기다리는 것을 구분한다. 두 번 보내거나 안내와 다른 행동을 하게 두지 않는다 | `pages/ResultInputPage.tsx:212` |
| D-01 | 로드맵 · 전체 순서 | 서버가 정한 지금 단계만 처음에 펼친다. 다른 단계도 열고 닫을 수 있다 | 앞으로 할 일도 미리 볼 수 있게 시안의 고정 펼침을 바꿨다. "해당 없음"은 완료 개수에서 뺀다 | `pages/RoadmapPage.tsx:22` |
| D-02 | 할 일 · 종류별 화면 | 안내만·체크·서류 첨부·결과 알려주기로 나눈다. "확인 필요"인 체크는 [다 했어요]를 끈다. [완료 취소하기]는 막지 않는다 | 서버가 거절할 완료 요청을 미리 막는다. 공식 절차가 끝났는지는 서버 판단을 따른다 | `pages/TaskFlowPage.tsx:129` |
| D-03 | 할 일 · 철거비 심사 결과 | 처음에는 아무것도 골라 두지 않는다. 골라서 저장에 성공하면 "기록했어요"로 바꾼다 | 서버가 지금 고른 값을 주지 않아 짐작해서 골라 두지 않는다. 다음에 할 일은 화면이 정하지 않는다 | `pages/TaskFlowPage.tsx:203` |
| D-04 | 할 일 · 통합 폐업 신고 | 폐업일·사유·도로명 주소는 꼭, 상세 주소는 선택. 주소 찾기는 아래에서 올라오는 시트. 저장 뒤 접수증 올리기와 결과 알려주기를 안내 | 서버가 한 번에 저장해서 한 화면에 모았다. 팝업·새 탭으로 가면 흐름을 잃어서 시트로 찾는다. 저장은 신고 완료가 아니다 | `pages/TaskFlowPage.tsx:419` |
| D-05 | 할 일 · 보증금 정산 기록 | 결과를 먼저 저장하고 성공하면 완료 체크. 체크만 실패하면 체크만 다시 한다 | 완료 표시는 있는데 정산 결과는 비어 있는 상태를 막는다. 저장한 값은 다시 들어오면 보여준다 | `pages/TaskFlowPage.tsx:296` |
| E-01 | 서류함 · 올리기와 빼기 | 한 장씩 올린다. 20MB가 넘으면 고르는 순간 막는다. 빼기는 확인 시트를 거친다 | 오래 올린 뒤에 크기로 거절당하는 일을 줄인다. 뺀 서류는 되돌릴 수 없어 먼저 묻는다. 종류 나누기·필요한 서류 판단은 서버가 한다 | `pages/DocsPage.tsx:24` |
| E-02 | 서류함 · 읽은 종류와 값 확인 | 종류를 고르고 보이는 값 칸이 다 채워져야 [확인]이 켜진다. 서버가 읽은 칸만 보여주고 보낸다 | 빈 값을 확인된 사실로 저장하지 않는다. 서류마다 필요한 칸을 화면이 마음대로 늘리지 않는다 | `pages/DocsPage.tsx:217` |
| E-03 | 서류 점검 · 신청인과 결과 | 신청인 이름은 꼭(50자까지), 실제 폐업일은 선택. 점검 결과와 문제 문구는 서버가 준 그대로 보여준다 | 가입 정보에 신청인 이름과 실제 폐업일이 없어 점검 직전에 받는다. 예상 폐업 시기와 실제 날짜를 구분한다 | `pages/DocsCheckPage.tsx:212` |
| E-04 | 정산 · 제출 파일 받기 | 점검을 통과했을 때만 이 화면을 연다. ZIP을 받은 뒤 신청은 사장님이 직접 한다 | 버튼을 누른 뒤에야 실패를 알게 하지 않는다. 서류 수와 다음 할 일은 화면이 정하지 않는다 | `pages/DocsDonePage.tsx:13` |
| E-05 | 작업 기록 | 최근 것부터 보여준다. 리본·사장님을 그림과 글자로 같이 표시한다. 빈 목록과 불러오기 실패를 따로 보여준다 | 그림을 못 보는 사람도 누가 한 일인지 알게 글자로도 적는다. (추론) 불러오지 못한 것을 기록이 없는 것으로 오해하지 않게 한다 | `pages/LogPage.tsx:13` |

결과 입력에서 서버가 `RESTORATION_ANSWER`를 지정하면 원상복구 범위·철거 여부의 보기를 보여 주고 [직접 쓸게요]로 글 입력도 선택할 수 있습니다. 보기의 답은 임대인에게 들은 말투로 씁니다. 화면이 묻는 “임대인이 뭐라고 했나요?”에 사장님이 스스로 결정한 것처럼 답하지 않게 하려는 의도입니다(`pages/ResultInputPage.tsx:29`, #210·#213 리뷰).

**근거가 없어서 지어내지 않은 곳**

- 할 일 근거 상자 (`pages/TaskPage.tsx:20`): 시안에는 "계약서에서 찾아뒀어요" 같은 상자가 있지만, 서버가 근거를 주지 않아 할 일의 이유를 대신 보여준다
- 알림 (`pages/NotificationsPage.tsx:9`): 알림 API가 없어 빈 화면만 있다
- 결과 입력 예시 문구 (`pages/ResultInputPage.tsx:513`): 철거 상황을 가정한 시안 예시라, 다른 할 일 뒤에도 같은 문구가 뜬다

## npm script

| 명령 | 설명 |
|---|---|
| `npm run dev` | 개발 서버 (5173) |
| `npm run build` | 프로덕션 빌드 (`tsc -b && vite build`) |
| `npm run lint` | ESLint |
| `npm run test` | 단위·화면 테스트 (Vitest) |
| `npm run test:e2e` | 브라우저 E2E (Playwright). 실제 BE · MySQL이 떠 있어야 해서 보통 CI에서 돈다 |
| `npm run preview` | 빌드 결과 미리보기 |

## CI

`frontend/` 변경이 포함된 PR을 올리면 GitHub Actions가 아래를 자동으로 실행합니다(`check`).

```
npm ci  →  npm run lint  →  npm run test  →  npm run build
```

- `develop`, `main`으로 가는 PR 모두 동일하게 실행됩니다
- 앞 단계가 실패하면 이후 단계는 실행되지 않습니다. PR의 Checks에서 로그를 확인합니다
- 고친 뒤 같은 브랜치에 push하면 기존 PR에서 자동으로 다시 실행됩니다

브라우저 E2E(`browser`)는 따로 돕니다. PR과 `develop` push에서 실제 FE 빌드 · BE · MySQL ·
Chromium을 띄워 `npm run test:e2e`를 실행합니다. 모델 응답만 가짜로 대신합니다.

CI는 검증만 하고 배포하지 않습니다. 설정 파일은 레포 루트의 `.github/workflows/frontend-ci.yml`,
`.github/workflows/e2e.yml` 입니다.

## 배포

Preview는 push하면 Vercel이 자동으로 만듭니다. **운영(Production)은 자동으로 바뀌지 않습니다.**
운영 BE(EC2) 반영을 확인한 뒤, 같은 커밋으로 만들어진 배포를 Vercel에서 Production으로 승격합니다.
FE가 BE보다 먼저 올라가면 아직 없는 API를 부르게 되어서입니다(BE 배포 순서는 `docs/deploy.md`).

| Vercel 환경 | 어떤 코드 | 언제 바뀌나 |
|---|---|---|
| Production | 승격한 배포 하나 | 사람이 Vercel에서 승격할 때만 |
| Preview | `develop` · PR 브랜치 | push할 때마다 자동 |

주소는 아래 "환경 · URL" 표에 있습니다.

서버 주소는 Vercel에 환경변수로 두지 않습니다. 화면은 늘 같은 주소의 `/api`만 부르고,
`vercel.json`의 규칙이 서버(`https://reborn-ktc.duckdns.org`)로 넘깁니다. 개발 서버도
`vite.config.ts`에 같은 규칙을 둡니다. 그래서 서버 주소는 이 두 곳에만 있고, 로컬과 배포가 같은
길로 요청해 "로컬에서는 되는데 배포에서만 안 되는" 차이가 생기지 않습니다.
(처음에는 서버가 HTTP라 브라우저가 막아서 둔 규칙이었는데, 서버가 HTTPS가 된 뒤에도 위 이유로 둡니다.)

Preview 배포에서는 URL 쿼리로 예외 화면을 확인할 수 있고, 로그인 화면에 **"가짜로 로그인"**
버튼이 하나 더 나옵니다. `VITE_ENABLE_MOCK_SWITCH`를 Preview 환경에만 설정하기 때문이며,
Production에서는 둘 다 나오지 않습니다.

가짜 로그인이 필요한 이유는 카카오가 돌아올 주소를 정확히 일치하는 것만 허용하기 때문입니다.
PR 브랜치마다 Preview 주소가 달라 등록할 수 없어서, **리뷰어는 가짜 로그인으로 화면을 보고
진짜 카카오 로그인은 `develop` 머지 후 확인합니다.**

```
/?mock=logged-out           로그인 안 된 상태
/?mock=no-case              Case가 없는 사용자 (상황 진단으로). 진단 화면을 직접 볼 때는 /cases/new?mock=no-case
/cases/new?mock=creating    상황 진단을 보낸 뒤 저장하는 동안 ("만드는 중")
/?mock=pending              판단 중 (Case를 막 만든 직후)
/?mock=pending-long         판단 중인데 오래 걸려 자동 조회를 멈춘 상태
/?mock=more-info            다음 할 일을 정하려면 더 물어봐야 하는 상태
/?mock=judgment-failed          판단 실패 — 서버가 다시 해볼 수 있다고 본 경우 ([다시 판단하기]를 누르면 판단 중으로)
/?mock=judgment-failed-detail   판단 실패 — 다시 알아야 할 항목을 짚어준 경우
/?mock=judgment-failed-service  판단 실패 — 서비스가 들여다봐야 하는 경우
/?mock=judgment-failed-none     판단 실패 — 지금 이어서 할 수 있는 것이 없는 경우
/?mock=judgment-conflict    말한 내용이 기록과 달라 확인이 필요한 상태
/?mock=unrecognized         서버가 모르는 판단 상태를 보냈을 때
/?mock=completed            폐업 정리를 모두 마친 상태 (부가세 신고를 체크한 뒤)
/results?mock=conflict      제출하면 충돌 확인으로
/results?mock=result-choice  원상복구 답을 골라서 보내기 (보내면 반영 결과로)
/results?mock=more-info     리본이 되물은 질문에 답하기 (보내면 또 되묻는다)
/results?mock=failed-retry     판단 실패 — 같은 내용으로 다시 보낼 수 있는 경우
/results?mock=failed-detail    판단 실패 — 더 적어서 보내야 할 항목을 짚어준 경우
/results?mock=failed-service   판단 실패 — 서비스가 들여다봐야 하는 경우
/results?mock=failed-none      판단 실패 — 이번 판단에 할 수 있는 것이 없는 경우
/results?mock=failed-unknown   판단 실패 — 이유를 알 수 없는 경우
/results?mock=send-failed      결과를 보내지 못함
/results?mock=send-rejected    서버가 글을 받지 않음 (422, 고쳐서 다시 보내기)
/results?mock=stale            그사이 상황이 바뀜
/results?mock=too-long         판단이 오래 걸림
/results?mock=unrecognized     판단 결과를 읽지 못함
/results?mock=judgment-failed-detail  홈의 "다시 알려주기"에서 온 경우 (더 알려주셔야 하는 실패)
/replan?mock=no-change      바뀐 것 없음 (다른 키는 바뀐 내용 · 새로 생긴 할 일 3개)
/log?mock=logs-empty        기록이 아직 없음 (다른 키는 예시 기록)
/docs?mock=docs             서류 목록 · 올리기 · 확인 필요 서류
/docs?mock=docs-issues      점검에서 빠진 서류가 나온 상태
/docs?mock=docs-complete    점검을 통과해 제출 파일을 볼 수 있는 상태
/roadmap?mock=roadmap       폐업 전체 순서 (2단계 진행 중). 할 일을 누르면 할 일 화면. 4단계 정산 항목은 "확인 필요"
/roadmap?mock=roadmap-unsupported  미지원 업종 안내
```

`?mock=` 없이 가짜 로그인만 하면 **판단이 끝난 화면**이 나옵니다.

**먼저 한 번 로그인해야 합니다.** 위 링크는 로그인한 상태를 전제로 하고, 안 되어 있으면
`/login`으로 갑니다. "가짜로 로그인"을 한 번 누르면 그 탭에서는 유지됩니다.

`/` 에서 붙인 `?mock=` 은 "결과 알려주기"를 눌러도 이어집니다. `/?mock=conflict` 로 들어가면
클릭만으로 충돌 흐름 끝까지 볼 수 있습니다. 다만 **다음 할 일이 없는 상태**(`pending` ·
`more-info` · `judgment-failed*` · `unrecognized`)에는 그 버튼이 없어서, 거기서는 흐름이
이어지지 않고 그 화면만 보입니다.

| 환경 | URL |
|---|---|
| Production | https://ktc4-kangwon-4.vercel.app |
| Preview (`develop`) | https://ktc4-kangwon-4-git-develop-blackwell-s-projects.vercel.app |

PR 브랜치는 배포될 때마다 별도 Preview URL이 생기며, PR 화면에서 확인할 수 있습니다.

## 폴더 구조

```
frontend/
├─ CLAUDE.md          Claude Code 작업 규칙
├─ docs/
│  └─ ui-guidelines.md
├─ src/
│  ├─ components/     재사용 UI
│  │  └─ ui/          새 시안 부품(버튼·배지·로더·빈 상태·머리말·탭·탭 틀·할 일 카드·홈 띠·단계 카드·소개·질문 한 장·처리 중·아래 시트).
│  │                  components/ 바로 아래의 옛 부품은 화면을 교체하며 지운다
│  ├─ pages/          화면
│  ├─ hooks/          화면이 데이터를 구하는 방법
│  ├─ adapters/       서버 모양 ↔ 화면 모양 변환
│  ├─ types/          api.ts — 서버가 주는 모양 (snake_case)
│  │                  view.ts — 화면이 필요한 모양 (camelCase)
│  ├─ mocks/          Mock 전환(?mock=)용 데이터
│  ├─ lib/            화면에 속하지 않는 보조 코드 (서버 호출 · 할 일 장면 표 · 주소 찾기 등)
│  ├─ stores/         Zustand — 화면 여러 장에 걸쳐 이어지는 답 (상황 진단)
│  ├─ styles/         tokens.css — 색·글자 크기·모서리·그림자 토큰
│  ├─ assets/         brand/ — 워드마크·망치 마크·카카오 심볼 SVG
│  │                  emoji/ — 상황 진단의 Fluent Emoji SVG (MIT, LICENSE 동봉)
│  ├─ routes.tsx      라우트 정의
│  ├─ main.tsx        진입점
│  ├─ App.tsx         RouterProvider
│  ├─ vite-env.d.ts   환경변수 타입 선언
│  └─ index.css       Tailwind·토큰 import, 본문 기본 스타일
├─ e2e/               브라우저 E2E (Playwright, 실제 BE · MySQL과 함께 돈다)
├─ index.html
├─ .env.example       로컬 BE 에 붙일 때만 필요
├─ playwright.config.ts
├─ vercel.json        SPA fallback + API 프록시
└─ vite.config.ts
```

화면이 16개(`routes.tsx`) 규모라 `features/` 없이 `pages/` + `components/` 로 나눈다.
데이터를 구하는 것은 페이지가, 그리는 것은 컴포넌트가 맡는다.
데이터가 흐르는 방향은 한 줄이다.

```
types/api.ts  →  adapters/  →  types/view.ts  →  components/
(서버 모양)                     (화면 모양)        (화면은 view 만 받는다)
```

서버 필드 이름이 바뀌면 `adapters/` 만 고친다. 화면은 서버 필드 이름을 모른다.

## 문서

- `CLAUDE.md` — FE 개발 규칙
- `docs/ui-guidelines.md` — 디자인 토큰과 UI 기준
- 화면 흐름(사장님이 지나가는 순서와 예외) → 레포 루트 `docs/hero-scenario.md`
- 데이터 모델 → 레포 루트 `docs/schema/`
- BE 배포 순서(백업 · 반영 · 되돌리기) → 레포 루트 `docs/deploy.md`
- 기술 구성 → 레포 루트 `docs/tech-stack.md`
- API 스펙 → 서버가 코드에서 만드는 OpenAPI(`/openapi.json`)
- CI/CD 구축안 → 팀 노션
