import { Navigate, useLocation } from 'react-router'

import { useCase } from '../hooks/useCase'

/**
 * 진입 분기. 화면이 없고 보낼 곳만 정한다.
 *
 * 로그인 검사는 이 위의 `RequireAuth`가 이미 끝냈다. 여기 도착했다는 것은 로그인한
 * 사용자라는 뜻이라, Case가 있는지만 보면 된다.
 *
 * `replace`를 쓰는 이유는 이 경로가 뒤로가기 목록에 남으면 안 되기 때문이다.
 * 남으면 `/case`에서 뒤로 눌렀을 때 다시 `/case`로 튕겨 나가 빠져나갈 수 없다.
 *
 * `search`를 그대로 넘기는 것은 `?mock=` 링크 하나로 흐름을 따라갈 수 있게 하려는 것이다.
 * `/?mock=more-info` 가 `/case?mock=more-info` 로 이어진다.
 */
export function EntryPage() {
  const { search } = useLocation()
  const { query } = useCase()

  // 곧 다른 화면으로 옮겨 갈 자리라 로딩 안내를 두지 않는다.
  // 여기서 뭔가 보여주면 다음 화면의 안내와 겹쳐 두 번 깜빡인다
  if (query.status === 'LOADING') return null

  /**
   * 서버를 못 불렀으면 Case 가 있는지 알 수 없다. 그래도 현재 Case 로 보낸다 —
   * 실패 안내를 두 화면에 만들지 않고 한 곳에서만 한다.
   */
  const next = query.status === 'EMPTY' ? '/start' : '/case'

  return <Navigate to={{ pathname: next, search }} replace />
}
