import { Navigate, useLocation } from 'react-router'

import { readMockKey } from '../lib/mockSwitch'

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
 * `/?mock=insufficient` 가 `/case?mock=insufficient` 로 이어진다.
 */
export function EntryPage() {
  const { search } = useLocation()

  /**
   * TODO(API): `GET /cases` 응답의 `case`가 `null`인지로 판단한다.
   * 지금은 즉시 끝나지만 연동하면 응답을 기다리는 로딩 상태가 생긴다.
   */
  const hasCase = readMockKey(search) !== 'no-case'

  return <Navigate to={{ pathname: hasCase ? '/case' : '/start', search }} replace />
}
