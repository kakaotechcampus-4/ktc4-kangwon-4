import { createBrowserRouter, Navigate } from 'react-router'

import { RequireAuth } from './components/RequireAuth'
import { CaseCreatePage } from './pages/CaseCreatePage'
import { ConfirmChangePage } from './pages/ConfirmChangePage'
import { CurrentCasePage } from './pages/CurrentCasePage'
import { EntryPage } from './pages/EntryPage'
import { LoginPage } from './pages/LoginPage'
import { ReplanPage } from './pages/ReplanPage'
import { ResultInputPage } from './pages/ResultInputPage'
import { StartPage } from './pages/StartPage'

/**
 * Hero Loop의 화면 순서가 그대로 경로가 된다.
 *
 *   /login     로그인         인증 가드 밖에 있는 유일한 화면
 *   /          진입 분기      보낼 곳만 정하고 화면은 없다
 *   /start     시작 화면      Case가 없는 사용자만 본다
 *   /cases/new Case 생성      사장님이 이미 아는 것만 묻는다
 *   /case      현재 Case      지금 무엇이 막혀 있고 무엇을 할 차례인가
 *   /results   결과 입력      실행한 결과를 한 줄로 말한다
 *   /confirm   충돌 확인      기존 기록과 어긋날 때만 들른다 (CONFLICT)
 *   /replan    재계획 결과    무엇이 바뀌었고 다음은 무엇인가
 *
 * `/confirm`은 `/results`와 `/replan` 사이의 단계가 아니라 예외 분기다.
 * 정상 경로는 `/results`에서 `/replan`으로 바로 간다.
 *
 * `/login`을 뺀 전부가 `RequireAuth` 아래에 있다. 화면마다 로그인을 검사하지 않고
 * 구조에 한 번 끼워 두면, 새 화면을 추가할 때 보호를 빠뜨릴 수 없다.
 *
 * 모르는 경로는 `/`로 보낸다. 거기서 지금 상태에 맞는 화면을 다시 고른다 —
 * `/case`로 바로 보내면 Case가 없는 사용자가 빈 화면을 본다.
 */
export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      { path: '/', element: <EntryPage /> },
      { path: '/start', element: <StartPage /> },
      { path: '/cases/new', element: <CaseCreatePage /> },
      { path: '/case', element: <CurrentCasePage /> },
      { path: '/results', element: <ResultInputPage /> },
      { path: '/confirm', element: <ConfirmChangePage /> },
      { path: '/replan', element: <ReplanPage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
