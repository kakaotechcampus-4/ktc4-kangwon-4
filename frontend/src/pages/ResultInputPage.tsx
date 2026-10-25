import { type ComponentProps, useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { AppShell } from '../components/AppShell'
import { FollowUpQuestionCard } from '../components/FollowUpQuestionCard'
import { NoticeCard } from '../components/NoticeCard'
import { PendingCard } from '../components/PendingCard'
import { ResultInputForm } from '../components/ResultInputForm'
import { MOCK_SWITCH_ENABLED, readMockKey } from '../lib/mockSwitch'
import { pendingMessages, resultInput, simulateSubmit } from '../mocks/resultFlow'
import type { FailureNotice, NextAction, SubmitState } from '../types/view'

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
  // 개발·Preview에서만 Mock으로 떨어지고, 그 외에는 진입 분기로 돌린다 —
  // 없는 할 일을 지어내 보여주면 사용자가 엉뚱한 대상에 결과를 보고하게 된다.
  const nextAction =
    (routeState as NextAction | null) ?? (MOCK_SWITCH_ENABLED ? resultInput.nextAction : null)
  const isPending = state.kind === 'PENDING'
  const canRetry = text.trim().length > 0
  const notice = stayNotice(state, {
    retry: { label: '다시 보내기', onClick: handleSubmit, disabled: !canRetry },
    goToCase: { label: '지금 상황 보기', onClick: () => navigate({ pathname: '/case', search }) },
  })

  if (!nextAction) return <Navigate to={{ pathname: '/', search }} replace />

  async function handleSubmit() {
    // "다시 보내기" 버튼도 이 함수를 부른다. 폼에만 검증을 두면 그 경로로 빈 입력이 나간다
    if (text.trim().length === 0) return

    setState({ kind: 'PENDING' })

    // TODO(API): 계약이 확정되면 POST /cases/{caseId}/results 로 바꾼다.
    // 진행 중인 요청 자체를 끊는 것은 그때 AbortController로 처리한다.
    //
    // 함께 챙길 것:
    // - 대기 중 이탈해도 서버에는 이미 반영됐을 수 있다. /로 돌아왔을 때 그 변경이
    //   보이도록 현재 Case를 다시 불러와야 한다.
    // - "다시 시도"가 같은 요청을 두 번 만들 수 있다. §5 요청 예시에 clientEventId가
    //   있지만 의미가 계약에 정의돼 있지 않다 — 중복 제거 키가 맞는지 BE에 먼저 확인하고,
    //   맞다면 재시도 때 같은 값을 보낸다.
    // 그때 실패 처리도 함께 넣는다 — 오류가 나면 PENDING에서 빠져나오지 못해
    // 입력창이 잠긴 채로 남는다. FAILED 상태가 그 자리다.
    const outcome = await simulateSubmit(readMockKey(search), text)
    if (!alive.current) return

    switch (outcome.kind) {
      case 'REPLAN':
        navigate({ pathname: '/replan', search }, { state: outcome.view })
        return
      case 'CONFIRM':
        navigate({ pathname: '/confirm', search }, { state: outcome.view })
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
    // 순번은 `/case` 에서 넘어올 때 없다 — 서버가 보내지 않는 값이다.
    // 그대로 끼우면 "undefined번째 할 일의 결과" 가 뜬다
    <AppShell
      title="결과 알려주기"
      subtitle={nextAction.seq === undefined ? undefined : `${nextAction.seq}번째 할 일의 결과`}
    >
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

      {notice && <NoticeCard {...notice} />}
    </AppShell>
  )
}

type NoticeProps = ComponentProps<typeof NoticeCard>
type NoticeAction = NonNullable<NoticeProps['action']>

/**
 * 더 적어야 할 항목을 한 문장으로. `/case` 의 `requestedText` 와 같은 모양이다.
 *
 * 항목을 문장 끝에 떼어 둔다. 앞에 두면 "범위를"·"업종을" 처럼 받침에 따라 조사가 갈린다.
 */
function detailText({ fields, partial }: { fields: string[]; partial: boolean }): string {
  if (fields.length === 0) {
    return '어떤 내용이 더 필요한지는 아직 확인되지 않았어요. 조금 더 자세히 적어서 다시 보내 주세요.'
  }
  return `이 내용을 조금 더 적어서 다시 보내 주세요 — ${fields.join(', ')}${partial ? ' 등' : ''}.`
}

/** 판단 실패 이유마다의 안내. "다시 보내기"는 같은 글을 그대로 보내도 될 때만 단다 */
function failureNotice(notice: FailureNotice, retry: NoticeAction): NoticeProps {
  switch (notice.kind) {
    case 'RETRY_AVAILABLE':
      return {
        tone: 'NEUTRAL',
        title: '이번 결과로 다음 할 일을 정하지 못했어요.',
        description: '적어 주신 내용은 그대로 있어요. 같은 내용으로 다시 보내실 수 있어요.',
        action: retry,
      }

    // 더 적어야 하는 실패에 "다시 보내기"를 달면 고치지 않은 글로 같은 실패를 되풀이한다.
    // 아래 폼의 보내기 버튼이 그 자리다
    case 'NEEDS_DETAIL':
      return { tone: 'WARNING', title: '추가 확인이 필요해요.', description: detailText(notice) }

    case 'SERVICE_SIDE':
      return {
        tone: 'NEUTRAL',
        title: '서비스에서 확인이 필요한 문제가 생겼어요.',
        description: '적어 주신 내용은 받았어요. 이 건은 저희 쪽에서 봐야 하는 문제예요.',
      }

    case 'NO_RECOVERY':
      return {
        tone: 'NEUTRAL',
        title: '이번 결과로 다음 할 일을 정하지 못했어요.',
        description: '이번 판단에 대해서는 더 해 보실 수 있는 것이 없어요.',
      }

    case 'UNKNOWN_CAUSE':
      return {
        tone: 'NEUTRAL',
        title: '이번 결과로 다음 할 일을 정하지 못했어요.',
        description: '자세한 이유는 확인되지 않았어요.',
      }
  }
}

/**
 * 머무는 상태마다 띄울 안내 한 장. 안내할 것이 없는 상태면 `null`.
 *
 * `/case` 의 `failureCard` 를 바탕으로 이 화면에 맞게 고쳤다. 다른 점은 둘이다 —
 * 사장님이 방금 글을 적어 보낸 참이고, 여기서는 **실제로 다시 보낼 수 있다.**
 *
 * 이 화면이 아는 판단이 낡았거나 끝을 못 본 경우는 `/case` 로 보낸다. 거기가 지금 판단을
 * 다시 묻고 기다리는 자리라, 같은 기다림을 여기 하나 더 만들지 않는다.
 */
function stayNotice(
  state: SubmitState,
  actions: { retry: NoticeAction; goToCase: NoticeAction },
): NoticeProps | null {
  switch (state.kind) {
    case 'IDLE':
    case 'PENDING':
    case 'NEEDS_MORE_INFO':
      return null

    case 'FAILED':
      return failureNotice(state.notice, actions.retry)

    case 'SEND_FAILED':
      return {
        tone: 'NEUTRAL',
        title: '결과를 보내지 못했어요.',
        description: '연결이 불안정했을 수 있어요. 적어 주신 내용은 그대로 있어요.',
        action: actions.retry,
      }

    case 'STALE':
      return {
        tone: 'NEUTRAL',
        title: '그사이 상황이 바뀌었어요.',
        description: '다른 곳에서 결과를 보냈거나 새 판단이 나왔어요.',
        action: actions.goToCase,
      }

    case 'WAITED_TOO_LONG':
      return {
        tone: 'NEUTRAL',
        title: '판단이 오래 걸리고 있어요.',
        description: '보내 주신 결과는 접수됐어요. 끝나면 지금 상황 화면에서 보실 수 있어요.',
        action: actions.goToCase,
      }

    case 'UNRECOGNIZED':
      return {
        tone: 'NEUTRAL',
        title: '판단 결과를 읽지 못했어요.',
        description: '보내 주신 결과는 접수됐어요. 지금 상황 화면에서 다시 확인해 주세요.',
        action: actions.goToCase,
      }
  }
}
