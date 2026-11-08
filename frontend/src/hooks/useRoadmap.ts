import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { toRoadmapView } from '../adapters/roadmap'
import { ApiError, request, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import { mockRoadmap, mockUnsupportedRoadmap } from '../mocks/roadmap'
import type { RoadmapResponse } from '../types/api'
import type { RoadmapView } from '../types/view'

/** 로드맵을 불러온 상태 */
export type RoadmapQuery =
  | { status: 'LOADING' }
  | { status: 'READY'; view: RoadmapView }
  /** 아직 Case 를 만들지 않은 사용자(404). 상황 진단으로 보낸다 */
  | { status: 'EMPTY' }
  /** 연결이 끊겼거나 서버가 답을 못 했거나, 받은 모양을 읽지 못했다 */
  | { status: 'LOAD_FAILED' }

/**
 * 로드맵 조회(`GET /cases/roadmap`, #178). 로드맵 화면 · 할 일 화면 · 홈 단계 카드가 같이 쓴다.
 *
 * 들어올 때 한 번 묻는다(기록 조회 `useLogs` 와 같은 방식). 할 일 상태는 사장님이 체크하거나 판단이
 * 끝나야 바뀌어서, 홈처럼 계속 다시 묻지 않는다 — 할 일 화면에서 체크하고 돌아오면 다시 들어오며 새로 묻는다.
 * 서버 값을 전역에 들고 있지 않는다(프론트 규칙: 서버 데이터는 서버에 다시 묻는다).
 *
 * 401 은 로그인으로 보낸다. 404 는 Case 가 없다는 것이라 `EMPTY` 다.
 *
 * Mock(`?mock=`)으로 볼 때는 서버를 부르지 않고 예시 로드맵을, `?mock=roadmap-unsupported` 면 미지원 업종을 준다.
 */
export function useRoadmap(): { query: RoadmapQuery; reload: () => void } {
  const { search } = useLocation()
  const navigate = useNavigate()
  const usesMock = usesMockData(search)
  const mockKey = readMockKey(search)
  const [query, setQuery] = useState<RoadmapQuery>({ status: 'LOADING' })
  /** 다시 불러오기를 누를 때마다 올려 조회를 다시 돌린다 */
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (usesMock) return

    // 떠난 뒤 늦게 온 응답은 버린다
    let current = true
    request('/cases/roadmap')
      // 본문이 JSON 이 아니면 여기서 실패하고, 아래 실패 쪽으로 간다
      .then((response) => response.json() as Promise<RoadmapResponse | null>)
      .then(
        (body) => {
          const view = toRoadmapView(body)
          if (!current) return
          setQuery(view === null ? { status: 'LOAD_FAILED' } : { status: 'READY', view })
        },
        (error: unknown) => {
          if (!current) return
          if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })
          if (error instanceof ApiError && error.status === 404) return setQuery({ status: 'EMPTY' })
          setQuery({ status: 'LOAD_FAILED' })
        },
      )

    return () => {
      current = false
    }
  }, [usesMock, attempt, navigate])

  const reload = useCallback(() => {
    setQuery({ status: 'LOADING' })
    setAttempt((count) => count + 1)
  }, [])

  if (usesMock) {
    return { query: { status: 'READY', view: mockKey === 'roadmap-unsupported' ? mockUnsupportedRoadmap : mockRoadmap }, reload }
  }
  return { query, reload }
}
