import { type ComponentProps, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { toResultsEntry, toSubmitOutcome } from '../adapters/results'
import { AppShell } from '../components/AppShell'
import { FollowUpQuestionCard } from '../components/FollowUpQuestionCard'
import { NoticeCard } from '../components/NoticeCard'
import { PendingCard } from '../components/PendingCard'
import { ResultInputForm } from '../components/ResultInputForm'
import { ApiError, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import { fetchResultsEntry, submitResult, waitForResult } from '../lib/resultSubmit'
import { pendingMessages, resultInput, simulateSubmit } from '../mocks/resultFlow'
import type { FailureNotice, NextAction, SubmitOutcome, SubmitState } from '../types/view'

/** 들어올 때 서버에 물은 결과. 폼은 `READY` 일 때만 연다 */
type EntryQuery =
  | { status: 'LOADING' }
  /** `historyId` 는 이 결과가 어느 판단에 대한 것인지. 보낼 때마다 새 접수 번호로 바뀐다 */
  | { status: 'READY'; nextAction: NextAction; historyId: number }
  | { status: 'LOAD_FAILED' }
  | { status: 'UNRECOGNIZED' }

/**
 * Mock 으로 볼 때의 진입. 서버를 부르지 않으니 판단 번호도 쓰지 않는다.
 *
 * `/case` Mock 의 할 일과 같은 이야기를 잇도록 `resultInput` 을 쓴다.
 */
const MOCK_ENTRY: EntryQuery = { status: 'READY', nextAction: resultInput.nextAction, historyId: 0 }

const stay = (state: SubmitState): SubmitOutcome => ({ kind: 'STAY', state })

/**
 * ③ 결과 입력.
 *
 * **들어올 때 서버에 먼저 묻는다.** 결과는 가장 최근 판단에 대해서만 보낼 수 있어서,
 * 앞 화면이 넘겨준 할 일을 믿고 폼을 열면 그사이 바뀐 판단에 대해 적게 된다. 라우터
 * state 로 받던 것을 버린 이유다 — 히스토리에 남은 값이 "지금 할 일"이라는 얼굴로 다시 뜬다.
 *
 * 보낸 뒤에는 응답에 따라 화면을 옮기거나(⑤·④) 이 자리에 머문다. 머무는 경우를
 * `SubmitState` 로 두어, 그 목록이 타입에 드러나게 했다.
 */
export function ResultInputPage() {
  const { search } = useLocation()
  const navigate = useNavigate()
  // 가짜 토큰으로 서버를 부르면 곧바로 401 이라, 그 경우에는 아예 부르지 않는다
  const usesMock = usesMockData(search)

  const [fetched, setFetched] = useState<EntryQuery>({ status: 'LOADING' })
  /** 다시 불러오기를 누를 때마다 올려 진입 조회를 다시 돌린다 */
  const [attempt, setAttempt] = useState(0)
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
  /** 판단을 기다리는 중이면 그 기다림을 끊는 손잡이. 화면을 떠날 때 당긴다 */
  const waiting = useRef<AbortController | null>(null)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      waiting.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (usesMock) return
    let current = true

    fetchResultsEntry().then(
      (body) => {
        if (!current) return
        const entry = toResultsEntry(body)

        switch (entry.kind) {
          case 'READY':
            setFetched({ status: 'READY', nextAction: entry.nextAction, historyId: entry.historyId })
            return
          // 확인을 기다리는 충돌부터 풀어야 한다. 뒤로 가기로 이 화면에 돌아오지 않게 바꿔 낀다
          case 'CONFIRM':
            navigate('/confirm', { replace: true, state: entry.view })
            return
          // 판단 중·되물을 것 있음·판단 실패는 `/case` 가 안내한다
          case 'ELSEWHERE':
            navigate('/case', { replace: true })
            return
          case 'UNRECOGNIZED':
            setFetched({ status: 'UNRECOGNIZED' })
            return
        }
      },
      (error: unknown) => {
        if (!current) return
        if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })
        // Case 가 없다. 진입 분기가 시작 화면으로 보낸다
        if (error instanceof ApiError && error.status === 404) return navigate('/', { replace: true })
        setFetched({ status: 'LOAD_FAILED' })
      },
    )

    return () => {
      current = false
    }
  }, [usesMock, attempt, navigate])

  const entry = usesMock ? MOCK_ENTRY : fetched
  const isPending = state.kind === 'PENDING'
  const canRetry = text.trim().length > 0
  const goToCase = { label: '지금 상황 보기', onClick: () => navigate({ pathname: '/case', search }) }
  const notice = stayNotice(state, {
    retry: { label: '다시 보내기', onClick: handleSubmit, disabled: !canRetry },
    goToCase,
  })

  /**
   * 실제 서버에 보내고 판단을 기다린다. 화면을 떠났거나 다른 화면으로 보냈으면 `null`.
   *
   * 보내기와 기다리기의 실패를 따로 받는다. 보내다 실패하면 서버가 받았는지조차 모르고,
   * 기다리다 실패하면 접수는 된 것이라 사장님에게 할 말이 다르다.
   */
  async function submitToServer(historyId: number, rawInput: string): Promise<SubmitOutcome | null> {
    let acceptedId: number
    try {
      acceptedId = await submitResult(historyId, rawInput)
    } catch (error: unknown) {
      if (!alive.current) return null
      if (error instanceof UnauthorizedError) {
        navigate('/login', { replace: true })
        return null
      }
      // 미결 충돌·직전 제출 판단 중·더 새로운 판단(409), Case 없음(404) — 이 화면이 아는 판단이 낡았다
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) {
        return stay({ kind: 'STALE' })
      }
      return stay({ kind: 'SEND_FAILED' })
    }

    // 방금 접수된 것이 이제 가장 최근 판단이다. 되묻거나 실패해 다시 보낼 때는 이 번호로 보낸다
    setFetched((current) => (current.status === 'READY' ? { ...current, historyId: acceptedId } : current))

    const controller = new AbortController()
    waiting.current = controller
    try {
      const waited = await waitForResult(acceptedId, { signal: controller.signal })
      switch (waited.kind) {
        case 'SETTLED':
          return toSubmitOutcome(waited.body)
        case 'STALE':
          return stay({ kind: 'STALE' })
        case 'WAITED_TOO_LONG':
          return stay({ kind: 'WAITED_TOO_LONG' })
      }
    } catch (error: unknown) {
      if (controller.signal.aborted || !alive.current) return null
      if (error instanceof UnauthorizedError) {
        navigate('/login', { replace: true })
        return null
      }
      // 다시 물어도 답이 같은 4xx 다. 접수는 됐으니 `/case` 에서 확인하게 한다
      return stay({ kind: 'UNRECOGNIZED' })
    } finally {
      waiting.current = null
    }
  }

  async function handleSubmit() {
    // "다시 보내기" 버튼도 이 함수를 부른다. 폼에만 검증을 두면 그 경로로 빈 입력이 나간다
    if (text.trim().length === 0 || entry.status !== 'READY') return

    setState({ kind: 'PENDING' })

    const outcome = usesMock
      ? await simulateSubmit(readMockKey(search), text)
      : await submitToServer(entry.historyId, text)
    if (!alive.current || outcome === null) return

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

  if (entry.status === 'LOADING') {
    return (
      <AppShell title="결과 알려주기">
        <section className="rounded-2xl bg-white p-5" role="status" aria-live="polite">
          <p className="text-base leading-relaxed text-gray-600">하시기로 한 일을 불러오고 있어요.</p>
        </section>
      </AppShell>
    )
  }

  if (entry.status === 'LOAD_FAILED') {
    return (
      <AppShell title="결과 알려주기">
        <NoticeCard
          tone="NEUTRAL"
          title="하시기로 한 일을 불러오지 못했어요."
          description="연결 상태를 확인하고 다시 불러와 주세요."
          action={{
            label: '다시 불러오기',
            onClick: () => {
              setFetched({ status: 'LOADING' })
              setAttempt((count) => count + 1)
            },
          }}
        />
      </AppShell>
    )
  }

  // 다시 불러와도 같은 답이 온다. 지금 판단을 보여주는 자리로 보낸다
  if (entry.status === 'UNRECOGNIZED') {
    return (
      <AppShell title="결과 알려주기">
        <NoticeCard
          tone="NEUTRAL"
          title="지금 상황을 읽지 못했어요."
          description="지금 상황 화면에서 다시 확인해 주세요."
          action={goToCase}
        />
      </AppShell>
    )
  }

  const { nextAction } = entry

  return (
    // 순번은 서버가 보내지 않는 값이라 없을 수 있다.
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
