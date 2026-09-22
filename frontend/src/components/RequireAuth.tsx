import { Navigate, Outlet, useLocation } from 'react-router'

import { isLoggedIn } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'

/**
 * 로그인한 사용자만 지나갈 수 있는 문.
 *
 * 로그인 검사를 화면마다 넣으면 새 화면을 추가할 때 빠뜨리기 쉽고, 빠뜨려도 화면은
 * 멀쩡히 보여서 티가 안 난다. 라우트 구조에 한 번 끼워 두면 그 아래는 전부 보호된다.
 *
 * 로그인 여부를 판단하는 곳도 여기 하나다. `?mock=logged-out` 처리가 여기 있는 이유는,
 * 이 규칙이 두 군데로 나뉘면 한쪽만 고쳐져서 서로 다른 답을 내기 때문이다.
 *
 * TODO(API): 연동하면 보호된 요청이 401로 돌아올 때도 이 화면으로 보내야 한다.
 * 토큰이 중간에 만료되는 경우가 그렇다.
 */
export function RequireAuth() {
  const { search } = useLocation()
  const loggedIn = readMockKey(search) === 'logged-out' ? false : isLoggedIn()

  if (!loggedIn) return <Navigate to={{ pathname: '/login', search }} replace />

  return <Outlet />
}
