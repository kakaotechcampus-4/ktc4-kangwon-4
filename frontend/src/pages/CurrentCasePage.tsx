import { Navigate, useLocation } from 'react-router'

import { AppShell } from '../components/AppShell'
import { BlockerCard } from '../components/BlockerCard'
import { FactList } from '../components/FactList'
import { InsufficientInfoCard } from '../components/InsufficientInfoCard'
import { NextActionCard } from '../components/NextActionCard'
import { NoBlockerCard } from '../components/NoBlockerCard'
import { NoticeCard } from '../components/NoticeCard'
import { useCase } from '../hooks/useCase'

/**
 * 현재 Case. 사용자가 돌아올 곳이고, 이 제품에서 유일하게 "지금 상황"을 보여주는 화면이다.
 *
 * 그래서 들어올 때마다 서버에 다시 묻는다. 앞 화면에서 받은 값을 들고 오면 편하지만,
 * 그 값이 히스토리에 남아 오래된 Case가 지금 상황인 척 다시 뜬다.
 */
export function CurrentCasePage() {
  const { search } = useLocation()
  const query = useCase()

  if (query.status === 'LOADING') {
    return (
      <AppShell title="내 폐업 준비">
        <section className="rounded-2xl bg-white p-5" role="status" aria-live="polite">
          <p className="text-base leading-relaxed text-gray-600">불러오는 중입니다.</p>
        </section>
      </AppShell>
    )
  }

  /**
   * 아직 Case를 만들지 않은 사용자가 주소로 직접 들어온 경우다.
   * 빈 화면을 보여주는 대신 만들러 보낸다.
   */
  if (query.status === 'EMPTY') return <Navigate to={{ pathname: '/start', search }} replace />

  if (query.status === 'FAILED') {
    return (
      <AppShell title="내 폐업 준비">
        <NoticeCard
          tone="NEUTRAL"
          title="지금 상황을 불러오지 못했습니다."
          description="잠시 후 다시 시도해 주세요. 입력하신 내용은 그대로 있습니다."
        />

        {/* 라우터로 옮겨도 같은 화면이라 다시 받아올 수 없다. 페이지를 새로 연다 */}
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="min-h-13 w-full rounded-xl bg-gray-900 text-base font-bold text-white"
        >
          다시 시도
        </button>
      </AppShell>
    )
  }

  const { facts, blocker, nextAction } = query.view

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
