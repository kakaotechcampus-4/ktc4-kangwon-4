import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { AppShell } from '../components/AppShell'
import { FollowUpQuestionCard } from '../components/FollowUpQuestionCard'
import { NoticeCard } from '../components/NoticeCard'
import { PendingCard } from '../components/PendingCard'
import { ResultInputForm } from '../components/ResultInputForm'
import { MOCK_SWITCH_ENABLED, readMockKey } from '../lib/mockSwitch'
import { pendingMessages, resultInput, simulateSubmit } from '../mocks/resultFlow'
import type { NextAction, SubmitState } from '../types/view'

/**
 * ③ 결과 입력.
 *
 * 응답에 따라 화면을 옮기거나(⑤·④) 이 자리에 머문다. 머무는 경우를 `SubmitState`로
 * 두어, 한 화면이 다섯 얼굴을 갖되 그 목록이 타입에 드러나게 했다.
 */
export function ResultInputPage() {
  const { search, state: routeState } = useLocation()
  const navigate = useNavigate()

  const [text, setText] = useState('')
  const [state, setState] = useState<SubmitState>({ kind: 'IDLE' })

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

  // 어느 할 일의 결과인지는 앞 화면이 알려준다. 주소로 직접 열었을 때는 없으므로
  // 개발·Preview에서만 Mock으로 떨어지고, 그 외에는 현재 Case로 돌린다 —
  // 없는 할 일을 지어내 보여주면 사용자가 엉뚱한 대상에 결과를 보고하게 된다.
  const nextAction =
    (routeState as NextAction | null) ?? (MOCK_SWITCH_ENABLED ? resultInput.nextAction : null)
  const isPending = state.kind === 'PENDING'
  const canRetry = text.trim().length > 0

  if (!nextAction) return <Navigate to="/" replace />

  async function handleSubmit() {
    // "다시 시도" 버튼도 이 함수를 부른다. 폼에만 검증을 두면 그 경로로 빈 입력이 나간다
    if (text.trim().length === 0) return

    setState({ kind: 'PENDING' })

    // TODO(API): 계약이 확정되면 POST /cases/{caseId}/results 로 바꾼다.
    // 진행 중인 요청 자체를 끊는 것은 그때 AbortController로 처리한다.
    // 그때 실패 처리도 함께 넣는다 — 오류가 나면 PENDING에서 빠져나오지 못해
    // 입력창이 잠긴 채로 남는다. FAILED 상태가 그 자리다.
    const outcome = await simulateSubmit(readMockKey(search), text)
    if (!alive.current) return

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
      default: {
        // 갈래가 늘면 여기서 컴파일이 막힌다. 없으면 조용히 빠져나가 PENDING에 갇힌다
        const unhandled: never = outcome
        return unhandled
      }
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
          description="잠시 후 다시 시도해 주세요. 같은 내용을 그대로 보내셔도 됩니다."
          action={{ label: '다시 시도', onClick: handleSubmit, disabled: !canRetry }}
        />
      )}
    </AppShell>
  )
}
