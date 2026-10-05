import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { toCurrentCaseView } from '../adapters/case'
import { request, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import {
  doneCase,
  judgmentFailedCase,
  moreInfoCase,
  pendingCase,
  unrecognizedCase,
} from '../mocks/currentCase'
import type { CasesEnvelope } from '../types/api'
import type { CurrentCaseView } from '../types/view'

/**
 * 지금 Case 를 서버에 물어본다.
 *
 * 진입 분기(`/`)·시작 화면(`/start`)·현재 Case(`/case`) 가 같은 것을 알아야 해서
 * 한곳에 모았다. 각 화면이 각자 부르되, 부르는 방법은 하나다 — 인증 실패 처리나
 * Mock 전환을 화면마다 적으면 한 곳쯤 달라진다.
 *
 * 라우터 state 로 넘겨받지 않고 화면마다 다시 묻는 것은, 넘겨받은 값이 히스토리에 남아
 * **오래된 Case 가 "지금 상황"이라는 얼굴로 다시 뜨기** 때문이다.
 *
 * **조회와 판단은 다른 축이다.** 서버를 잘 불렀어도 판단은 아직 안 끝날 수 있다.
 * 여기 `CaseQuery` 는 조회만 말하고, 판단 상태는 `view.judgment` 안에 있다.
 */
export type CaseQuery =
  /** 아직 서버 답을 한 번도 받지 못했다 */
  | { status: 'LOADING' }
  /** 아직 Case 를 만들지 않은 사용자 */
  | { status: 'EMPTY' }
  /**
   * 받아둔 Case 가 있다.
   *
   * `stale` 은 **다시 물어봤는데 실패한** 상태다. 화면은 마지막으로 받은 내용을 그대로
   * 보여주되, 이 값이 지금 것이 아닐 수 있다고 알리고 결과 제출 같은 동작은 막는다.
   */
  | { status: 'READY'; view: CurrentCaseView; stale: boolean }
  /** 한 번도 못 받았다. 인증 실패는 여기 오지 않고 로그인 화면으로 보낸다 */
  | { status: 'LOAD_FAILED' }

export interface CaseQueryResult {
  query: CaseQuery
  /** 사장님이 직접 누르는 재조회 */
  refresh: () => void
  /** 조회가 나가 있는 동안. 버튼을 잠그는 데 쓴다 */
  refreshing: boolean
  /**
   * 판단을 기다린 지 상한을 넘겼다. 자동으로 다시 묻는 것은 멈춘 상태다.
   *
   * 화면은 "곧 됩니다" 가 아니라 오래 걸리고 있다고 알려야 한다 — 끝나지 않을 수도 있다.
   */
  waitedTooLong: boolean
}

/**
 * 서버가 답은 했는데 모양이 계약과 다르다.
 *
 * 네트워크 실패와 같은 자리로 흘려보낸다 — 사장님이 할 수 있는 일이 "잠시 후 다시" 로
 * 같고, 받아둔 가게 정보를 지키는 것도 같다.
 */
class MalformedResponseError extends Error {}

/**
 * 판단이 끝날 때까지 다시 물어보는 간격.
 *
 * AI 판단은 실측 36~120초다(BE #47). 1초마다 묻는 것은 근거가 없고, 1분마다 묻는 것은
 * 다 끝난 화면을 오래 들고 있게 된다.
 */
const POLL_INTERVAL_MS = 10_000

/**
 * 판단이 끝나기를 기다리는 상한. 넘기면 자동으로 묻는 것을 멈춘다.
 *
 * 판단은 길어도 7분이면 끝난다(#52). 그보다 짧게 끊으면 정상인데 실패처럼 보여서
 * 넉넉히 둔다. 그래도 상한이 필요한 것은 **끝나지 않는 경우가 있기 때문이다** —
 * 판단 도중 서버가 다시 뜨면 그 Case 는 계속 `PENDING` 으로 남는다(#40).
 * 그때 상한이 없으면 화면은 한 시간에 360번을 묻고도 그대로다.
 */
const POLL_TIMEOUT_MS = 10 * 60 * 1000

/** `?mock=` 으로 불러낼 수 있는 화면들 */
const MOCKS: Record<string, CurrentCaseView> = {
  pending: pendingCase,
  'pending-long': pendingCase,
  'more-info': moreInfoCase,
  'judgment-failed': judgmentFailedCase,
  unrecognized: unrecognizedCase,
}

function mockQuery(mockKey: string): CaseQuery {
  if (mockKey === 'no-case') return { status: 'EMPTY' }

  return {
    status: 'READY',
    view: Object.hasOwn(MOCKS, mockKey) ? MOCKS[mockKey] : doneCase,
    stale: false,
  }
}

export function useCase(): CaseQueryResult {
  const { search } = useLocation()
  const navigate = useNavigate()
  const [fetched, setFetched] = useState<CaseQuery>({ status: 'LOADING' })
  const [refreshing, setRefreshing] = useState(false)
  const [visible, setVisible] = useState(() => !document.hidden)
  const [waitedTooLong, setWaitedTooLong] = useState(false)

  const mockKey = readMockKey(search)
  // 가짜 토큰으로 서버를 부르면 곧바로 401 이라, 그 경우에는 아예 부르지 않는다
  const usesMock = usesMockData(search)

  /**
   * 이 세대의 응답만 받아들인다.
   *
   * 화면을 떠나면 올려서, 흘러가 있던 요청이 돌아와도 버린다. 떠난 화면의 상태를 바꾸면
   * 뒤로 간 사용자가 몇 초 뒤에 이전 화면으로 끌려간다.
   */
  const generation = useRef(0)

  /** 수동 조회와 자동 조회가 겹치지 않게 한다 */
  const inFlight = useRef(false)

  /** 판단을 기다리기 시작한 때. 판단 중이 아니면 `null` */
  const pendingSince = useRef<number | null>(null)

  /** 탭을 떠나 있다 돌아왔는지. 그때는 다음 간격을 기다리지 않는다 */
  const resumed = useRef(false)

  /** Mock 을 보고 있다 실제 조회로 돌아왔는지. 들고 있던 값이 그 사이 낡는다 */
  const leftMock = useRef(false)

  const load = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    setRefreshing(true)

    const mine = generation.current

    try {
      const response = await request('/cases')
      const body = (await response.json()) as CasesEnvelope
      if (mine !== generation.current) return

      // Case 가 없다는 뜻은 **`case: null`** 하나다. 칸이 통째로 빠진 응답을 "없음" 으로
      // 읽으면, Case 를 가진 사장님이 갱신 한 번에 시작 화면으로 끌려가 **자기 정보가
      // 사라진 줄 안다.** 그건 조회가 잘못된 것이니 받아둔 것을 지키고 실패로 둔다.
      if (body.case === undefined) throw new MalformedResponseError()

      setFetched(
        body.case === null
          ? { status: 'EMPTY' }
          : { status: 'READY', view: toCurrentCaseView(body, body.case), stale: false },
      )
    } catch (error: unknown) {
      if (mine !== generation.current) return

      // 못 쓰는 토큰을 들고 화면에 머물면 아무것도 되지 않는다
      if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })

      // 한 번이라도 받아둔 것이 있으면 지우지 않는다. 가게 정보까지 사라지면
      // 사장님은 적어낸 내용이 날아간 줄 안다
      setFetched((current) =>
        current.status === 'READY' ? { ...current, stale: true } : { status: 'LOAD_FAILED' },
      )
    } finally {
      // `refreshing` 은 세대를 따지지 않고 내린다. 요청 중에 Mock 으로 바뀌면 이 조회는
      // 버려지는데, 그때 켜둔 채로 두면 돌아왔을 때 모든 버튼이 잠긴 채로 남는다
      if (mine === generation.current) inFlight.current = false
      setRefreshing(false)
    }
  }, [navigate])

  useEffect(() => {
    // 화면을 떠나거나 Mock 으로 바뀌면 흘러가 있던 요청을 버린다
    return () => {
      generation.current += 1
      inFlight.current = false
      // 이 정리가 `usesMock` 이 참인 채로 돌았다면 Mock 을 벗어나는 참이다.
      // 그동안 서버 쪽이 달라졌을 수 있어 돌아가면 다시 묻는다
      if (usesMock) leftMock.current = true
    }
  }, [usesMock])

  useEffect(() => {
    function handleVisibilityChange() {
      if (document.hidden) {
        setVisible(false)
        return
      }
      resumed.current = true
      setVisible(true)
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  /**
   * 언제 다시 물어볼지를 한곳에서 정한다.
   *
   * 처음 들어온 것도 여기서 부른다. 조회를 시작하는 자리가 둘로 나뉘면 "지금 요청이
   * 나가 있나"를 양쪽이 따로 따져야 한다.
   *
   * 부르는 것은 타이머에 맡긴다. effect 안에서 곧바로 부르면 그 안의 `setState` 가
   * 렌더를 연쇄시킨다.
   */
  useEffect(() => {
    // 보이지 않는 탭에서는 예약하지 않는다. 사장님이 보고 있지 않은 화면을 위해
    // 서버를 계속 부를 이유가 없다
    if (usesMock || !visible) return

    const judging = fetched.status === 'READY' && fetched.view.judgment.status === 'PENDING'
    const refreshFailed = fetched.status === 'READY' && fetched.stale

    // 기다리기 시작한 때를 기억한다. 판단 중이 아니게 되면 잊는다 — 다음에 또 `PENDING`
    // 이 되면 거기서 다시 센다. 이어서 세면 한 번 오래 걸린 Case 가 그 뒤로 영영
    // 상한을 넘긴 것으로 남는다
    if (!judging) pendingSince.current = null
    else if (pendingSince.current === null) pendingSince.current = Date.now()

    const timedOut =
      judging && pendingSince.current !== null && Date.now() - pendingSince.current >= POLL_TIMEOUT_MS

    if (timedOut !== waitedTooLong) setWaitedTooLong(timedOut)

    /** 다음 조회까지 기다릴 시간. `null` 이면 묻지 않는다 */
    function nextDelay(): number | null {
      if (fetched.status === 'LOADING' || leftMock.current) return 0

      // 탭에서 막 돌아왔다. 숨어 있는 사이 판단이 끝났을 수 있고, 갱신에 실패해
      // 멈춰 있던 화면도 여기서 회복할 기회를 얻는다
      if (resumed.current) return judging || refreshFailed ? 0 : null

      // 갱신이 한 번 실패한 뒤에는 저절로 반복하지 않는다. 서버가 멎어 있으면 10초마다
      // 같은 실패를 쌓을 뿐이라, 사장님이 직접 누를 때까지 기다린다
      if (refreshFailed) return null

      // 상한을 넘기면 저절로 묻지 않는다. 사장님이 직접 누르는 길은 남겨 둔다 —
      // 그사이 판단이 끝났을 수도 있다
      if (timedOut) return null

      return judging ? POLL_INTERVAL_MS : null
    }

    const delay = nextDelay()
    resumed.current = false
    leftMock.current = false
    if (delay === null) return

    const timer = window.setTimeout(() => void load(), delay)
    return () => window.clearTimeout(timer)
  }, [fetched, usesMock, visible, load, waitedTooLong])

  const refresh = useCallback(() => void load(), [load])

  if (usesMock) {
    // 서버를 안 부르니 다시 부를 것도 없다. 오래 기다린 화면은 `?mock=pending-long` 으로 본다
    return {
      query: mockQuery(mockKey),
      refresh: () => {},
      refreshing: false,
      waitedTooLong: mockKey === 'pending-long',
    }
  }

  return { query: fetched, refresh, refreshing, waitedTooLong }
}
