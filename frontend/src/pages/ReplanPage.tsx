import { Link, Navigate, useLocation } from 'react-router'

import { AppShell } from '../components/AppShell'
import { BlockerCard } from '../components/BlockerCard'
import { ChangeList } from '../components/ChangeList'
import { NextActionCard } from '../components/NextActionCard'
import { NoBlockerCard } from '../components/NoBlockerCard'
import { NoticeCard } from '../components/NoticeCard'
import { MOCK_SWITCH_ENABLED, readMockKey } from '../lib/mockSwitch'
import { noChangeReplan, updatedReplan } from '../mocks/resultFlow'
import type { ReplanView } from '../types/view'

const MOCKS: Record<string, ReplanView> = {
  'no-change': noChangeReplan,
}

/**
 * ⑤ 재계획 결과.
 *
 * ③에서 라우터 state로 결과를 받는다. URL에 담지 않는 것은 변경 내역과 판단이
 * 전부 주소창에 드러나기 때문이다.
 *
 * 대신 주소만으로는 열 수 없다. 개발·Preview에서는 Mock으로 그려 링크 확인이
 * 가능하게 하고, 그 외에는 ②로 보낸다.
 *
 * TODO(API): 연동 후에는 state가 없을 때 `GET /cases/{caseId}`로 현재 판단을
 * 다시 불러오는 편이 나을 수 있다. 새로고침해도 화면이 유지된다.
 */
export function ReplanPage() {
  const { search, state } = useLocation()

  const mockKey = readMockKey(search)
  const fallback = Object.hasOwn(MOCKS, mockKey)
    ? MOCKS[mockKey]
    : MOCK_SWITCH_ENABLED
      ? updatedReplan
      : null
  const view = (state as ReplanView | null) ?? fallback

  if (!view) return <Navigate to="/" replace />

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
        to={{ pathname: '/', search }}
        className="flex min-h-13 items-center justify-center rounded-xl border border-gray-300 bg-white text-base font-bold text-gray-900"
      >
        현재 상황 보기
      </Link>
    </AppShell>
  )
}
