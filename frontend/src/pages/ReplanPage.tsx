import { useEffect, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'

import { toSubmitOutcome } from '../adapters/results'
import { AppShell } from '../components/AppShell'
import { BlockerCard } from '../components/BlockerCard'
import { ChangeList } from '../components/ChangeList'
import { NextActionCard } from '../components/NextActionCard'
import { NoBlockerCard } from '../components/NoBlockerCard'
import { NoticeCard } from '../components/NoticeCard'
import { HammerLoader } from '../components/ui/HammerLoader'
import { ApiError, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { MOCK_SWITCH_ENABLED, readMockKey } from '../lib/mockSwitch'
import { fetchResultStatus } from '../lib/resultSubmit'
import { noChangeReplan, updatedReplan } from '../mocks/resultFlow'
import type { ReplanView } from '../types/view'

const MOCKS: Record<string, ReplanView> = {
  'no-change': noChangeReplan,
}

/** 서버에 물은 결과 */
type ReplanQuery =
  | { status: 'LOADING' }
  | { status: 'READY'; view: ReplanView }
  /** 이 결과 뒤로 새 판단이 생겼다(409). 지난 결과를 지금 것처럼 보여주지 않는다 */
  | { status: 'SUPERSEDED' }
  | { status: 'LOAD_FAILED' }

/**
 * 주소의 판단 번호. 숫자 글자로만 된 양의 정수가 아니면 `null`.
 *
 * `Number()` 는 `''`·`'1e3'`·`' 12 '` 도 숫자로 바꿔 주므로 글자부터 본다.
 */
function parseHistoryId(search: string): number | null {
  const raw = new URLSearchParams(search).get('history')
  if (raw === null || !/^\d+$/.test(raw)) return null
  const id = Number(raw)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

/**
 * ⑤ 반영 결과.
 *
 * **주소의 판단 번호(`?history=`)로 서버에 다시 묻는다.** 앞 화면이 넘겨준 결과를 그대로 그리면
 * 라우터 state 가 히스토리에 남아, 루프를 더 돈 뒤 뒤로 가기·새로고침을 했을 때 지난 판단이
 * "지금 할 일"이라는 얼굴로 다시 뜬다. 판단 번호로 물으면 서버가 그 뒤로 새 판단이 생겼는지
 * 알려준다(409).
 *
 * 반영된 결과(`UPDATED`·`NO_CHANGE`)만 그린다. 아직 판단 중이거나 다른 결과면 이 화면이 보여줄
 * 것이 아니라 지금 상황(`/case`)으로 보낸다.
 *
 * Mock 은 물을 서버가 없어 앞 화면이 넘겨준 결과나 `?mock=` 으로 그린다.
 */
export function ReplanPage() {
  const { search, state } = useLocation()
  const usesMock = usesMockData(search)

  if (usesMock) {
    const fallback = Object.hasOwn(MOCKS, readMockKey(search))
      ? MOCKS[readMockKey(search)]
      : MOCK_SWITCH_ENABLED
        ? updatedReplan
        : null
    const view = (state as ReplanView | null) ?? fallback
    if (!view) return <Navigate to={{ pathname: '/', search }} replace />
    return <Replanned view={view} search={search} />
  }

  const historyId = parseHistoryId(search)
  // 번호가 없거나 이상하면 물어볼 것이 없다. 요청을 보내지 않고 지금 상황으로 보낸다
  if (historyId === null) return <Navigate to="/case" replace />
  // 번호가 바뀌면 새로 그린다. 앞 번호의 결과가 잠깐이라도 남아 보이지 않게 한다
  return <ServerReplan key={historyId} historyId={historyId} />
}

function ServerReplan({ historyId }: { historyId: number }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState<ReplanQuery>({ status: 'LOADING' })
  /** 다시 불러오기를 누를 때마다 올려 조회를 다시 돌린다 */
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    // 떠났거나 번호가 바뀐 뒤 늦게 온 응답은 버린다
    let current = true

    fetchResultStatus(historyId).then(
      (body) => {
        if (!current) return
        const outcome = toSubmitOutcome(body)
        // 판단 중·되물음·충돌·실패·읽지 못함은 이 화면이 보여줄 것이 아니다
        if (outcome.kind !== 'REPLAN') return navigate('/case', { replace: true })
        setQuery({ status: 'READY', view: outcome.view })
      },
      (error: unknown) => {
        if (!current) return
        if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })
        if (error instanceof ApiError && error.status === 409) return setQuery({ status: 'SUPERSEDED' })
        // 그 번호의 기록이 없다
        if (error instanceof ApiError && error.status === 404) return navigate('/case', { replace: true })
        setQuery({ status: 'LOAD_FAILED' })
      },
    )

    return () => {
      current = false
    }
  }, [historyId, attempt, navigate])

  switch (query.status) {
    case 'LOADING':
      return (
        <AppShell title="다시 계산했습니다">
          <div className="flex justify-center py-10">
            <HammerLoader size={48} label="반영 결과를 불러오는 중" />
          </div>
        </AppShell>
      )

    case 'SUPERSEDED':
      return (
        <AppShell title="다시 계산했습니다">
          <NoticeCard
            tone="NEUTRAL"
            title="이 결과 뒤로 새 판단이 나왔어요."
            description="지금 상황에서 최신 할 일을 확인해 주세요."
            action={{ label: '지금 상황 보기', onClick: () => navigate('/case') }}
          />
        </AppShell>
      )

    case 'LOAD_FAILED':
      return (
        <AppShell title="다시 계산했습니다">
          <NoticeCard
            tone="NEUTRAL"
            title="반영 결과를 불러오지 못했어요."
            description="연결 상태를 확인하고 다시 불러와 주세요."
            action={{ label: '다시 불러오기', onClick: () => {
                setQuery({ status: 'LOADING' })
                setAttempt((count) => count + 1)
              }, }}
          />
        </AppShell>
      )

    case 'READY':
      return <Replanned view={query.view} search="" />
  }
}

/** 반영된 결과. 모양은 다음 커밋에서 새 시안으로 바꾼다 */
function Replanned({ view, search }: { view: ReplanView; search: string }) {
  const { changes, blocker, nextAction } = view

  return (
    <AppShell title="다시 계산했습니다" subtitle="바뀐 내용에 맞춰 다음 할 일을 정했어요">
      {changes.length > 0 ? (
        <ChangeList changes={changes} />
      ) : (
        <NoticeCard
          tone="NEUTRAL"
          title="바뀐 것이 없습니다."
          description="기록된 내용이 그대로라 다음 할 일도 달라지지 않았어요."
        />
      )}

      {nextAction ? (
        <NextActionCard nextAction={nextAction} />
      ) : (
        <NoticeCard
          tone="NEUTRAL"
          title="다음 할 일을 정하려면 확인이 더 필요합니다."
          description="현재 상황에서 어떤 항목이 비어 있는지 확인해 주세요."
        />
      )}

      {blocker && <BlockerCard blocker={blocker} />}
      {nextAction && !blocker && <NoBlockerCard />}

      <Link
        to={{ pathname: '/case', search }}
        className="flex min-h-13 items-center justify-center rounded-xl border border-gray-300 bg-white text-base font-bold text-gray-900"
      >
        현재 상황 보기
      </Link>
    </AppShell>
  )
}
