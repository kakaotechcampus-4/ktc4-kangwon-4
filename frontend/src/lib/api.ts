import { getAccessToken, logOut, verifyOAuthState } from './auth'

/**
 * 서버를 부르는 유일한 자리.
 *
 * 주소와 인증 헤더를 화면마다 적으면 한 곳쯤은 빠뜨리고, 빠뜨려도 그 화면만 조용히
 * 401을 받아서 원인을 찾기 어렵다. 여기 한 번 모아두면 새 호출을 추가할 때 따라온다.
 *
 * 응답을 `Response` 그대로 돌려준다. 토큰이 본문이 아니라 **헤더**로 오기 때문에
 * 여기서 JSON으로 바꿔버리면 로그인이 헤더를 읽을 방법이 없어진다.
 */
// `??` 가 아니라 `||` 다. `.env` 에 `VITE_API_BASE_URL=` 처럼 이름만 두면 Vite 가
// `undefined` 가 아니라 빈 문자열로 읽는데, 그러면 요청이 FE 자기 주소로 나가
// 화면 경로에 부딪힌다 — 오류 없이 아무 일도 일어나지 않는 것처럼 보인다
const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

/**
 * 요청을 보내고 **본문까지 다 받기를** 기다리는 시간.
 *
 * 성능 예산이 아니라 "서버가 답을 안 준다"를 가려내는 값이다. 제한이 없으면 그 요청이
 * 영영 끝나지 않고, 끝나기를 기다리는 쪽(`useCase`)의 뒷정리도 같이 멈춘다 —
 * 자동 조회도 다시 확인 버튼도 막혀서 사장님이 화면에 갇힌다.
 *
 * 폴링 간격(10초)보다 길어 한 주기를 건너뛰지만, 조회 쪽이 중복 요청을 막고 있다.
 *
 * 아직 실서버 응답 시간을 재보지 못해 잡아둔 초기값이다. 배포 뒤 실제 조회 응답 시간을
 * 보고 다시 정한다.
 */
export const REQUEST_TIMEOUT_MS = 15_000

/** 서버가 2xx가 아닌 것을 돌려줬을 때 */
export class ApiError extends Error {
  // 생성자 인자에 `readonly`를 붙이는 축약형은 이 프로젝트의 `erasableSyntaxOnly`
  // 설정에서 막힌다. 타입만 지우면 실행되는 코드로 남아야 하기 때문이다
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

/**
 * 인증이 통하지 않았을 때. BE가 헤더 누락·만료·위조·토큰 종류 불일치를 전부 401로 준다.
 *
 * TODO(API): 다음 PR에서 보호된 호출이 생기면 이 오류를 받아 `/login`으로 보낸다.
 * 지금은 로그인 요청 하나뿐이라 보낼 곳이 없다.
 */
export class UnauthorizedError extends ApiError {
  constructor(message = '로그인이 필요합니다.') {
    super(401, message)
    this.name = 'UnauthorizedError'
  }
}

/**
 * 제한 시간 안에 응답 수신을 마치지 못했다.
 *
 * 이유 없이 취소하면 `DOMException: AbortError`가 올라와 **네트워크 실패와 구분되지 않는다.**
 * 취소한 이유를 직접 넘겨서 "우리가 끊었다"가 남게 한다.
 */
export class TimeoutError extends Error {
  constructor(message = '제한 시간 안에 응답을 다 받지 못했습니다.') {
    super(message)
    this.name = 'TimeoutError'
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
}

/**
 * 네트워크 자체가 실패하면 `fetch`가 던지는 오류가 그대로 올라간다.
 * 서버가 준 답이 없다는 뜻이라 상태 코드로 감쌀 것이 없다.
 *
 * 제한 시간을 넘기면 요청을 취소한다. **취소를 예약한 타이머는 지우지 않는다** —
 * 이 함수는 `Response`만 돌려주고 본문은 호출부가 나중에 읽는데, 응답을 받자마자 지우면
 * **헤더만 오고 본문이 멈추는 경우**를 못 막는다. 이미 끝난 요청을 취소하는 것은 아무 일도
 * 하지 않으므로, 정상 응답 뒤 하는 일 없는 타이머가 잠시 남는 대신 본문까지 보호한다.
 */
export async function request(path: string, { method = 'GET', body }: RequestOptions = {}) {
  const token = getAccessToken()

  const controller = new AbortController()
  setTimeout(() => controller.abort(new TimeoutError()), REQUEST_TIMEOUT_MS)

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    signal: controller.signal,
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      // BE가 표준 Authorization 대신 커스텀 헤더를 쓴다
      ...(token === null ? {} : { 'Access-Token': token }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401) {
    // 못 쓰는 토큰을 들고 있으면 다음 요청도 똑같이 막힌다
    logOut()
    throw new UnauthorizedError()
  }

  if (!response.ok) throw new ApiError(response.status, `요청이 실패했습니다 (${response.status})`)

  return response
}

/**
 * 카카오 로그인 화면으로 가는 주소.
 *
 * `fetch`로 부를 수 없다. 서버가 303으로 카카오에 넘기는데, 그 리다이렉트를 따라가는 것은
 * 브라우저가 할 일이다. 주소를 만드는 규칙은 여기 두고 화면은 이동만 시킨다.
 *
 * `state`를 인자로 **반드시** 받는다. 빼먹어도 로그인은 멀쩡히 되는데 돌아왔을 때
 * 맞춰볼 것이 없어져, 실수가 화면에 드러나지 않는다. 인자로 요구하면 컴파일에서 막힌다.
 *
 * UUID에는 특수문자가 없지만 그래도 감싼다. 규칙이 값의 생김새에 기대면,
 * 나중에 값을 바꾼 사람이 여기까지 보지 않는다.
 */
export function loginFormUrl(state: string): string {
  return `${API_BASE}/login/form?state=${encodeURIComponent(state)}`
}

export interface LoginResult {
  accessToken: string
  refreshToken: string
  nickname: string
}

/**
 * 카카오가 준 `code`를 토큰으로 바꾼다. `code`는 한 번만 쓸 수 있다.
 *
 * `state` 검사를 화면이 아니라 여기 둔다. 이 함수가 하는 일은 "돌아온 콜백을 세션으로
 * 바꾸는 것"이고, **그 콜백을 믿어도 되는가**는 그 일의 일부다. 떼어놓으면 검사를
 * 건너뛰고 이 함수를 부르는 길이 생긴다.
 *
 * 토큰은 본문이 아니라 응답 헤더로 온다. 그래서 서버에 `Access-Control-Expose-Headers`
 * 설정이 없거나 중간 프록시가 헤더를 지우면, **응답은 200인데 토큰만 비어 온다.**
 * 그 상태를 성공으로 넘기면 로그인한 것처럼 보이다가 다음 요청에서 401이 나므로
 * 여기서 실패로 끊는다.
 */
export async function postLogin(code: string, state: string | null): Promise<LoginResult> {
  // 돌아온 콜백이 우리가 시작한 로그인인지 먼저 본다. 서버를 부르기 전에 막아야
  // 공격자의 code 가 토큰으로 바뀌지 않는다.
  if (!verifyOAuthState(state)) {
    throw new ApiError(400, '로그인 요청이 올바르지 않습니다.')
  }

  const response = await request('/login', { method: 'POST', body: { code } })

  const accessToken = response.headers.get('Access-Token')
  const refreshToken = response.headers.get('Refresh-Token')

  if (accessToken === null || refreshToken === null) {
    throw new ApiError(response.status, '로그인 응답에서 토큰을 읽지 못했습니다.')
  }

  const { nickname } = (await response.json()) as { nickname: string }

  return { accessToken, refreshToken, nickname }
}
