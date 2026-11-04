import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { toLogEntries } from '../adapters/logs'
import { ApiError, request, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import { mockLogEntries } from '../mocks/logs'
import type { CaseLogResponse } from '../types/api'
import type { LogEntry } from '../types/view'

/** 기록을 불러온 상태 */
export type LogsQuery =
  | { status: 'LOADING' }
  /** 불러왔다. Case 가 없어 기록이 없으면(404) 빈 목록이다 */
  | { status: 'READY'; entries: LogEntry[] }
  /** 연결이 끊겼거나 서버가 답을 못 했거나, 받은 모양을 읽지 못했다 */
  | { status: 'LOAD_FAILED' }

/**
 * 기록 조회(`GET /cases/logs`). 기록 탭과 홈 띠가 같이 쓴다.
 *
 * 들어올 때 한 번 묻는다. 기록은 사장님이 무엇을 하거나 판단이 끝나야 늘어서, 홈처럼
 * 판단 중에 계속 다시 묻지 않는다 — 다른 화면에 다녀오면 다시 들어오며 새로 묻는다.
 *
 * Case 가 없으면 404 다. 기록이 없는 것과 같아서 빈 목록으로 둔다. 401 은 로그인으로 보낸다.
 *
 * Mock(`?mock=`)으로 볼 때는 서버를 부르지 않고 예시 기록을, `?mock=logs-empty` 면 빈 목록을 준다.
 */
export function useLogs(): { query: LogsQuery; reload: () => void } {
  const { search } = useLocation()
  const navigate = useNavigate()
  const usesMock = usesMockData(search)
  const mockKey = readMockKey(search)
  const [query, setQuery] = useState<LogsQuery>({ status: 'LOADING' })
  /** 다시 불러오기를 누를 때마다 올려 조회를 다시 돌린다 */
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (usesMock) return

    // 떠난 뒤 늦게 온 응답은 버린다
    let current = true
    request('/cases/logs')
      // 본문이 JSON 이 아니면 여기서 실패하고, 아래 실패 쪽으로 간다
      .then((response) => response.json() as Promise<CaseLogResponse | null>)
      .then(
      (body) => {
        const entries = toLogEntries(body)
        if (!current) return
        setQuery(entries === null ? { status: 'LOAD_FAILED' } : { status: 'READY', entries })
      },
      (error: unknown) => {
        if (!current) return
        if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })
        if (error instanceof ApiError && error.status === 404) return setQuery({ status: 'READY', entries: [] })
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

  if (usesMock) return { query: { status: 'READY', entries: mockKey === 'logs-empty' ? [] : mockLogEntries }, reload }
  return { query, reload }
}
