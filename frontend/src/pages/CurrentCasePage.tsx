import { useLocation } from 'react-router'

import { AppShell } from '../components/AppShell'
import { BlockerCard } from '../components/BlockerCard'
import { FactList } from '../components/FactList'
import { InsufficientInfoCard } from '../components/InsufficientInfoCard'
import { NextActionCard } from '../components/NextActionCard'
import { NoBlockerCard } from '../components/NoBlockerCard'
import { readMockKey } from '../lib/mockSwitch'
import { insufficientCase, noBlockerCase, normalCase } from '../mocks/currentCase'
import type { CurrentCaseView } from '../types/view'

/**
 * 이 화면에서 볼 수 있는 Mock.
 *
 * TODO(API): 계약이 확정되면 `GET /cases/{caseId}` 응답을 어댑터로 변환해 쓴다.
 * 그때 이 목록은 테스트 픽스처로 옮긴다.
 */
const MOCKS: Record<string, CurrentCaseView> = {
  'no-blocker': noBlockerCase,
  insufficient: insufficientCase,
}

export function CurrentCasePage() {
  const { search } = useLocation()
  const mockKey = readMockKey(search)
  const view: CurrentCaseView = Object.hasOwn(MOCKS, mockKey) ? MOCKS[mockKey] : normalCase
  const { facts, blocker, nextAction } = view

  const confirmed = facts.filter((fact) => fact.status === 'CONFIRMED')
  const pending = facts.filter((fact) => fact.status !== 'CONFIRMED')
  // 확인 중인 항목은 이미 사용자가 알아보러 간 것이라 "알려주세요" 목록에 넣지 않는다
  const unknown = pending.filter((fact) => fact.status === 'UNKNOWN')

  return (
    <AppShell
      title="내 폐업 준비"
      subtitle={nextAction ? `${nextAction.seq}번째 할 일` : undefined}
    >
      {nextAction ? (
        <NextActionCard nextAction={nextAction} />
      ) : (
        <InsufficientInfoCard missing={unknown} />
      )}

      {blocker && <BlockerCard blocker={blocker} />}
      {nextAction && !blocker && <NoBlockerCard />}

      <FactList
        title="내 가게 상황"
        caption={`확인 ${confirmed.length} · 미확인 ${pending.length}`}
        facts={confirmed}
      />

      <FactList title="아직 확인 안 된 것" caption="순서대로 하나씩" facts={pending} />
    </AppShell>
  )
}
