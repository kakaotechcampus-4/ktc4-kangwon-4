import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { AppShell } from '../components/AppShell'
import { ConflictChoice } from '../components/ConflictChoice'
import { NoticeCard } from '../components/NoticeCard'
import { PendingCard } from '../components/PendingCard'
import { usesMockData } from '../lib/auth'
import { conflictConfirm, pendingMessages, simulateConfirm } from '../mocks/resultFlow'
import type { ConfirmView, ConflictSide } from '../types/view'

/**
 * ④ 충돌 확인.
 *
 * 기존 기록과 새 입력이 어긋날 때만 들른다. 정상 경로는 ③에서 ⑤로 바로 간다.
 *
 * `rollback` API가 계약에서 빠져, 값을 되돌릴 수 있는 지점은 여기뿐이다.
 * 그래서 한 항목이라도 고르지 않으면 진행할 수 없게 한다.
 *
 * **실서버에서는 아직 고른 것을 보내지 않는다.** 충돌 결정을 받는 API(#108)가 머지 전이라,
 * 실제 충돌을 보여주고 고르게는 하되 보내는 버튼만 잠근다. 보낼 곳이 생기면 버튼만 풀면
 * 되도록 항목마다 서버 번호(`referenceId`)를 이미 들고 있다.
 */
export function ConfirmChangePage() {
  const { search, state } = useLocation()
  const navigate = useNavigate()

  // 가짜 토큰으로 서버를 부르면 곧바로 401 이라, 그 경우에는 아예 부르지 않는다
  const usesMock = usesMockData(search)

  // 주소로 직접 열었을 때는 넘겨받은 충돌이 없다. Mock 으로 볼 때만 준비된 것으로 그린다 —
  // 없는 충돌을 지어내 보여주면 사장님이 기록에 없는 것을 고르게 된다
  const view = (state as ConfirmView | null) ?? (usesMock ? conflictConfirm : null)
  const [choices, setChoices] = useState<Record<string, ConflictSide>>({})
  const [isPending, setIsPending] = useState(false)

  /*
   * 화면이 아직 붙어 있는지.
   *
   * 응답을 기다리는 동안 사용자가 뒤로 갈 수 있다. 그때 이동을 그대로 실행하면
   * 일부러 빠져나온 화면으로 몇 초 뒤에 끌려간다.
   *
   * 정리 함수만 두면 StrictMode의 이중 실행에서 첫 마운트가 곧바로 false가 되므로
   * 실행할 때마다 다시 true로 세운다.
   */
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  if (!view) return <Navigate to={{ pathname: '/', search }} replace />
  // 고를 것이 없으면 이 화면의 존재 이유가 없다. 서버가 빈 목록을 보내도 막다른 골목이
  // 되지 않게 진입 분기로 돌린다 — 거기서 지금 상태에 맞는 화면을 다시 고른다.
  if (view.conflicts.length === 0) return <Navigate to={{ pathname: '/', search }} replace />

  const { rawInput, conflicts } = view
  const allDecided = conflicts.every((conflict) => choices[conflict.key])

  // 보낼 곳이 없는 동안은 다 골라도 누를 수 없다. 눌리는데 아무 일도 없으면 고장으로 읽힌다
  const canSend = usesMock

  async function handleConfirm() {
    setIsPending(true)

    // TODO(#108): 실서버에서는 고른 쪽을 항목의 `referenceId` 와 함께 보내고, 판단이 끝날
    // 때까지 기다린다. 보내기·기다리기 실패에서 빠져나올 길도 그때 `/results` 와 같게 만든다 —
    // 지금은 Mock 이라 실패하지 않지만, 서버로 바꾸면 오류가 나도 화면이 잠긴 채로 남는다.
    const replan = await simulateConfirm(choices)
    if (!alive.current) return
    // 이미 해결한 충돌 화면으로 뒤로 돌아가 같은 결정을 다시 제출하는 일을 막는다.
    // 히스토리에서 이 항목을 지우는 것이라 확인을 마친 경우에만 해당한다 —
    // 아직 고르지 않고 떠난 충돌은 그대로 남아 다시 들어올 수 있다.
    navigate({ pathname: '/replan', search }, { state: replan, replace: true })
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
          disabled={!allDecided || !canSend}
          onClick={handleConfirm}
          className="min-h-13 w-full rounded-xl bg-gray-900 text-base font-bold text-white disabled:bg-gray-200 disabled:text-gray-400"
        >
          이대로 진행하기
        </button>
      </fieldset>

      {isPending && <PendingCard messages={pendingMessages} />}

      {!canSend && (
        <NoticeCard
          tone="NEUTRAL"
          title="선택을 보내는 기능은 준비 중이에요."
          description="고르신 내용은 아직 저장되지 않아요. 기록은 지금 그대로 남아 있습니다."
          action={{ label: '지금 상황 보기', onClick: () => navigate({ pathname: '/case', search }) }}
        />
      )}
    </AppShell>
  )
}
