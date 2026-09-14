import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { AppShell } from '../components/AppShell'
import { FollowUpQuestionCard } from '../components/FollowUpQuestionCard'
import { NoticeCard } from '../components/NoticeCard'
import { PendingCard } from '../components/PendingCard'
import { ResultInputForm } from '../components/ResultInputForm'
import { readMockKey } from '../lib/mockSwitch'
import { pendingMessages, resultInput, simulateSubmit } from '../mocks/resultFlow'
import type { SubmitState } from '../types/view'

/**
 * ③ 결과 입력.
 *
 * 응답에 따라 화면을 옮기거나(⑤·④) 이 자리에 머문다. 머무는 경우를 `SubmitState`로
 * 두어, 한 화면이 다섯 얼굴을 갖되 그 목록이 타입에 드러나게 했다.
 */
export function ResultInputPage() {
  const { search } = useLocation()
  const navigate = useNavigate()

  const [text, setText] = useState('')
  const [state, setState] = useState<SubmitState>({ kind: 'IDLE' })

  const { nextAction } = resultInput
  const isPending = state.kind === 'PENDING'

  async function handleSubmit() {
    setState({ kind: 'PENDING' })

    // TODO(API): 계약이 확정되면 POST /cases/{caseId}/results 로 바꾼다.
    const outcome = await simulateSubmit(readMockKey(search))

    switch (outcome.kind) {
      case 'REPLAN':
        navigate('/replan', { state: outcome.view })
        return
      case 'CONFIRM':
        navigate('/confirm', { state: outcome.view })
        return
      case 'STAY':
        setState(outcome.state)
        return
    }
  }

  return (
    <AppShell title="결과 알려주기" subtitle={`${nextAction.seq}번째 할 일의 결과`}>
      {/* 며칠 뒤에 들어올 수도 있다. 무엇에 대한 결과인지 먼저 상기시킨다 */}
      <section className="rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-sm font-bold tracking-wide text-gray-500">하시기로 한 일</h2>
        <p className="mt-2 text-base leading-relaxed text-gray-900">{nextAction.title}</p>
      </section>

      <ResultInputForm
        value={text}
        onChange={setText}
        onSubmit={handleSubmit}
        disabled={isPending}
      />

      {isPending && <PendingCard messages={pendingMessages} />}

      {state.kind === 'NEEDS_MORE_INFO' && <FollowUpQuestionCard questions={state.questions} />}

      {state.kind === 'INVALID_TRANSITION' && (
        <NoticeCard
          tone="WARNING"
          title={state.message}
          description="기록과 다른 부분이 있는지 확인하고 다시 말씀해 주세요."
        />
      )}

      {state.kind === 'FAILED' && (
        <NoticeCard
          tone="NEUTRAL"
          title={state.message}
          description="말씀하신 내용은 저장되지 않았습니다. 잠시 후 다시 시도해 주세요."
          action={{ label: '다시 시도', onClick: handleSubmit }}
        />
      )}
    </AppShell>
  )
}
