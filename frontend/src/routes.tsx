import { createBrowserRouter, Navigate } from 'react-router'

import { ConfirmChangePage } from './pages/ConfirmChangePage'
import { CurrentCasePage } from './pages/CurrentCasePage'
import { ReplanPage } from './pages/ReplanPage'
import { ResultInputPage } from './pages/ResultInputPage'

/**
 * Hero Loop의 화면 순서가 그대로 경로가 된다.
 *
 *   /          ② 현재 Case      지금 무엇이 막혀 있고 무엇을 할 차례인가
 *   /results   ③ 결과 입력      실행한 결과를 한 줄로 말한다
 *   /confirm   ④ 충돌 확인      기존 기록과 어긋날 때만 들른다 (CONFLICT)
 *   /replan    ⑤ 재계획 결과    무엇이 바뀌었고 다음은 무엇인가
 *
 * ④는 ③과 ⑤ 사이의 단계가 아니라 예외 분기다. 정상 경로는 ③에서 ⑤로 바로 간다.
 *
 * 모르는 경로는 ②로 보낸다. 이 제품에서 사용자가 돌아갈 곳은 언제나 현재 Case다.
 */
export const router = createBrowserRouter([
  { path: '/', element: <CurrentCasePage /> },
  { path: '/results', element: <ResultInputPage /> },
  { path: '/confirm', element: <ConfirmChangePage /> },
  { path: '/replan', element: <ReplanPage /> },
  { path: '*', element: <Navigate to="/" replace /> },
])
