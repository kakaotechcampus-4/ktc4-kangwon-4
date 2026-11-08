import { useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router'

import { announceLogsChanged } from '../hooks/useLogs'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import { fetchResultsEntry, waitForResult } from '../lib/resultSubmit'
import type { ResultsSubmitResult } from '../types/api'
import { Toast } from './ui/Toast'

/**
 * 판단을 스스로 기다리는 화면. 여기서는 쉰다 — 같은 판단을 두 번 묻게 된다.
 * `/` 와 `/cases/new` 는 아직 판단이 없는 자리다.
 */
const QUIET_PATHS = new Set(['/', '/cases/new', '/case', '/results', '/confirm'])

/** 끝난 판단에서 띠에 필요한 것 */
interface Finished {
  result: Exclude<ResultsSubmitResult, 'PENDING'>
  historyId: number
}

/** 결과마다 띠 문구와 버튼. 반영된 결과는 그 판단 번호로 결과 화면을 다시 연다(`/replan?history=`) */
function toToast({ result, historyId }: Finished): { message: string; actionLabel: string; to: string } {
  switch (result) {
    case 'UPDATED':
    case 'NO_CHANGE':
      return { message: '리본이 내용을 반영했어요', actionLabel: '보기', to: `/replan?history=${historyId}` }
    case 'NEEDS_MORE_INFO':
      return { message: '더 여쭤볼 게 있어요', actionLabel: '답하러 가기', to: '/case' }
    case 'CONFLICT':
      return { message: '확인이 필요한 내용이 있어요', actionLabel: '확인하러 가기', to: '/case' }
    case 'FAILED':
      return { message: '다음 할 일을 정하지 못했어요', actionLabel: '확인하기', to: '/case' }
  }
}

/**
 * 판단 중인지 보고, 그렇다면 끝날 때까지 기다린다. 판단 중이 아니었거나 끝을 못 봤으면 `null`.
 *
 * **판단 중인 것을 직접 본 경우만 끝났다고 알린다.** 들어왔을 때 이미 끝나 있던 판단은 띠로 알리지
 * 않는다 — 언제 끝났는지 모르는 일을 방금 끝난 것처럼 알리게 된다. 그건 종 버튼의 점이 알린다.
 *
 * 기다리기는 결과 화면과 같은 것(`waitForResult`)을 쓴다. 간격(3초)과 상한(10분)도 같다.
 */
async function watchJudgment(signal: AbortSignal): Promise<Finished | null> {
  const entry = await fetchResultsEntry()
  if (signal.aborted) return null
  if (entry?.judgment_status !== 'PENDING' || entry.case_history_id === null) return null

  const historyId = entry.case_history_id
  const waited = await waitForResult(historyId, { signal })
  if (waited.kind !== 'SETTLED' || waited.body === null || waited.body.result === 'PENDING') return null
  return { result: waited.body.result, historyId }
}

/** `?mock=judgment-finished` 로 볼 때 띠가 뜨기까지 기다리는 시간. 화면이 먼저 그려진 뒤 뜨게 한다 */
const MOCK_DELAY_MS = 2_000

/**
 * 다른 화면에 있을 때 판단이 끝나면 위쪽 띠로 알린다. 로그인한 화면 전부(`RequireAuth`) 아래에 있다.
 *
 * 화면을 옮길 때마다, 그리고 탭으로 돌아올 때마다 판단 중인지 한 번 묻는다. 서류 확인처럼 한 화면에
 * 머문 채 판단이 시작되면 그 화면에서는 알 수 없다 — 서류 응답이 판단 시작을 알려주지 않는다.
 *
 * **실패는 조용히 넘긴다.** 띠는 덧붙인 도움이라, 묻다 실패했다고 화면을 바꾸거나 로그인으로 보내지
 * 않는다. 로그인이 풀린 것은 그 화면이 원래 부르는 요청이 알아채고 보낸다.
 */
export function JudgmentWatcher() {
  const { pathname, search } = useLocation()
  const watching = !QUIET_PATHS.has(pathname)
  const usesMock = usesMockData(search)
  const mockKey = readMockKey(search)
  const [finished, setFinished] = useState<Finished | null>(null)
  /** 탭으로 돌아올 때마다 올려 다시 묻게 한다 */
  const [returned, setReturned] = useState(0)

  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden) setReturned((count) => count + 1)
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [])

  useEffect(() => {
    if (!watching) return

    if (usesMock) {
      if (mockKey !== 'judgment-finished') return
      const timer = window.setTimeout(() => setFinished({ result: 'UPDATED', historyId: 1 }), MOCK_DELAY_MS)
      return () => window.clearTimeout(timer)
    }

    const controller = new AbortController()
    watchJudgment(controller.signal).then(
      (result) => {
        if (result === null || controller.signal.aborted) return
        setFinished(result)
        announceLogsChanged()
      },
      () => {},
    )
    return () => controller.abort()
    // `pathname` 은 안에서 쓰지 않지만 넣어 둔다. 화면을 옮길 때마다 판단 중인지 다시 묻는 것이 목적이다
  }, [watching, pathname, usesMock, mockKey, returned])

  const close = useCallback(() => setFinished(null), [])

  if (!finished) return null
  return <Toast {...toToast(finished)} onClose={close} />
}
