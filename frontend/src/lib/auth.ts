import { MOCK_SWITCH_ENABLED, readMockKey } from './mockSwitch'
import { createSessionValue } from './sessionStore'

/**
 * 로그인 상태와 토큰.
 *
 * 토큰이 어디에 어떤 이름으로 담기는지는 이 파일 밖으로 나가지 않는다. 화면은
 * "로그인돼 있나"만 묻고, 서버를 부르는 쪽은 "실어 보낼 값"만 가져간다.
 *
 * `sessionStorage`에 두는 것은 탭을 닫으면 같이 끝나기 때문이다. 가게 컴퓨터나 공용 PC를
 * 쓰는 사용자가 있어 브라우저를 껐다 켜도 로그인이 남는 쪽은 피했다. 대신 새 탭에서는
 * 카카오 로그인을 다시 거친다.
 *
 * TODO(보안): Access는 메모리에만 두고 Refresh만 저장소에 남기는 쪽으로 옮긴다.
 * 그러면 XSS에 노출되는 범위가 줄지만 새로고침마다 `POST /reissue`가 필요해서
 * 재발급 실패 경로까지 함께 설계해야 한다.
 */
const accessToken = createSessionValue('reborn:access-token')
const refreshToken = createSessionValue('reborn:refresh-token')

/**
 * 가짜 로그인을 표시하는 값.
 *
 * 카카오는 돌아올 주소를 정확히 일치하는 것만 허용해서, 주소가 매번 다른 feature 브랜치
 * Preview에서는 진짜 로그인을 할 수 없다. 리뷰어가 화면을 보려면 우회로가 필요하다.
 */
const MOCK_TOKEN = 'mock-session'

/**
 * `search`를 반드시 받는다. `?mock=logged-out` 처리를 호출부가 빼먹으면 화면마다
 * 다른 답이 나오는데, 인자로 요구하면 빼먹을 수가 없다.
 */
export function isLoggedIn(search: string): boolean {
  if (readMockKey(search) === 'logged-out') return false
  return accessToken.read() !== null
}

/** 보호된 요청에 `Access-Token` 헤더로 실을 값 */
export function getAccessToken(): string | null {
  return accessToken.read()
}

export function saveTokens(access: string, refresh: string): void {
  accessToken.write(access)
  refreshToken.write(refresh)
}

/**
 * TODO(테스트): Refresh 토큰이 지워지는지는 지금 테스트로 못 잡는다 — 꺼내 보는 함수가
 * 없어서다. `/reissue`를 붙일 때 `getRefreshToken()`과 함께 테스트를 넣는다.
 * 남아 있으면 로그아웃한 사용자가 재발급으로 되살아난다.
 */
export function logOut(): void {
  accessToken.write(null)
  refreshToken.write(null)
}

/**
 * Mock 전환이 허용된 환경에서만 동작한다. Production에서는 아무 일도 하지 않는다 —
 * 호출부가 실수로 남아 있어도 실제 사용자가 가짜 세션을 갖지 않게 한다.
 */
export function logInWithMock(): void {
  if (!MOCK_SWITCH_ENABLED) return
  accessToken.write(MOCK_TOKEN)
  refreshToken.write(null)
}

/**
 * 가짜 세션인지.
 *
 * TODO(API): 다음 PR에서 Case를 서버에 물을 때, 가짜 세션이면 서버를 부르지 않고
 * Mock 데이터를 쓴다. 지금 그대로 보내면 서버가 401로 돌려보낸다.
 */
export function isMockSession(): boolean {
  return accessToken.read() === MOCK_TOKEN
}
