import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { AppShell } from '../components/AppShell'
import { ConflictChoice, type ConflictSide } from '../components/ConflictChoice'
import { PendingCard } from '../components/PendingCard'
import { MOCK_SWITCH_ENABLED } from '../lib/mockSwitch'
import { conflictConfirm, pendingMessages, simulateConfirm } from '../mocks/resultFlow'
import type { ConfirmView } from '../types/view'

/**
 * ④ 충돌 확인.
 *
 * 기존 기록과 새 입력이 어긋날 때만 들른다. 정상 경로는 ③에서 ⑤로 바로 간다.
 *
 * `rollback` API가 계약에서 빠져, 값을 되돌릴 수 있는 지점은 여기뿐이다.
 * 그래서 한 항목이라도 고르지 않으면 진행할 수 없게 한다.
 */
export function ConfirmChangePage() {
  const { state } = useLocation()
  const navigate = useNavigate()

  const view = (state as ConfirmView | null) ?? (MOCK_SWITCH_ENABLED ? conflictConfirm : null)
  const [choices, setChoices] = useState<Record<string, ConflictSide>>({})
  const [isPending, setIsPending] = useState(false)

  if (!view) return <Navigate to="/" replace />

  const { rawInput, conflicts } = view
  const allDecided = conflicts.every((conflict) => choices[conflict.key])

  async function handleConfirm() {
    setIsPending(true)

    // TODO(API): POST /cases/{caseId}/results/confirm 으로 선택값을 보낸다.
    // 요청 형태는 confirmedChanges: [{ field, value }] 배열이다.
    const replan = await simulateConfirm()
    navigate('/replan', { state: replan })
  }

  return (
    <AppShell title="확인이 필요합니다" subtitle="기록과 다른 부분이 있어요">
      {/* 어느 문장 때문에 이 화면이 떴는지 모르면 무엇을 고르는지도 알 수 없다 */}
      <section className="rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-sm font-bold tracking-wide text-gray-500">이번에 하신 말씀</h2>
        <p className="mt-2 text-base leading-relaxed text-gray-900">{rawInput}</p>
      </section>

      <p className="text-base leading-relaxed text-gray-600">
        아래 항목이 지금 기록과 달라요. 어느 쪽이 맞는지 골라 주세요.
      </p>

      {/* 보내는 중에는 선택을 잠근다. fieldset이 안쪽 버튼까지 함께 비활성화한다 */}
      <fieldset disabled={isPending} className="contents">
        {conflicts.map((conflict) => (
          <ConflictChoice
            key={conflict.key}
            item={conflict}
            selected={choices[conflict.key] ?? null}
            onSelect={(side) => setChoices((current) => ({ ...current, [conflict.key]: side }))}
          />
        ))}

        <button
          type="button"
          disabled={!allDecided}
          onClick={handleConfirm}
          className="min-h-13 w-full rounded-xl bg-gray-900 text-base font-bold text-white disabled:bg-gray-200 disabled:text-gray-400"
        >
          이대로 진행하기
        </button>
      </fieldset>

      {isPending && <PendingCard messages={pendingMessages} />}

    </AppShell>
  )
}
