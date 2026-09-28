import { getAccessToken, logOut } from './auth'

/**
 * 서버를 부르는 유일한 자리.
 *
 * 주소와 인증 헤더를 화면마다 적으면 한 곳쯤은 빠뜨리고, 빠뜨려도 그 화면만 조용히
 * 401을 받아서 원인을 찾기 어렵다. 여기 한 번 모아두면 새 호출을 추가할 때 따라온다.
 *
 * 응답을 `Response` 그대로 돌려준다. 토큰이 본문이 아니라 **헤더**로 오기 때문에
 * 여기서 JSON으로 바꿔버리면 로그인이 헤더를 읽을 방법이 없어진다.
 */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

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

interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
}

/**
 * 네트워크 자체가 실패하면 `fetch`가 던지는 오류가 그대로 올라간다.
 * 서버가 준 답이 없다는 뜻이라 상태 코드로 감쌀 것이 없다.
 */
export async function request(path: string, { method = 'GET', body }: RequestOptions = {}) {
  const token = getAccessToken()

  const response = await fetch(`${API_BASE}${path}`, {
    method,
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

export interface LoginResult {
  accessToken: string
  refreshToken: string
  nickname: string
}

/**
 * 카카오가 준 `code`를 토큰으로 바꾼다. `code`는 한 번만 쓸 수 있다.
 *
 * 토큰은 본문이 아니라 응답 헤더로 온다. 그래서 서버에 `Access-Control-Expose-Headers`
 * 설정이 없거나 중간 프록시가 헤더를 지우면, **응답은 200인데 토큰만 비어 온다.**
 * 그 상태를 성공으로 넘기면 로그인한 것처럼 보이다가 다음 요청에서 401이 나므로
 * 여기서 실패로 끊는다.
 */
export async function postLogin(code: string): Promise<LoginResult> {
  const response = await request('/login', { method: 'POST', body: { code } })

  const accessToken = response.headers.get('Access-Token')
  const refreshToken = response.headers.get('Refresh-Token')

  if (accessToken === null || refreshToken === null) {
    throw new ApiError(response.status, '로그인 응답에서 토큰을 읽지 못했습니다.')
  }

  const { nickname } = (await response.json()) as { nickname: string }

  return { accessToken, refreshToken, nickname }
}
