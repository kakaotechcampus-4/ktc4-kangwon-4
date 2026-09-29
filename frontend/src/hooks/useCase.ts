import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { toCurrentCaseView } from '../adapters/case'
import { request, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import { insufficientCase, noBlockerCase, normalCase } from '../mocks/currentCase'
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
 * **오래된 Case 가 "지금 상황"이라는 얼굴로 다시 뜨기** 때문이다. 이 화면들은 Case 가
 * Source of Truth 라는 원칙 위에 서 있다.
 */
export type CaseQuery =
  /** 아직 서버 답을 기다리는 중 */
  | { status: 'LOADING' }
  /** 아직 Case 를 만들지 않은 사용자 */
  | { status: 'EMPTY' }
  | { status: 'READY'; view: CurrentCaseView }
  /** 서버를 부르지 못했다. 인증 실패는 여기 오지 않고 로그인 화면으로 보낸다 */
  | { status: 'FAILED' }

/** `?mock=` 으로 불러낼 수 있는 화면들 */
const MOCKS: Record<string, CurrentCaseView> = {
  'no-blocker': noBlockerCase,
  insufficient: insufficientCase,
}

function mockQuery(mockKey: string): CaseQuery {
  if (mockKey === 'no-case') return { status: 'EMPTY' }

  return {
    status: 'READY',
    view: Object.hasOwn(MOCKS, mockKey) ? MOCKS[mockKey] : normalCase,
  }
}

export function useCase(): CaseQuery {
  const { search } = useLocation()
  const navigate = useNavigate()
  const [fetched, setFetched] = useState<CaseQuery>({ status: 'LOADING' })

  const mockKey = readMockKey(search)

  // 가짜 토큰으로 서버를 부르면 곧바로 401 이라, 그 경우에는 아예 부르지 않는다
  const usesMock = usesMockData(search)

  /** 응답을 기다리는 사이 화면을 떠날 수 있다. 떠난 화면의 상태를 바꾸지 않는다 */
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    if (usesMock) return

    request('/cases')
      .then((response) => response.json() as Promise<CasesEnvelope>)
      .then((body) => {
        if (!alive.current) return
        // 서버가 아직 봉투를 안 보내는 동안에도 화면이 깨지지 않게 둔다
        const serverCase = body.case ?? null
        setFetched(
          serverCase === null
            ? { status: 'EMPTY' }
            : { status: 'READY', view: toCurrentCaseView(serverCase) },
        )
      })
      .catch((error: unknown) => {
        if (!alive.current) return
        // 못 쓰는 토큰을 들고 화면에 머물면 아무것도 되지 않는다
        if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })
        setFetched({ status: 'FAILED' })
      })

    return () => {
      alive.current = false
    }
  }, [usesMock, navigate])

  return usesMock ? mockQuery(mockKey) : fetched
}
