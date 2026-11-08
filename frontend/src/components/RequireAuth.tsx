import { Navigate, Outlet, useLocation } from 'react-router'

import { isLoggedIn } from '../lib/auth'
import { useNavigationDirection } from '../lib/viewTransition'
import { JudgmentWatcher } from './JudgmentWatcher'

/**
 * 로그인한 사용자만 지나갈 수 있는 문.
 *
 * 로그인 검사를 화면마다 넣으면 새 화면을 추가할 때 빠뜨리기 쉽고, 빠뜨려도 화면은
 * 멀쩡히 보여서 티가 안 난다. 라우트 구조에 한 번 끼워 두면 그 아래는 전부 보호된다.
 *
 * 로그인 여부를 판단하는 규칙 자체는 `lib/auth`에 있다. `?mock=logged-out` 처리까지
 * 거기서 끝내는 이유는, 규칙이 두 군데로 나뉘면 한쪽만 고쳐져서 서로 다른 답을 내기 때문이다.
 *
 * 들어온 뒤 토큰이 만료되면 서버가 401 을 준다. 그때는 이 문이 아니라 서버를 부른 화면이
 * 로그인으로 보낸다(`UnauthorizedError`).
 *
 * 화면 이동 방향도 여기서 한 번 적는다(`useNavigationDirection`). 움직이는 화면이 모두 이 아래에 있다.
 *
 * 판단이 끝나면 알리는 띠(`JudgmentWatcher`)도 여기 둔다. 로그인한 화면 어디에 있든 떠야 한다.
 */
export function RequireAuth() {
  const { search } = useLocation()
  useNavigationDirection()

  if (!isLoggedIn(search)) return <Navigate to={{ pathname: '/login', search }} replace />

  return (
    <>
      <Outlet />
      <JudgmentWatcher />
    </>
  )
}
