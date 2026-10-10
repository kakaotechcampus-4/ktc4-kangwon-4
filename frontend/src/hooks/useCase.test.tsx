import { act, fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { REQUEST_TIMEOUT_MS } from '../lib/api'
import { logInWithMock, saveTokens } from '../lib/auth'
import type { CaseResponse } from '../types/api'
import { useCase } from './useCase'

const SERVER_CASE: Partial<CaseResponse> = {
  id: 1,
  business_type: '카페',
  franchise_status: false,
  employee_count: 2,
  lease_status: 'LEASED_PAID',
  restoration_scope: 'UNKNOWN',
  demolition_required: 'UNKNOWN',
}

/** 판단 칸이 전부 비어 있는 봉투. 테스트마다 필요한 칸만 덮어쓴다 */
const EMPTY_JUDGMENT = {
  blocker: null,
  next_action: null,
  judgment_status: null,
  questions_for_user: null,
}

function response(body: unknown, status = 200) {
  return new Response(status === 200 ? JSON.stringify(body) : null, { status })
}

function mockFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(response(body, status))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/**
 * 답을 주지 않는 서버. 요청이 취소되면 그 이유로 거부한다 — 실제 `fetch` 와 같다.
 *
 * `mockFetch` 는 `signal` 을 보지 않아서, 취소해도 그 Promise 가 끝나지 않는다.
 */
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

/** 처음엔 받아오고, 그 뒤로는 답을 주지 않는다. 갱신만 멈춘 상태를 만든다 */
function mockThenHang(body: unknown) {
  let called = false
  const fetchMock = vi.fn((_url: string, init: RequestInit) => {
    if (!called) {
      called = true
      return Promise.resolve(response(body))
    }

    return new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(init.signal?.reason))
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** 부를 때마다 다른 답을 주고 싶을 때. 목록이 끝나면 마지막 답을 계속 준다 */
function mockFetchSequence(...responses: (() => Response)[]) {
  let call = 0
  const fetchMock = vi.fn().mockImplementation(() => {
    const make = responses[Math.min(call, responses.length - 1)]
    call += 1
    return Promise.resolve(make())
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const PENDING = { ...EMPTY_JUDGMENT, case: SERVER_CASE, judgment_status: 'PENDING' }
const DONE = {
  ...EMPTY_JUDGMENT,
  case: SERVER_CASE,
  judgment_status: 'DONE',
  blocker: '막힘',
  next_action: '할 일',
}

/**
 * 가짜 시계를 돌리고, 그 사이 끝난 요청과 그에 따른 렌더까지 반영한다.
 *
 * 한 번에 길게 돌리면 안 된다. 조회가 끝나야 다음 조회가 예약되는 구조라,
 * `0` 으로 먼저 첫 조회를 끝낸 뒤 간격만큼 돌려야 실제 흐름과 같아진다.
 */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

/** 탭을 숨기거나 되돌린다. 브라우저가 보내는 것과 같은 신호를 직접 쏜다 */
function setTabHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
}

/** 훅이 돌려준 상태를 글자로 드러내는 최소한의 화면 */
function Probe() {
  const { query, refresh, waitedTooLong } = useCase()

  return (
    <>
      {query.status === 'READY' ? (
        <p>{`READY ${query.view.judgment.status} ${query.view.facts.find((fact) => fact.key === 'business_type')?.value}`}</p>
      ) : (
        <p>{query.status}</p>
      )}
      {query.status === 'READY' && query.stale && <p>최신인지 모름</p>}
      {waitedTooLong && <p>오래 기다림</p>}
      <button type="button" onClick={refresh}>
        다시 묻기
      </button>
    </>
  )
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/case', element: <Probe /> },
      { path: '/login', element: <p>로그인 화면</p> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
  return router
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 세 화면이 이 훅 하나로 Case 를 묻는다. 여기가 틀리면 처음 온 사장님이 빈 현재 Case 를
 * 보거나, 이미 Case 가 있는 사장님이 다시 "시작하기"를 마주한다.
 */
describe('useCase', () => {
  it('서버가 준 Case 를 화면 모양으로 돌려준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch({ ...EMPTY_JUDGMENT, case: SERVER_CASE, judgment_status: 'PENDING' })
    renderAt('/case')

    expect(await screen.findByText('READY PENDING 카페')).toBeInTheDocument()
  })

  it('Case 가 없으면 EMPTY 다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch({ ...EMPTY_JUDGMENT, case: null })
    renderAt('/case')

    expect(await screen.findByText('EMPTY')).toBeInTheDocument()
  })

  /**
   * Case 가 없다는 뜻은 `case: null` 하나다.
   *
   * 칸이 통째로 빠진 응답을 "없음" 으로 읽으면, Case 를 가진 사장님이 갱신 한 번에
   * 시작 화면으로 끌려가 **자기 정보가 사라진 줄 안다.** 서버가 잘못 답한 것이니
   * 조회 실패로 두는 편이 정직하다.
   */
  it('봉투에 case 칸이 없으면 Case 없음이 아니라 조회 실패로 둔다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch({})
    renderAt('/case')

    expect(await screen.findByText('LOAD_FAILED')).toBeInTheDocument()
  })

  /**
   * 못 쓰는 토큰을 들고 화면에 머물면 아무것도 되지 않는다. 화면은 멀쩡한데
   * 누르는 것마다 실패해서, 사용자는 무엇이 잘못됐는지 알 수 없다.
   */
  it('인증이 통하지 않으면 로그인 화면으로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch(null, 401)
    renderAt('/case')

    expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
  })

  it('서버를 부르지 못하면 실패로 둔다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetch(null, 500)
    renderAt('/case')

    expect(await screen.findByText('LOAD_FAILED')).toBeInTheDocument()
  })

  /**
   * Preview 에서는 진짜 카카오 로그인을 할 수 없어 가짜 로그인을 쓴다. 그 토큰으로 서버를
   * 부르면 곧바로 401 이라, 화면을 보러 온 리뷰어가 화면을 못 본다.
   */
  it('가짜 세션이면 서버를 부르지 않는다', async () => {
    logInWithMock()
    const fetchMock = mockFetch({ ...EMPTY_JUDGMENT, case: SERVER_CASE })
    renderAt('/case')

    expect(await screen.findByText(/^READY/)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  /** 리뷰어가 링크 하나로 예외 화면을 보는 길이다. 진짜 세션에서도 살아 있어야 한다 */
  it('?mock= 이 있으면 서버 대신 그 화면을 쓴다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetch({ ...EMPTY_JUDGMENT, case: SERVER_CASE })
    renderAt('/case?mock=no-case')

    expect(await screen.findByText('EMPTY')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

/**
 * `POST /cases` 가 저장만 하고 바로 응답한 뒤 판단은 뒤에서 돈다. 그래서 Case 를 만든
 * 직후에는 반드시 `PENDING` 이고, 여기서 다시 묻지 않으면 **판단이 끝나도 화면은
 * 영원히 "정하고 있어요" 에 머문다.**
 *
 * 사람 손으로는 확인하기 어려운 흐름이라(수십 초를 기다려야 한다) 가짜 타이머로 본다.
 */
describe('useCase 폴링', () => {
  afterEach(() => {
    vi.useRealTimers()
    setTabHidden(false)
  })

  it('판단 중이면 10초 뒤에 다시 묻는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetch(PENDING)
    vi.useFakeTimers()
    renderAt('/case')

    await advance(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    // 9초까지는 묻지 않는다. 더 자주 부르면 서버만 바쁘다
    await advance(9_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await advance(1_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  /**
   * 판단은 길어도 7분이면 끝나지만, 판단 도중 서버가 다시 뜨면 그 Case 는 계속
   * `PENDING` 으로 남는다. 상한이 없으면 화면은 끝나지 않을 답을 영원히 묻는다.
   */
  it('상한을 넘기면 저절로 묻는 것을 멈춘다', async () => {
    saveTokens('access-1', 'refresh-1')
    // 응답 본문은 한 번만 읽을 수 있다. 여러 번 묻는 테스트는 매번 새 응답을 만들어야
    // 하고, 그러지 않으면 두 번째 조회가 실패해 **상한이 아니라 조회 실패로** 멈춘다
    const fetchMock = mockFetchSequence(() => response(PENDING))
    vi.useFakeTimers()
    renderAt('/case')

    await advance(0)
    // 10분 동안은 10초마다 묻는다
    for (let elapsed = 0; elapsed < 10 * 60 * 1000; elapsed += 10_000) await advance(10_000)
    const atLimit = fetchMock.mock.calls.length
    expect(atLimit).toBeGreaterThan(1)

    // 넘긴 뒤로는 시간이 아무리 지나도 늘지 않는다
    await advance(60 * 60 * 1000)
    expect(fetchMock).toHaveBeenCalledTimes(atLimit)
  })

  /** 화면이 "곧 됩니다" 대신 다른 말을 할 수 있어야 한다. 그 신호를 훅이 내준다 */
  it('상한을 넘기면 오래 기다렸다고 알린다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockFetchSequence(() => response(PENDING))
    vi.useFakeTimers()
    renderAt('/case')

    await advance(0)
    expect(screen.queryByText('오래 기다림')).not.toBeInTheDocument()

    for (let elapsed = 0; elapsed < 10 * 60 * 1000; elapsed += 10_000) await advance(10_000)

    expect(screen.getByText('오래 기다림')).toBeInTheDocument()
  })

  /** 자동으로 묻는 것만 멈춘다. 그사이 판단이 끝났을 수도 있어 직접 누르는 길은 남는다 */
  it('상한을 넘겨도 직접 누르면 다시 묻는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetchSequence(() => response(PENDING))
    vi.useFakeTimers()
    renderAt('/case')

    await advance(0)
    for (let elapsed = 0; elapsed < 10 * 60 * 1000; elapsed += 10_000) await advance(10_000)
    const atLimit = fetchMock.mock.calls.length

    await act(async () => {
      screen.getByRole('button', { name: '다시 묻기' }).click()
    })

    expect(fetchMock.mock.calls.length).toBeGreaterThan(atLimit)
  })

  /** 끝난 판단을 계속 물으면 사장님 데이터 요금만 쓴다 */
  it('판단이 끝나면 더 묻지 않는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetchSequence(
      () => response(PENDING),
      () => response(DONE),
    )
    vi.useFakeTimers()
    renderAt('/case')

    await advance(0)
    await advance(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await advance(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('처음부터 판단이 끝나 있으면 한 번만 묻는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetch(DONE)
    vi.useFakeTimers()
    renderAt('/case')

    await advance(0)
    await advance(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  /**
   * 서버가 멎어 있으면 10초마다 같은 실패를 쌓을 뿐이다. 사장님이 직접 누를 때까지 멈춘다.
   * 그 사이에도 마지막으로 받은 가게 정보는 그대로 남아 있어야 한다 — 지우면 사장님은
   * 적어낸 내용이 날아간 줄 안다.
   */
  it('갱신에 실패하면 멈추고 마지막 내용을 남긴다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetchSequence(
      () => response(PENDING),
      () => response(null, 500),
    )
    vi.useFakeTimers()
    renderAt('/case')

    await advance(0)
    await advance(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.getByText(/^READY/)).toBeInTheDocument()

    await advance(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('보이지 않는 탭에서는 묻지 않는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetch(PENDING)
    vi.useFakeTimers()
    renderAt('/case')

    await advance(0)
    act(() => setTabHidden(true))

    await advance(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  /**
   * 리뷰어가 `?mock=` 으로 다른 화면을 보다 쿼리를 지우고 돌아오는 경로다.
   *
   * 들고 있던 값은 Mock 을 보던 동안 낡는다. 그때 판단이 이미 끝나 있으면(`DONE`)
   * 폴링도 예약되지 않아, 서버 상태가 달라져도 **옛 할 일을 계속 보여준다.**
   */
  it('Mock 을 보다 실제 조회로 돌아오면 다시 묻는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetch(DONE)
    vi.useFakeTimers()
    const router = renderAt('/case')

    await advance(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await act(async () => void (await router.navigate('/case?mock=pending')))
    await advance(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await act(async () => void (await router.navigate('/case')))
    await advance(0)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  /**
   * 서버가 답을 아예 주지 않는 경우다. 제한 시간이 없으면 그 요청이 영영 끝나지 않고,
   * 끝나야 풀리는 중복 방지 플래그도 그대로 남는다 — **다음 조회가 아예 나가지 못해서
   * 자동이든 수동이든 화면이 굳는다.** 멘토 리뷰(#70)에서 짚인 자리다.
   */
  describe('답이 오지 않을 때', () => {
    it('한 번도 못 받았으면 조회 실패로 둔다', async () => {
      saveTokens('access-1', 'refresh-1')
      hangingFetch()
      vi.useFakeTimers()
      renderAt('/case')

      await advance(0)
      expect(screen.getByText('LOADING')).toBeInTheDocument()

      await advance(REQUEST_TIMEOUT_MS)
      expect(screen.getByText('LOAD_FAILED')).toBeInTheDocument()
    })

    /** 가게 정보까지 사라지면 사장님은 적어낸 내용이 날아간 줄 안다 */
    it('받아둔 것이 있으면 남기고 최신이 아니라고 둔다', async () => {
      saveTokens('access-1', 'refresh-1')
      mockThenHang(PENDING)
      vi.useFakeTimers()
      renderAt('/case')

      await advance(0)
      await advance(10_000)
      await advance(REQUEST_TIMEOUT_MS)

      expect(screen.getByText('READY PENDING 카페')).toBeInTheDocument()
      expect(screen.getByText('최신인지 모름')).toBeInTheDocument()
    })

    /**
     * **이 PR 이 막는 바로 그 자리다.** 플래그가 안 풀리면 두 번째 요청이 나가지 않아
     * 버튼을 눌러도 아무 일이 없다.
     */
    it('끊긴 뒤에도 다시 물을 수 있다', async () => {
      saveTokens('access-1', 'refresh-1')
      const fetchMock = hangingFetch()
      vi.useFakeTimers()
      renderAt('/case')

      await advance(0)
      await advance(REQUEST_TIMEOUT_MS)
      expect(fetchMock).toHaveBeenCalledTimes(1)

      fireEvent.click(screen.getByRole('button', { name: '다시 묻기' }))
      await advance(0)

      expect(fetchMock).toHaveBeenCalledTimes(2)
    })
  })

  /** 숨어 있는 사이 판단이 끝났을 수 있다. 10초를 더 기다리게 하면 멈춘 것처럼 보인다 */
  it('탭으로 돌아오면 기다리지 않고 한 번 묻는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockFetch(PENDING)
    vi.useFakeTimers()
    renderAt('/case')

    await advance(0)
    act(() => setTabHidden(true))
    await advance(60_000)

    act(() => setTabHidden(false))
    await advance(0)

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
