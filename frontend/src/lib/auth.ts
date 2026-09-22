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

const STORAGE_KEY = 'reborn:logged-in'

/**
 * sessionStorage를 쓸 수 없는 환경(사생활 보호 모드, 저장소 차단)의 대체 저장소.
 *
 * 이 경우 새로고침하면 로그인이 풀리지만, 화면이 아예 멈추는 것보다는 낫다.
 */
let fallback = false

/**
 * sessionStorage를 쓰는 이유는 탭을 닫으면 같이 끝나기 때문이다.
 * 공용 PC에서 쓰는 사용자가 있을 수 있어 브라우저를 껐다 켜도 남아 있게 두지 않는다.
 */
export function isLoggedIn(): boolean {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return fallback
  }
}

export function logIn(): void {
  write(true)
}

export function logOut(): void {
  write(false)
}

function write(value: boolean): void {
  fallback = value
  try {
    window.sessionStorage.setItem(STORAGE_KEY, String(value))
  } catch {
    // 대체 저장소에 이미 담았다
  }
}
