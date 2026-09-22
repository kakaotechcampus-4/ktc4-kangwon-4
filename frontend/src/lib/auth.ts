import { readMockKey } from './mockSwitch'
import { createSessionFlag } from './sessionFlag'

/**
 * 로그인 상태.
 *
 * 화면이 알아야 하는 것은 "지금 로그인돼 있나" 하나뿐이다. 토큰을 어디에 어떤 형태로
 * 보관할지는 아직 정해지지 않았고, 그 결정이 화면 코드에 스며들면 나중에 전부 따라
 * 바뀐다. 그래서 저장 방식은 이 파일 안에만 두고 밖으로는 불리언만 내보낸다.
 *
 * TODO(API): 실제로는 `POST /login` 응답 헤더(`Access-Token` / `Refresh-Token`)를 받아
 * 보관하고, 보호된 요청마다 `Access-Token` 헤더로 실어 보낸다. 보관 위치·만료 처리·
 * `POST /reissue` 재발급 시점은 아직 정해지지 않았다.
 */
const flag = createSessionFlag('reborn:logged-in')

/**
 * `search`를 반드시 받는다. `?mock=logged-out` 처리를 호출부가 빼먹으면 화면마다
 * 다른 답이 나오는데, 인자로 요구하면 빼먹을 수가 없다.
 */
export function isLoggedIn(search: string): boolean {
  if (readMockKey(search) === 'logged-out') return false
  return flag.read()
}

export function logIn(): void {
  flag.write(true)
}

export function logOut(): void {
  flag.write(false)
}
