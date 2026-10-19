import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  postLogin,
  request,
  REQUEST_TIMEOUT_MS,
  TimeoutError,
  UnauthorizedError,
} from './api'
import { createOAuthState, getAccessToken, saveTokens } from './auth'

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), { status: 200, ...init })
}

function mockFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** 호출 한 번의 인자를 읽는다 */
function calledWith(fetchMock: ReturnType<typeof vi.fn>) {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
  return { url, headers: new Headers(init.headers), init }
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 인증 헤더를 화면마다 붙이면 한 곳쯤 빠뜨리고, 빠뜨려도 그 화면만 조용히 401을 받는다.
 * 여기서 한 번에 붙는다는 것을 고정해 두면 새 호출이 늘어도 따라온다.
 */
describe('request', () => {
  it('로그인했으면 Access-Token 헤더를 싣는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetch(jsonResponse({}))

    await request('/cases')

    expect(calledWith(fetchMock).headers.get('Access-Token')).toBe('access-1')
  })

  it('로그인하지 않았으면 Access-Token 헤더를 싣지 않는다', async () => {
    const fetchMock = mockFetch(jsonResponse({}))

    await request('/login', { method: 'POST', body: { code: 'abc' } })

    expect(calledWith(fetchMock).headers.has('Access-Token')).toBe(false)
  })

  /**
   * 주소를 정하는 규칙만 따로 본다.
   *
   * 이 값은 모듈을 읽어 들일 때 한 번 계산되고, 개발자마다 `.env.local` 이 달라서
   * 그냥 두면 "내 컴퓨터에서만 깨지는" 테스트가 된다. 환경을 직접 세우고 다시 읽는다.
   */
  async function loadApiWith(base: string | undefined) {
    vi.stubEnv('VITE_API_BASE_URL', base as string)
    vi.resetModules()
    return import('./api')
  }

  async function urlFor(base: string | undefined) {
    const { request: freshRequest } = await loadApiWith(base)
    const fetchMock = mockFetch(jsonResponse({}))

    await freshRequest('/cases')

    vi.unstubAllEnvs()
    vi.resetModules()
    return calledWith(fetchMock).url
  }

  /** 배포 화면이 HTTPS 라 프록시를 거쳐야 한다. 그때는 같은 출처로 보낸다 */
  it('환경변수가 없으면 /api 로 보낸다', async () => {
    expect(await urlFor(undefined)).toBe('/api/cases')
  })

  /**
   * `.env.example` 을 그대로 복사하면 이름만 있고 값이 없는 상태가 되는데, Vite 는 그걸
   * `undefined` 가 아니라 빈 문자열로 읽는다. 빈 문자열이 통과하면 요청이 FE 자기 주소로
   * 나가 화면 경로에 부딪히고, 오류 없이 아무 일도 없는 것처럼 보인다.
   */
  it('환경변수가 비어 있어도 /api 로 보낸다', async () => {
    expect(await urlFor('')).toBe('/api/cases')
  })

  it('환경변수가 있으면 그 주소로 보낸다', async () => {
    expect(await urlFor('http://localhost:8000')).toBe('http://localhost:8000/cases')
  })

  /**
   * 못 쓰는 토큰을 그대로 들고 있으면 다음 요청도 똑같이 막히고,
   * 화면은 로그인한 것처럼 보이면서 아무것도 되지 않는다.
   */
  it('401이면 토큰을 지우고 UnauthorizedError 를 던진다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch(new Response(null, { status: 401 }))

    await expect(request('/cases')).rejects.toBeInstanceOf(UnauthorizedError)
    expect(getAccessToken()).toBeNull()
  })

  it('다른 실패 응답은 상태 코드를 담아 던진다', async () => {
    mockFetch(new Response(null, { status: 409 }))

    await expect(request('/cases', { method: 'POST' })).rejects.toMatchObject({ status: 409 })
  })

  /**
   * 서버가 답을 아예 주지 않으면 그 요청은 영영 끝나지 않는다. 그러면 끝나기를 기다리는
   * 쪽의 뒷정리도 같이 멈춰서, 자동 조회도 다시 확인 버튼도 막힌 채 화면이 굳는다.
   *
   * `AbortSignal.timeout()` 을 쓰지 않는 것은 가짜 타이머가 그것까지 바꾸지 못해서다.
   * 런타임 내부 타이머라 가짜 시간이 흘러도 안 터지고, 테스트가 실제로 15초를 기다리게 된다.
   */
  describe('제한 시간', () => {
    /** 응답을 주지 않다가, 요청이 취소되면 그 이유로 거부한다 — 실제 `fetch` 와 같다 */
    function hangingFetch() {
      const fetchMock = vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => reject(init.signal?.reason))
          }),
      )
      vi.stubGlobal('fetch', fetchMock)
      return fetchMock
    }

    afterEach(() => {
      vi.useRealTimers()
    })

    it('답이 오지 않으면 끊는다', async () => {
      vi.useFakeTimers()
      hangingFetch()

      const pending = request('/cases')
      const settled = expect(pending).rejects.toBeInstanceOf(TimeoutError)
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)

      await settled
    })

    /**
     * 응답을 받았다고 끝난 것이 아니다. 본문은 호출부가 나중에 읽는데, 여기서 타이머를
     * 지워버리면 **헤더만 오고 본문이 멈추는 경우**를 아무도 못 막는다.
     *
     * 본문이 멈추는 상황 자체는 가짜 `fetch` 로 재현할 수 없다 — 실제 `fetch` 는 본문
     * 스트림을 내부에서 `signal` 에 묶지만, 우리가 만든 `Response` 는 그 `signal` 과 아무
     * 관계가 없다. 그래서 **우리 코드가 타이머를 살려뒀는지**만 본다.
     */
    it('응답을 받은 뒤에도 제한 시간이 살아 있다', async () => {
      vi.useFakeTimers()
      const fetchMock = mockFetch(jsonResponse({}))

      await request('/cases')
      const { init } = calledWith(fetchMock)
      expect(init.signal?.aborted).toBe(false)

      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)

      expect(init.signal?.aborted).toBe(true)
    })
  })
})

describe('postLogin', () => {
  it('토큰은 헤더에서, 닉네임은 본문에서 꺼낸다', async () => {
    const state = createOAuthState()
    mockFetch(
      jsonResponse(
        { nickname: '김사장' },
        { headers: { 'Access-Token': 'access-1', 'Refresh-Token': 'refresh-1' } },
      ),
    )

    await expect(postLogin('code-1', state)).resolves.toEqual({
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      nickname: '김사장',
    })
  })

  /**
   * 서버에 `Access-Control-Expose-Headers` 설정이 없거나 중간 프록시가 헤더를 지우면
   * 응답은 200인데 토큰만 비어 온다. 성공으로 넘기면 로그인한 것처럼 보이다가
   * 다음 요청에서 401이 나서, 원인이 두 단계 떨어진 곳에 생긴다.
   */
  it('토큰 헤더가 없으면 성공으로 보지 않는다', async () => {
    const state = createOAuthState()
    mockFetch(jsonResponse({ nickname: '김사장' }))

    await expect(postLogin('code-1', state)).rejects.toBeInstanceOf(ApiError)
  })

  /**
   * 우리가 시작하지 않은 로그인이다. 서버를 부르고 나서 막으면 늦다 — 그 사이에
   * 공격자의 `code` 가 이미 토큰으로 바뀐다. 요청이 아예 나가지 않아야 한다.
   */
  it('state 가 어긋나면 서버를 부르지 않는다', async () => {
    createOAuthState()
    const fetchMock = mockFetch(jsonResponse({ nickname: '김사장' }))

    await expect(postLogin('code-1', '꾸며낸-값')).rejects.toBeInstanceOf(ApiError)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
