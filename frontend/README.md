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

Mobile-first 반응형, 기준 폭 375px.

서버 통신은 `src/lib/api.ts` 한곳을 거칩니다. 주소와 `Access-Token` 헤더를 여기서 붙이고,
인증이 통하지 않으면 로그인 화면으로 돌려보냅니다.

**아직 도입하지 않은 것** — 웹폰트, 상태관리 라이브러리

## 화면

| 경로 | 화면 | 내용 |
|---|---|---|
| `/login` | 로그인 | 카카오. 인증 가드 밖 |
| `/login/callback` | 로그인 처리 | 카카오가 돌려보내는 자리. 역시 가드 밖 |
| `/` | 진입 분기 | 보낼 곳만 정하고 화면은 없다 |
| `/start` | 시작 화면 | Case가 없는 사용자만 본다 |
| `/cases/new` | Case 생성 | 사장님이 이미 아는 것만 묻는다 |
| `/case` | 현재 Case | 지금 막혀 있는 것과 다음에 할 일 |
| `/results` | 결과 입력 | 실행 결과를 한 줄로 전달 |
| `/confirm` | 충돌 확인 | 기존 기록과 어긋날 때만 들른다 |
| `/replan` | 재계획 결과 | 무엇이 바뀌었고 다음은 무엇인가 |

로그인 화면 둘을 뺀 전부가 인증 가드 아래에 있습니다. 로그인하지 않고 열면 `/login`으로 갑니다.

`/`는 화면이 아니라 분기입니다. 로그인 여부와 Case 유무를 보고 `/login`·`/start`·`/case` 중
하나로 보냅니다. 판단을 한곳에 모아두면 새 화면이 늘어도 규칙이 갈라지지 않습니다.

`/results`·`/confirm`·`/replan`은 이전 화면에서 라우터 state로 데이터를 받습니다. 주소로 직접 열면
개발·Preview에서는 Mock으로, 그 외에는 `/`로 이동합니다.

**Case 가 있는지는 서버에 물어봅니다.** `/` · `/start` · `/case` 가 들어올 때마다
`GET /cases` 를 부릅니다. 앞 화면에서 받은 값을 넘겨받지 않는 것은, 그 값이 히스토리에 남아
오래된 Case 가 "지금 상황"인 척 다시 뜨기 때문입니다.

로그인 토큰은 `sessionStorage`에 둡니다. 탭을 닫으면 풀립니다 — 가게나 공용 PC에서 쓰는
사용자가 있어 브라우저를 껐다 켜도 남는 쪽은 피했습니다.

## npm script

| 명령 | 설명 |
|---|---|
| `npm run dev` | 개발 서버 (5173) |
| `npm run build` | 프로덕션 빌드 (`tsc -b && vite build`) |
| `npm run lint` | ESLint |
| `npm run preview` | 빌드 결과 미리보기 |

## CI

`frontend/` 변경이 포함된 PR을 올리면 GitHub Actions가 아래를 자동으로 실행합니다.

```
npm ci  →  npm run lint  →  npm run build
```

- `feature/* → develop`, `develop → main` PR 모두 동일하게 실행됩니다
- 앞 단계가 실패하면 이후 단계는 실행되지 않습니다. PR의 Checks에서 로그를 확인합니다
- 고친 뒤 같은 브랜치에 push하면 기존 PR에서 자동으로 다시 실행됩니다

CI는 검증만 하고 배포하지 않습니다. 설정 파일은 레포 루트의 `.github/workflows/frontend-ci.yml` 입니다.

## 배포

merge되면 Vercel이 자동으로 배포합니다. 사람이 배포 명령을 실행하지 않습니다.

| 브랜치 | Vercel 환경 | 용도 |
|---|---|---|
| `main` | Production | 실제 서비스 |
| `develop` | Preview | 팀 통합 확인 |
| PR 브랜치 | Preview | 리뷰용 |

서버 주소는 Vercel에 환경변수로 두지 않습니다. 배포된 화면은 HTTPS인데 서버가 HTTP라
직접 부르면 브라우저가 막습니다. 그래서 `/api`로 보내고 `vercel.json`의 프록시가 서버로
넘깁니다. **BE에 인증서가 붙으면 이 규칙을 지웁니다.**

Preview 배포에서는 URL 쿼리로 예외 화면을 확인할 수 있고, 로그인 화면에 **"가짜로 로그인"**
버튼이 하나 더 나옵니다. `VITE_ENABLE_MOCK_SWITCH`를 Preview 환경에만 설정하기 때문이며,
Production에서는 둘 다 나오지 않습니다.

가짜 로그인이 필요한 이유는 카카오가 돌아올 주소를 정확히 일치하는 것만 허용하기 때문입니다.
PR 브랜치마다 Preview 주소가 달라 등록할 수 없어서, **리뷰어는 가짜 로그인으로 화면을 보고
진짜 카카오 로그인은 `develop` 머지 후 확인합니다.**

```
/?mock=logged-out           로그인 안 된 상태
/?mock=no-case              Case가 없는 사용자 (시작 화면)
/?mock=pending              판단 중 (Case를 막 만든 직후)
/?mock=pending-long         판단 중인데 오래 걸려 자동 조회를 멈춘 상태
/?mock=more-info            다음 할 일을 정하려면 더 물어봐야 하는 상태
/?mock=judgment-failed      판단 실패
/?mock=judgment-conflict    말한 내용이 기록과 달라 확인이 필요한 상태
/?mock=unrecognized         서버가 모르는 판단 상태를 보냈을 때
/results?mock=conflict      제출하면 충돌 확인으로
/results?mock=more-info     추가 질문
/results?mock=invalid       정정 요청
/results?mock=failed        재시도 안내
/replan?mock=no-change      바뀐 것 없음
```

`?mock=` 없이 가짜 로그인만 하면 **판단이 끝난 화면**이 나옵니다.

**먼저 한 번 로그인해야 합니다.** 위 링크는 로그인한 상태를 전제로 하고, 안 되어 있으면
`/login`으로 갑니다. "가짜로 로그인"을 한 번 누르면 그 탭에서는 유지됩니다.

`/` 에서 붙인 `?mock=` 은 "결과 알려주기"를 눌러도 이어집니다. `/?mock=conflict` 로 들어가면
클릭만으로 충돌 흐름 끝까지 볼 수 있습니다. 다만 **다음 할 일이 없는 상태**(`pending` ·
`more-info` · `judgment-failed` · `unrecognized`)에는 그 버튼이 없어서, 거기서는 흐름이
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
│  ├─ pages/          화면
│  ├─ hooks/          화면이 데이터를 구하는 방법
│  ├─ adapters/       서버 모양 ↔ 화면 모양 변환
│  ├─ types/          api.ts — 서버가 주는 모양 (snake_case)
│  │                  view.ts — 화면이 필요한 모양 (camelCase)
│  ├─ mocks/          Mock 전환(?mock=)용 데이터
│  ├─ lib/            화면에 속하지 않는 보조 코드
│  ├─ routes.tsx      라우트 정의
│  ├─ main.tsx        진입점
│  ├─ App.tsx         RouterProvider
│  ├─ vite-env.d.ts   환경변수 타입 선언
│  └─ index.css       Tailwind import
├─ index.html
├─ .env.example       로컬 BE 에 붙일 때만 필요
├─ vercel.json        SPA fallback + API 프록시
└─ vite.config.ts
```

화면이 8개 규모라 `features/` 없이 `pages/` + `components/` 로 나눈다.
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
- 화면 흐름 · API 스펙 · 데이터 모델 → 레포 루트 `docs/` (작성 예정)
- CI/CD 구축안 → 팀 노션
