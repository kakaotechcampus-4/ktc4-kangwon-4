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

## 스택

| 기술 | 비고 |
|---|---|
| React 19 + TypeScript | UI · 컴포넌트 |
| Vite | 빌드 도구 |
| Tailwind CSS 4 | `tailwind.config.js`와 PostCSS 설정이 **없습니다**. `@tailwindcss/vite` 플러그인과 `src/index.css`의 `@import "tailwindcss";` 로 동작합니다 |
| Fetch API | 통신 |
| React 내장 | 상태관리 (`useState` / `useContext`) |

Mobile-first 반응형, 기준 폭 375px.

**아직 도입하지 않은 것** — React Router(라우트가 생기는 시점에 추가), 배포(플랫폼 검토 중)

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

배포는 포함되지 않습니다. 설정 파일은 레포 루트의 `.github/workflows/frontend-ci.yml` 입니다.

## 폴더 구조

```
frontend/
├─ CLAUDE.md          Claude Code 작업 규칙
├─ docs/
│  └─ ui-guidelines.md
├─ src/
│  ├─ components/     재사용 UI
│  ├─ pages/          화면
│  ├─ types/          view.ts — 화면이 필요한 데이터 모양
│  ├─ mocks/          서버 연동 전 데이터 소스
│  ├─ main.tsx        진입점
│  ├─ App.tsx
│  └─ index.css       Tailwind import
├─ index.html
└─ vite.config.ts
```

화면이 5개 규모라 `features/` 없이 `pages/` + `components/` 로 나눈다.
`types/api.ts`(서버 계약)와 `adapters/`는 서버 스키마가 확정되면 추가한다.

## 문서

- `CLAUDE.md` — FE 개발 규칙
- `docs/ui-guidelines.md` — 디자인 토큰과 UI 기준
- 화면 흐름 · API 스펙 · 데이터 모델 → 레포 루트 `docs/` (작성 예정)
- CI/CD 구축안 → 팀 노션
