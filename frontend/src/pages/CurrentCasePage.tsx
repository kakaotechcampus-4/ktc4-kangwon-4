import { AppShell } from '../components/AppShell'
import { BlockerCard } from '../components/BlockerCard'
import { FactList } from '../components/FactList'
import { InsufficientInfoCard } from '../components/InsufficientInfoCard'
import { NextActionCard } from '../components/NextActionCard'
import { NoBlockerCard } from '../components/NoBlockerCard'
import type { CurrentCaseView } from '../types/view'

interface CurrentCasePageProps {
  data: CurrentCaseView
}

export function CurrentCasePage({ data }: CurrentCasePageProps) {
  const { facts, blocker, nextAction } = data

  const confirmed = facts.filter((fact) => fact.status === 'CONFIRMED')
  const pending = facts.filter((fact) => fact.status !== 'CONFIRMED')

  return (
    <AppShell
      title="내 폐업 준비"
      subtitle={nextAction ? `${nextAction.seq}번째 할 일` : undefined}
    >
      {nextAction ? (
        <NextActionCard nextAction={nextAction} />
      ) : (
        <InsufficientInfoCard missing={pending} />
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
