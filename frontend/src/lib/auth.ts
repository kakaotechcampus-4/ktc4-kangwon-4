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
 * 카카오로 나갈 때 들려 보내고, 돌아올 때 맞춰보는 값.
 *
 * 이게 없으면 공격자가 자기 계정의 `code`가 담긴 `/login/callback?code=...` 링크를
 * 사장님에게 열게 해서, 사장님 브라우저를 공격자 계정으로 로그인시킬 수 있다.
 * 그 뒤 입력하는 폐업 정보가 전부 공격자 쪽에 쌓인다.
 *
 * 서버는 이 값을 저장하지도 검증하지도 않고 카카오에 그대로 실어 보내기만 한다.
 * 만들고 맞춰보는 것은 전부 여기 책임이다.
 */
const oauthState = createSessionValue('reborn:oauth-state')

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

/**
 * 이 화면이 서버 대신 Mock 을 봐야 하는지.
 *
 * `?mock=` 은 리뷰어가 링크 하나로 예외 화면을 보는 길이고, 가짜 세션은 Preview 에서
 * 진짜 카카오 로그인을 할 수 없어 만들어 둔 우회로다.
 *
 * 이 판단이 화면마다 흩어지면 한 곳이 달라진다. 실제로 Case 생성 화면만 `?mock=` 을
 * 빠뜨려서, Mock 링크를 따라가던 사람이 서버에 진짜 Case 를 만들고 있었다.
 */
export function usesMockData(search: string): boolean {
  return readMockKey(search) !== '' || isMockSession()
}

/**
 * 로그인 한 번에 값 하나. 시작할 때마다 새로 만들어 덮어쓴다.
 *
 * `crypto.randomUUID()`는 HTTPS 와 localhost 에서만 쓸 수 있는데, 우리 화면이 사는 곳이
 * 그 둘뿐이라 따로 대비하지 않는다.
 */
export function createOAuthState(): string {
  const value = crypto.randomUUID()
  oauthState.write(value)
  return value
}

/**
 * 카카오가 돌려준 값이 우리가 보낸 것과 같은지.
 *
 * **맞든 안 맞든 저장분을 지운다.** state 하나는 로그인 시도 하나다. 남겨두면 같은
 * 콜백 주소를 다시 열었을 때 또 통과한다.
 *
 * 세 갈래를 따로 본다. `returned !== saved` 하나만 쓰면 둘 다 `null` 일 때
 * `null !== null` 이 `false` 라서 통과한다 — state 를 아예 안 보내는, 제일 쉬운
 * 공격이 그대로 뚫린다.
 *
 * 저장소를 못 쓰는 브라우저에서는 저장분이 비어 있어 로그인이 막힌다. 검증을 건너뛰면
 * 막으려던 구멍이 그대로 남으므로 막히는 쪽을 고른다.
 */
export function verifyOAuthState(returned: string | null): boolean {
  const saved = oauthState.read()
  oauthState.write(null)

  return returned !== null && saved !== null && returned === saved
}
