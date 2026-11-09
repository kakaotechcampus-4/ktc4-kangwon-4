import { getAccessToken, getRefreshToken, logOut, saveTokens, verifyOAuthState } from './auth'

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
  /** 서버가 오류 본문 `detail.code` 로 알려 준 이유. 없으면 null(지금은 서류 안전 검사만 보낸다) */
  readonly code: string | null

  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.status = status
    this.code = code
    this.name = 'ApiError'
  }
}

/** 오류 응답 본문의 `detail.code`. 본문이 JSON 이 아니거나 코드가 없으면 null */
async function errorCode(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: { code?: unknown } } | null
    const code = body?.detail?.code
    return typeof code === 'string' ? code : null
  } catch {
    return null
  }
}

/**
 * 인증이 통하지 않았을 때. BE가 헤더 누락·만료·위조·토큰 종류 불일치를 전부 401로 준다.
 *
 * 서버를 부르는 쪽(`useCase` · `useLogs` · `useRoadmap` 등)이 이 오류를 받으면 `/login`으로 보낸다.
 * 못 쓰는 토큰은 여기서 먼저 지운다(`request` 의 `logOut`).
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
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  /**
   * 보낼 것. 보통은 JSON으로 바꿔 보낸다. `FormData`(파일 올리기)는 그대로 보낸다 —
   * 경계 문자열이 든 `Content-Type`은 브라우저가 직접 붙여야 해서 여기서 적지 않는다
   */
  body?: unknown
  /**
   * 이 요청만의 제한 시간. 서류 올리기처럼 서버가 끝날 때까지 붙잡고 있는 요청에 쓴다.
   * 비우면 `REQUEST_TIMEOUT_MS`다
   */
  timeoutMs?: number
}

/**
 * 네트워크 자체가 실패하면 `fetch`가 던지는 오류가 그대로 올라간다.
 * 서버가 준 답이 없다는 뜻이라 상태 코드로 감쌀 것이 없다.
 *
 * **401이면 로그인 토큰을 새로 받아 한 번만 다시 보낸다.** 서버의 로그인 토큰은 30분짜리라
 * (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`), 다시 받지 않으면 30분 뒤 첫 요청에서 로그인 화면으로 간다
 * (#212). 다시 받을 수 없거나, 새 토큰으로 보내도 401이면 토큰을 지우고 `UnauthorizedError` 를 던진다 —
 * 못 쓰는 토큰을 들고 있으면 다음 요청도 똑같이 막힌다.
 *
 * **기다리는 사이 로그인이 바뀌었으면 지금 로그인을 덮거나 지우지 않는다**(승준님 #210). 로그아웃했거나
 * 새로 로그인했는데 옛 로그인의 늦은 응답이 토큰을 저장하거나 지우면, 끝낸 로그인이 되살아나거나 새 로그인이
 * 풀린다. 그때는 토큰에 손대지 않고 `UnauthorizedError` 만 올린다. 화면은 로그인으로 보내고, 로그인 화면은
 * 이미 로그인돼 있으면 진입 분기로 돌려보낸다(`LoginPage`). `ApiError(409)` 로 멈추지 않는 이유는 화면들이
 * 409 를 그 API 의 뜻(거절됨 · 상황 바뀜)으로 읽어서다.
 */
export async function request(path: string, options: RequestOptions = {}) {
  const sentWith = readTokens()
  let response = await send(path, options, sentWith.access)

  if (response.status === 401) {
    const renewed = await renewedAfter(path, sentWith)
    response = await send(path, options, renewed.access)
    if (response.status === 401) endSession(renewed)
  }

  if (!response.ok) throw new ApiError(response.status, `요청이 실패했습니다 (${response.status})`, await errorCode(response))

  return response
}

/**
 * 한 번 보낸다. 다시 보낼 때도 같은 것을 새로 만들어 보낸다 — 제한 시간도 새로 센다.
 *
 * 제한 시간을 넘기면 요청을 취소한다. **취소를 예약한 타이머는 지우지 않는다** —
 * 이 함수는 `Response`만 돌려주고 본문은 호출부가 나중에 읽는데, 응답을 받자마자 지우면
 * **헤더만 오고 본문이 멈추는 경우**를 못 막는다. 이미 끝난 요청을 취소하는 것은 아무 일도
 * 하지 않으므로, 정상 응답 뒤 하는 일 없는 타이머가 잠시 남는 대신 본문까지 보호한다.
 */
function send(
  path: string,
  { method = 'GET', body, timeoutMs = REQUEST_TIMEOUT_MS }: RequestOptions,
  token: string | null,
  extraHeaders: Record<string, string> = {},
) {
  const isForm = body instanceof FormData

  const controller = new AbortController()
  setTimeout(() => controller.abort(new TimeoutError()), timeoutMs)

  return fetch(`${API_BASE}${path}`, {
    method,
    signal: controller.signal,
    headers: {
      ...(body === undefined || isForm ? {} : { 'Content-Type': 'application/json' }),
      // BE가 표준 Authorization 대신 커스텀 헤더를 쓴다
      ...(token === null ? {} : { 'Access-Token': token }),
      ...extraHeaders,
    },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  })
}

const REISSUE_PATH = '/reissue'

/** 한 로그인의 토큰 한 쌍. 다시 받을 때마다 둘 다 바뀐다 */
interface Tokens {
  access: string | null
  refresh: string | null
}

function readTokens(): Tokens {
  return { access: getAccessToken(), refresh: getRefreshToken() }
}

function isCurrent(tokens: Tokens): boolean {
  return tokens.access === getAccessToken() && tokens.refresh === getRefreshToken()
}

/**
 * 이 토큰으로는 더 이어 갈 수 없다. 아직 이 토큰을 들고 있을 때만 지운다 — 그사이 로그아웃했거나 새로
 * 로그인했으면 지금 것은 이 실패와 상관없다.
 */
function endSession(tokens: Tokens): never {
  if (isCurrent(tokens)) logOut()
  throw new UnauthorizedError()
}

/**
 * 401을 받은 뒤 다시 보낼 토큰. 받을 수 없으면 `UnauthorizedError` 를 던진다.
 *
 * 보낸 사이 Refresh 토큰이 바뀌었으면 다른 요청이 이미 새로 받은 것이라 또 받지 않고 지금 것으로 다시
 * 보낸다. 새로 로그인한 경우도 토큰만으로는 이와 가를 수 없어 같이 다시 보낸다. 비어 있으면 그사이
 * 로그아웃한 것이다. 다시 받기 자신이 401이면 받을 길이 없다.
 */
async function renewedAfter(path: string, sentWith: Tokens): Promise<Tokens> {
  if (path === REISSUE_PATH) endSession(sentWith)
  const current = readTokens()
  if (current.refresh !== sentWith.refresh) {
    if (current.access === null) throw new UnauthorizedError()
    return current
  }
  return reissueTokens(sentWith)
}

/**
 * 지금 진행 중인 다시 받기와 그것을 시작한 토큰. 여럿이 동시에 401을 받아도 같은 토큰이면 다시 받기는
 * 하나만 나간다. 토큰이 다르면(그사이 로그인이 바뀜) 따로 받는다.
 */
let reissuing: { from: string | null; promise: Promise<Tokens> } | null = null

/**
 * 로그인 토큰을 새로 받는다(`POST /reissue`). 새 토큰을 돌려준다.
 *
 * **한 번에 하나만 보낸다.** 서버는 Refresh 토큰을 쓸 때마다 새것으로 바꾸고 마지막 하나만 기억한다.
 * 동시에 둘이 보내면 뒤의 것은 이미 바뀐 옛 토큰을 보내 401이 되고, 사장님은 로그아웃된다.
 *
 * Refresh 토큰이 없으면(가짜 세션 · 로그아웃) 받지 않는다. 서버가 거절하거나 새 토큰을 읽지 못하면
 * 이 로그인은 끝난 것이다(`endSession`). 연결 실패 · 5xx 는 토큰을 그대로 두고 오류를 올린다.
 * 서버가 거절한 게 아니라 답을 못 받은 것이라, 지우면 잠깐 끊긴 연결로 로그아웃된다.
 */
function reissueTokens(tokens: Tokens): Promise<Tokens> {
  if (reissuing !== null && reissuing.from === tokens.refresh) return reissuing.promise

  const mine = {
    from: tokens.refresh,
    promise: renew(tokens).finally(() => {
      // 옛 로그인의 다시 받기가 늦게 끝나도, 그 뒤 시작한 새 로그인의 다시 받기는 남겨 둔다
      if (reissuing === mine) reissuing = null
    }),
  }
  reissuing = mine
  return mine.promise
}

async function renew(tokens: Tokens): Promise<Tokens> {
  if (tokens.refresh === null) endSession(tokens)

  const response = await send(REISSUE_PATH, { method: 'POST' }, null, { 'Refresh-Token': tokens.refresh })
  // 기다리는 사이 로그아웃했거나 새로 로그인했다. 늦게 온 답으로 지금 로그인을 덮거나 지우지 않는다
  if (!isCurrent(tokens)) throw new UnauthorizedError()
  if (response.status === 401) endSession(tokens)
  if (!response.ok) throw new ApiError(response.status, `로그인을 이어 가지 못했습니다 (${response.status})`)

  const access = response.headers.get('Access-Token')
  const nextRefresh = response.headers.get('Refresh-Token')
  // 서버는 이미 Refresh 토큰을 바꿨다. 새 값을 못 읽으면 들고 있는 것은 더 쓸 수 없다
  if (access === null || nextRefresh === null) endSession(tokens)

  saveTokens(access, nextRefresh)
  return { access, refresh: nextRefresh }
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

/** 로그아웃 요청을 기다리는 시간 */
const LOGOUT_TIMEOUT_MS = 5_000

/**
 * 서버에 로그아웃을 알린다(`POST /logout`). 서버는 이 회원의 Refresh 토큰을 지운다.
 *
 * 브라우저의 토큰만 지우면 서버에는 Refresh 토큰이 남아, 어딘가 복사돼 있던 값으로 새 로그인을
 * 계속 받을 수 있다. 그래서 화면은 이것을 부른 **뒤에** 브라우저 토큰도 지운다(`logOut`).
 * 실패하면 오류를 그대로 올린다 — 그래도 로그아웃할지는 화면이 정한다.
 */
export async function logOutFromServer(): Promise<void> {
  // 기다리는 동안 사장님은 로그아웃을 누른 화면에 남아 있다. 응답이 늦으면 기본 15초 대신
  // 짧게 끊고 화면 쪽 로그아웃으로 넘어간다
  await request('/logout', { method: 'POST', timeoutMs: LOGOUT_TIMEOUT_MS })
}
