import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  postLogin,
  request,
  REQUEST_TIMEOUT_MS,
  TimeoutError,
  UnauthorizedError,
} from './api'
import { createOAuthState, getAccessToken, getRefreshToken, logInWithMock, logOut, saveTokens } from './auth'

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

  /** 체크 저장(`PUT`)·서류 빼기(`DELETE`)가 이 길로 간다. 막혀 있으면 화면마다 `fetch`를 따로 부르게 된다 */
  it('PUT·DELETE도 같은 헤더로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetch(jsonResponse({}))

    await request('/cases/checklists/dispose_stock', { method: 'PUT', body: { completed: true } })
    await request('/cases/documents/1', { method: 'DELETE' })

    const [, put] = fetchMock.mock.calls[0] as [string, RequestInit]
    const [, remove] = fetchMock.mock.calls[1] as [string, RequestInit]
    expect(put.method).toBe('PUT')
    expect(JSON.parse(put.body as string)).toEqual({ completed: true })
    expect(new Headers(remove.headers).get('Access-Token')).toBe('access-1')
    expect(remove.method).toBe('DELETE')
  })

  /**
   * 파일은 JSON으로 바꾸면 빈 객체가 된다. `Content-Type`을 직접 적어도 깨진다 —
   * 경계 문자열이 빠져서 서버가 파일을 찾지 못한다
   */
  it('파일 묶음은 그대로 보내고 Content-Type 은 브라우저에 맡긴다', async () => {
    const fetchMock = mockFetch(jsonResponse({}))
    const form = new FormData()
    form.append('file', new Blob(['%PDF']), 'transfer.pdf')

    await request('/cases/documents', { method: 'POST', body: form })

    const { init, headers } = calledWith(fetchMock)
    expect(init.body).toBe(form)
    expect(headers.has('Content-Type')).toBe(false)
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

    /** 서류 올리기는 서버가 다 읽을 때까지 붙잡고 있어 수십 초가 걸린다. 기본값으로 끊으면 매번 실패한다 */
    it('요청마다 제한 시간을 늘릴 수 있다', async () => {
      vi.useFakeTimers()
      hangingFetch()

      const pending = request('/cases/documents', { method: 'POST', timeoutMs: REQUEST_TIMEOUT_MS * 4 })
      let failed = false
      pending.catch(() => {
        failed = true
      })

      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
      expect(failed).toBe(false)

      const settled = expect(pending).rejects.toBeInstanceOf(TimeoutError)
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS * 3)
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

/**
 * 서버의 로그인 토큰은 30분짜리다. 다시 받지 않으면 시연 도중 30분이 지나 첫 요청에서 로그인 화면으로 간다(#212).
 * 서버는 Refresh 토큰을 쓸 때마다 바꾸고 마지막 하나만 기억해서, 다시 받기가 둘 나가면 뒤의 것이 로그아웃시킨다.
 */
describe('request — 로그인 다시 받기', () => {
  const isReissue = (url: string) => url.endsWith('/reissue')
  const renewed = () =>
    new Response(null, { status: 200, headers: { 'Access-Token': 'access-2', 'Refresh-Token': 'refresh-2' } })

  /** 다시 받기는 `reissue` 로, 나머지는 보낸 로그인 토큰이 `access-2` 일 때만 200 이다 */
  function serve(reissue: () => Response | Promise<Response> = renewed) {
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      if (isReissue(url)) return reissue()
      return new Headers(init.headers).get('Access-Token') === 'access-2'
        ? jsonResponse({ ok: true })
        : new Response(null, { status: 401 })
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  const reissueCalls = (fetchMock: ReturnType<typeof serve>) =>
    fetchMock.mock.calls.filter(([url]) => isReissue(url))

  it('만료되면 새 토큰을 받아 저장하고, 같은 요청을 새 토큰으로 한 번 더 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serve()

    const response = await request('/cases/results', { method: 'POST', body: { raw_input: '철거하래요' } })

    expect(response.status).toBe(200)
    expect(getAccessToken()).toBe('access-2')
    expect(getRefreshToken()).toBe('refresh-2')
    const [, reissueInit] = reissueCalls(fetchMock)[0]
    expect(new Headers(reissueInit.headers).get('Refresh-Token')).toBe('refresh-1')
    const [, , retried] = fetchMock.mock.calls
    expect(retried[1].body).toBe(JSON.stringify({ raw_input: '철거하래요' }))
  })

  it('여럿이 동시에 만료돼도 다시 받기는 한 번만 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serve()

    const responses = await Promise.all([request('/cases'), request('/cases/logs'), request('/cases/roadmap')])

    expect(responses.map((response) => response.status)).toEqual([200, 200, 200])
    expect(reissueCalls(fetchMock)).toHaveLength(1)
  })

  it('서버가 다시 받기를 거절하면 로그아웃한다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve(() => new Response(null, { status: 401 }))

    await expect(request('/cases')).rejects.toBeInstanceOf(UnauthorizedError)
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
  })

  /** 서버가 거절한 게 아니라 답을 못 받은 것이다. 지우면 잠깐 끊긴 연결로 로그아웃된다 */
  it('다시 받다가 연결이 끊기면 토큰을 그대로 두고 오류를 올린다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve(() => Promise.reject(new TypeError('Failed to fetch')))

    await expect(request('/cases')).rejects.toBeInstanceOf(TypeError)
    expect(getAccessToken()).toBe('access-1')
    expect(getRefreshToken()).toBe('refresh-1')
  })

  /** 서버는 이미 Refresh 토큰을 바꿨다. 새 값을 못 읽으면 들고 있는 것은 쓸 수 없다 */
  it('다시 받았는데 새 토큰을 읽지 못하면 로그아웃한다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serve(() => new Response(null, { status: 200 }))

    await expect(request('/cases')).rejects.toBeInstanceOf(UnauthorizedError)
    expect(getAccessToken()).toBeNull()
    // 빈 토큰으로 한 번 더 보내 보지 않는다
    expect(fetchMock.mock.calls.filter(([url]) => !isReissue(url))).toHaveLength(1)
  })

  /** 늦게 돌아온 401이다. 그사이 다른 요청이 이미 새로 받았으면, 또 받으면 방금 받은 토큰이 버려진다 */
  it('보낸 사이 다른 요청이 이미 새로 받았으면 또 받지 않고 새 토큰으로 다시 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serve()
    fetchMock.mockImplementationOnce(async () => {
      saveTokens('access-2', 'refresh-2')
      return new Response(null, { status: 401 })
    })

    const response = await request('/cases')

    expect(response.status).toBe(200)
    expect(reissueCalls(fetchMock)).toHaveLength(0)
  })

  it('새 토큰으로 보내도 401이면 더 받지 않고 로그아웃한다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = vi.fn(async (url: string) => (isReissue(url) ? renewed() : new Response(null, { status: 401 })))
    vi.stubGlobal('fetch', fetchMock)

    await expect(request('/cases')).rejects.toBeInstanceOf(UnauthorizedError)
    expect(reissueCalls(fetchMock)).toHaveLength(1)
    expect(getAccessToken()).toBeNull()
  })

  it.each([
    ['가짜 세션', () => logInWithMock()],
    [
      '다시 받을 토큰이 없음',
      () => {
        saveTokens('access-1', 'refresh-1')
        window.sessionStorage.removeItem('reborn:refresh-token')
      },
    ],
  ])('%s 이면 다시 받지 않고 로그아웃한다', async (_name, setUp) => {
    setUp()
    const fetchMock = serve()

    await expect(request('/cases')).rejects.toBeInstanceOf(UnauthorizedError)
    expect(reissueCalls(fetchMock)).toHaveLength(0)
  })

  it('올리던 파일도 새 토큰으로 그대로 다시 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serve()
    const form = new FormData()
    form.append('file', new Blob(['계약서']), 'contract.pdf')

    await request('/cases/documents', { method: 'POST', body: form })

    const sent = fetchMock.mock.calls.filter(([url]) => url.endsWith('/cases/documents'))
    expect(sent).toHaveLength(2)
    expect(sent[1][1].body).toBe(form)
  })

  it.each([
    ['로그아웃', '정상'], ['로그아웃', '거절'], ['로그아웃', '헤더 누락'],
    ['새 세션', '정상'], ['새 세션', '거절'], ['새 세션', '헤더 누락'],
  ])('재발급 중 %s이면 늦은 %s 응답은 현재 세션을 바꾸거나 재전송하지 않는다', async (change, reply) => {
    saveTokens('access-1', 'refresh-1')
    let settle!: (response: Response) => void
    const delayed = new Promise<Response>((resolve) => { settle = resolve })
    const fetchMock = serve(() => delayed)
    const pending = request('/cases')
    await vi.waitFor(() => expect(reissueCalls(fetchMock)).toHaveLength(1))
    if (change === '로그아웃') logOut()
    else saveTokens('new-session-access', 'new-session-refresh')
    settle(reply === '정상' ? renewed() : new Response(null, { status: reply === '거절' ? 401 : 200 }))
    await expect(pending).rejects.toMatchObject({ status: 409 })
    expect(getAccessToken()).toBe(change === '로그아웃' ? null : 'new-session-access')
    expect(getRefreshToken()).toBe(change === '로그아웃' ? null : 'new-session-refresh')
    expect(fetchMock.mock.calls.filter(([url]) => !isReissue(url))).toHaveLength(1)
  })

  it('이전 세션의 재발급이 끝나도 새 세션의 동시 요청은 새 재발급 한 건을 함께 기다린다', async () => {
    saveTokens('access-1', 'refresh-1')
    let finishOld!: (response: Response) => void
    let finishNew!: (response: Response) => void
    const oldResponse = new Promise<Response>((resolve) => { finishOld = resolve })
    const newResponse = new Promise<Response>((resolve) => { finishNew = resolve })
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      const headers = new Headers(init.headers)
      if (isReissue(url)) return headers.get('Refresh-Token') === 'refresh-1' ? oldResponse : newResponse
      return headers.get('Access-Token') === 'new-access-2' ? jsonResponse({ ok: true }) : new Response(null, { status: 401 })
    })
    vi.stubGlobal('fetch', fetchMock)
    const old = request('/cases').catch((error: unknown) => error)
    await vi.waitFor(() => expect(reissueCalls(fetchMock)).toHaveLength(1))
    saveTokens('new-access-1', 'new-refresh-1')
    const first = request('/cases/logs')
    await vi.waitFor(() => expect(reissueCalls(fetchMock)).toHaveLength(2))
    finishOld(renewed())
    expect(await old).toMatchObject({ status: 409 })
    const second = request('/cases/roadmap')
    await vi.waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => !isReissue(url))).toHaveLength(3))
    expect(reissueCalls(fetchMock)).toHaveLength(2)
    finishNew(new Response(null, { status: 200, headers: { 'Access-Token': 'new-access-2', 'Refresh-Token': 'new-refresh-2' } }))
    expect((await Promise.all([first, second])).map((response) => response.status)).toEqual([200, 200])
    expect(getAccessToken()).toBe('new-access-2')
    expect(getRefreshToken()).toBe('new-refresh-2')
  })

  it('재전송한 요청의 늦은 401도 새 세션을 로그아웃시키지 않는다', async () => {
    saveTokens('access-1', 'refresh-1')
    let finish!: (response: Response) => void
    const retry = new Promise<Response>((resolve) => { finish = resolve })
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      if (isReissue(url)) return renewed()
      return new Headers(init.headers).get('Access-Token') === 'access-2' ? retry : new Response(null, { status: 401 })
    })
    vi.stubGlobal('fetch', fetchMock)
    const pending = request('/cases')
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    saveTokens('new-session-access', 'new-session-refresh')
    finish(new Response(null, { status: 401 }))
    await expect(pending).rejects.toMatchObject({ status: 409 })
    expect(getAccessToken()).toBe('new-session-access')
    expect(getRefreshToken()).toBe('new-session-refresh')
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
