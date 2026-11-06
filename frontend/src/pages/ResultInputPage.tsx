import { type ComponentProps, type ReactNode, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { toAnswerInput, toResultSteps, toResultsEntry, toSubmitOutcome } from '../adapters/results'
import { Button } from '../components/ui/Button'
import { HammerLoader } from '../components/ui/HammerLoader'
import { InfoBox } from '../components/ui/InfoBox'
import { ProcessingScreen } from '../components/ui/ProcessingScreen'
import { TopBar } from '../components/ui/TopBar'
import { ApiError, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import {
  fetchResultsEntry,
  MAX_RESULT_LENGTH,
  RESULT_LENGTH_HINT_FROM,
  submitResult,
  waitForResult,
} from '../lib/resultSubmit'
import { judgmentNeedsDetailCase, moreInfoCase } from '../mocks/currentCase'
import { resultInput, simulateSubmit } from '../mocks/resultFlow'
import type { RestorationAnswer, ResultInputKind } from '../types/api'
import type { FailureNotice, NextAction, SubmitOutcome, SubmitState } from '../types/view'

/**
 * 이 화면이 받는 것.
 *
 * - `RESULT` 할 일을 하고 온 결과
 * - `ANSWER` 리본이 되물은 질문들의 답
 * - `RESUBMIT` 판단이 실패해 더 알려주셔야 하는 내용
 *
 * 둘 다 같은 길(`POST /cases/results`)로 보낸다. 다른 것은 화면에 띄울 물음과 보낼 글 모양뿐이다.
 */
type Ask =
  | { kind: 'RESULT'; nextAction: NextAction; inputKind: ResultInputKind }
  | { kind: 'ANSWER'; questions: string[] }
  | { kind: 'RESUBMIT'; notice: Extract<FailureNotice, { kind: 'NEEDS_DETAIL' }> }

/** 들어올 때 서버에 물은 결과. 폼은 `READY` 일 때만 연다 */
type EntryQuery =
  | { status: 'LOADING' }
  /** `historyId` 는 이 결과가 어느 판단에 대한 것인지. 보낼 때마다 새 접수 번호로 바뀐다 */
  | { status: 'READY'; ask: Ask; historyId: number }
  | { status: 'LOAD_FAILED' }
  | { status: 'UNRECOGNIZED' }

/**
 * Mock 으로 볼 때의 진입. 서버를 부르지 않으니 판단 번호도 쓰지 않는다.
 *
 * `/case` Mock 과 같은 이야기를 잇는다. `?mock=more-info` 는 홈의 "답하러 가기"에서 오므로
 * 질문에 답하는 모양으로 연다.
 */
function mockEntry(mockKey: string): EntryQuery {
  const failed = judgmentNeedsDetailCase.judgment
  const ask: Ask =
    mockKey === 'more-info' && moreInfoCase.judgment.status === 'NEEDS_MORE_INFO'
      ? { kind: 'ANSWER', questions: moreInfoCase.judgment.questions }
      : mockKey === 'judgment-failed-detail' && failed.status === 'FAILED' && failed.notice.kind === 'NEEDS_DETAIL'
        ? { kind: 'RESUBMIT', notice: failed.notice }
        : { kind: 'RESULT', nextAction: resultInput.nextAction, inputKind: 'TEXT' }
  return { status: 'READY', ask, historyId: 0 }
}

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
 *
 * 리본이 되물으면(들어올 때든 보낸 뒤든) 같은 화면이 질문에 답하는 모양으로 바뀐다.
 * 답은 질문을 붙여 보낸다(`toAnswerInput`) — 재판단 때 AI는 직전 질문을 모른다.
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
  const [restorationAnswer, setRestorationAnswer] = useState<Partial<RestorationAnswer>>({})
  const [directInput, setDirectInput] = useState(false)
  /** 질문마다 적은 답. 질문 문장으로 찾는다 — 같은 질문을 다시 받으면 적었던 답이 그대로 남는다 */
  const [answers, setAnswers] = useState<Record<string, string>>({})
  /**
   * 보낸 뒤 리본이 되물은 질문. 들어올 때의 물음보다 앞선다.
   *
   * 상태(`state`)와 따로 둔다. 답을 보내다 실패하면 상태는 "보내지 못함"으로 바뀌는데,
   * 그때도 질문은 화면에 남아 있어야 같은 답을 다시 보낼 수 있다.
   */
  const [askedAgain, setAskedAgain] = useState<string[] | null>(null)
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
  /** 마지막으로 접수된 판단 번호. 반영되면 이 번호를 주소에 실어 `/replan` 으로 간다 */
  const lastAcceptedId = useRef<number | null>(null)
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
            setFetched({
              status: 'READY',
              ask: { kind: 'RESULT', nextAction: entry.nextAction, inputKind: entry.inputKind },
              historyId: entry.historyId,
            })
            return
          case 'ANSWER':
            setFetched({
              status: 'READY',
              ask: { kind: 'ANSWER', questions: entry.questions },
              historyId: entry.historyId,
            })
            return
          case 'RESUBMIT':
            setFetched({
              status: 'READY',
              ask: { kind: 'RESUBMIT', notice: entry.notice },
              historyId: entry.historyId,
            })
            return
          // 확인을 기다리는 충돌부터 풀어야 한다. 뒤로 가기로 이 화면에 돌아오지 않게 바꿔 낀다
          case 'CONFIRM':
            navigate('/confirm', { replace: true, state: entry.view })
            return
          // 판단 중·더 적어도 풀리지 않는 실패는 `/case` 가 안내한다
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
        // Case 가 없다. 진입 분기가 상황 진단으로 보낸다
        if (error instanceof ApiError && error.status === 404) return navigate('/', { replace: true })
        setFetched({ status: 'LOAD_FAILED' })
      },
    )

    return () => {
      current = false
    }
  }, [usesMock, attempt, navigate])

  const entry = usesMock ? mockEntry(readMockKey(search)) : fetched
  /** 반영 결과에서 "다르게 이해했어요"로 왔는지. 보내는 길과 글은 같고 안내만 다르다 */
  const correcting = new URLSearchParams(search).get('fix') === '1'
  /** 지금 답을 받는 질문. 없으면 할 일의 결과를 받는다 */
  const questions =
    askedAgain ?? (entry.status === 'READY' && entry.ask.kind === 'ANSWER' ? entry.ask.questions : null)
  /**
   * 보낼 글. 질문에 답할 때는 질문을 붙이고, 답하지 않은 질문은 뺀다.
   * 다시 알려주실 때도 요청한 항목을 질문 자리에 붙인다 — AI 는 무엇을 물었는지 모른다.
   * 요청한 항목이 비어 있으면 물은 것이 없어서 글만 보낸다.
   *
   * **방금 보낸 결과가 "이것을 더 알려 달라"로 실패했으면 그 항목을 붙인다.** 화면을 열 때의 안내(홈의
   * "다시 알려주기")보다 지금 화면에 떠 있는 실패 안내가 최신이다. 처음 안내를 붙이면 물은 것과 답이 엇갈리고,
   * 할 일의 결과를 보내다 실패한 경우는 물은 것 없이 나간다.
   */
  const resubmitNotice = entry.status === 'READY' && entry.ask.kind === 'RESUBMIT' ? entry.ask.notice : null
  const latestDetail = state.kind === 'FAILED' && state.notice.kind === 'NEEDS_DETAIL' ? state.notice : null
  const askedFields = latestDetail ?? resubmitNotice
  const canChoose = entry.status === 'READY' && entry.ask.kind === 'RESULT'
    && entry.ask.inputKind === 'RESTORATION_ANSWER' && !correcting && questions === null && !askedFields
  const usingChoices = canChoose && !directInput
  const selectionInput: RestorationAnswer | null = restorationAnswer.restoration_scope && restorationAnswer.demolition_required
    ? { restoration_scope: restorationAnswer.restoration_scope, demolition_required: restorationAnswer.demolition_required }
    : null
  const draft = questions
    ? toAnswerInput(questions.map((question) => ({ question, answer: answers[question] ?? '' })))
    : askedFields && askedFields.fields.length > 0
      ? toAnswerInput([{ question: requestedFieldsText(askedFields), answer: text }])
      : text.trim()
  const isPending = state.kind === 'PENDING'
  /*
   * 안내가 `/case` 로 보내는 상태에서는 폼을 잠근다. 안내와 폼이 서로 다른 말을 하면 안 된다.
   *
   * 끝을 모르는 상태(상황 바뀜·오래 걸림·읽지 못함)에서 다시 보내면, 판단 중인 제출 위에서는
   * 409 라 엉뚱한 안내가 뜨고 이미 반영된 판단 위에서는 같은 결과가 두 번 들어간다.
   * "더 해 보실 수 있는 것이 없다"·"저희 쪽 문제"라고 한 실패에서 보낼 수 있으면 그 말이 거짓이 된다.
   */
  const formLocked =
    isPending ||
    state.kind === 'STALE' ||
    state.kind === 'WAITED_TOO_LONG' ||
    state.kind === 'UNRECOGNIZED' ||
    (state.kind === 'FAILED' && (state.notice.kind === 'SERVICE_SIDE' || state.notice.kind === 'NO_RECOVERY'))
  // 너무 긴 글은 자르지 않고 보내기를 막는다. 소리 없이 잘라 보내면 사장님이 적은 뒷부분이 사라진다.
  // 아래 [보내기]와 실패 안내의 [다시 보내기]가 같은 조건을 쓴다
  const tooLong = !usingChoices && draft.length > MAX_RESULT_LENGTH
  const canRetry = usingChoices ? selectionInput !== null : draft.length > 0 && !tooLong
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
  async function submitToServer(historyId: number, input: string | RestorationAnswer): Promise<SubmitOutcome | null> {
    let acceptedId: number
    try {
      acceptedId = await submitResult(historyId, input)
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
      // 받을 수 없는 글이다(너무 긴 글 등). 같은 글을 다시 보내도 같은 답이라 고쳐 보내게 한다
      if (error instanceof ApiError && error.status === 422) return stay({ kind: 'SEND_REJECTED' })
      return stay({ kind: 'SEND_FAILED' })
    }

    if (!alive.current) return null
    // 방금 접수된 것이 이제 가장 최근 판단이다. 되묻거나 실패해 다시 보낼 때는 이 번호로 보낸다
    setFetched((current) => (current.status === 'READY' ? { ...current, historyId: acceptedId } : current))
    setState({ kind: 'PENDING', accepted: true })
    lastAcceptedId.current = acceptedId

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
    // "다시 보내기" 버튼도 이 함수를 부른다. 폼에만 검증을 두면 그 경로로 빈 입력·너무 긴 글이 나간다
    if (!canRetry || formLocked || entry.status !== 'READY') return

    // Mock 은 접수 단계가 없다. 보내는 순간 받은 것으로 둔다
    setState({ kind: 'PENDING', accepted: usesMock })

    const outcome = usesMock
      ? await simulateSubmit(readMockKey(search), draft)
      : await submitToServer(entry.historyId, usingChoices && selectionInput ? selectionInput : draft)
    if (!alive.current || outcome === null) return

    switch (outcome.kind) {
      case 'REPLAN':
        // 실서버는 판단 번호만 주소에 싣는다. `/replan` 이 그 번호로 서버에 다시 묻는다 —
        // 결과를 들고 가면 새로고침·뒤로 가기 때 지난 판단이 지금 것처럼 다시 뜬다.
        // Mock 은 물을 서버가 없어 결과를 들고 간다
        if (usesMock) navigate({ pathname: '/replan', search }, { state: outcome.view, viewTransition: true })
        else navigate({ pathname: '/replan', search: `?history=${lastAcceptedId.current}` }, { viewTransition: true })
        return
      case 'CONFIRM':
        // 뒤로 가면 이 화면이 다시 물어 충돌 화면으로 되돌려 보낸다. 거쳐 갈 이유가 없어 바꿔 낀다
        navigate({ pathname: '/confirm', search }, { state: outcome.view, replace: true })
        return
      case 'STAY':
        // 또 되물었다. 이제부터는 이 질문들의 답을 받는다
        if (outcome.state.kind === 'NEEDS_MORE_INFO') setAskedAgain(outcome.state.questions)
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
      <ResultFrame>
        <div className="flex flex-1 items-center justify-center">
          <HammerLoader size={48} label="하시기로 한 일을 불러오는 중" />
        </div>
      </ResultFrame>
    )
  }

  if (entry.status === 'LOAD_FAILED') {
    return (
      <ResultFrame>
        <main className="px-4 pt-2 pb-8">
          <InfoBox
            title="하시기로 한 일을 불러오지 못했어요."
            action={{
              label: '다시 불러오기',
              onClick: () => {
                setFetched({ status: 'LOADING' })
                setAttempt((count) => count + 1)
              },
            }}
          >
            연결 상태를 확인하고 다시 불러와 주세요.
          </InfoBox>
        </main>
      </ResultFrame>
    )
  }

  // 다시 불러와도 같은 답이 온다. 지금 판단을 보여주는 자리로 보낸다
  if (entry.status === 'UNRECOGNIZED') {
    return (
      <ResultFrame>
        <main className="px-4 pt-2 pb-8">
          <InfoBox title="지금 상황을 읽지 못했어요." action={goToCase}>
            지금 상황 화면에서 다시 확인해 주세요.
          </InfoBox>
        </main>
      </ResultFrame>
    )
  }

  /*
    보내는 동안은 제목과 폼 자리를 통째로 처리 화면으로 바꾼다. 적은 글은 상태에 남아 있어서,
    머무는 결과가 오면 폼이 그 글 그대로 돌아온다.
  */
  if (state.kind === 'PENDING') {
    return (
      <ResultFrame>
        {/*
          단계 줄은 화면이 실제로 아는 사건에만 맞춘다 — 접수 번호를 받으면 첫 줄이 끝나고, 그다음은
          결과가 올 때까지 둘째 줄에 머문다. 셋째 줄은 결과가 오는 순간 이 화면을 떠나므로 늘 대기다
        */}
        <ProcessingScreen
          title="답변을 정리하고 있어요"
          loaderLabel="보내주신 내용을 정리하는 중"
          steps={toResultSteps(state.accepted ? 'WAITING' : 'SENDING')}
        />
      </ResultFrame>
    )
  }

  const canSubmit = !formLocked && canRetry
  const answeredCount = questions
    ? questions.filter((question) => (answers[question] ?? '').trim() !== '').length
    : 0
  const partlyAnswered = questions !== null && answeredCount > 0 && answeredCount < questions.length
  const submitIfReady = () => {
    if (canSubmit) void handleSubmit()
  }

  return (
    <ResultFrame>
      <main className="flex flex-col gap-6 px-4 pt-2 pb-8">
        {questions ? (
          <div>
            <h1 className="text-26 font-bold">이 내용을 알려주세요</h1>
            <p className="mt-2 text-15 text-fg-neutral-muted">
              다음 할 일을 정하려면 알아야 해요. 아시는 만큼만 적어 주세요.
            </p>
          </div>
        ) : entry.ask.kind === 'RESUBMIT' ? (
          <div>
            <h1 id="result-title" className="text-26 font-bold">
              이 내용을 알려주세요
            </h1>
            <p className="mt-2 text-15 text-fg-neutral-muted">
              다음 할 일을 정하다 멈췄어요. 알려주시면 다시 정해 드려요.
            </p>
          </div>
        ) : (
          <div>
            <h1 id="result-title" className="text-26 font-bold">
              어떻게 됐나요?
            </h1>
            {/* 며칠 뒤에 들어올 수도 있다. 무엇에 대한 결과인지 먼저 상기시킨다 */}
            {entry.ask.kind === 'RESULT' && (
              <p className="mt-2 text-15 text-fg-neutral-muted">{entry.ask.nextAction.title}</p>
            )}
          </div>
        )}

        {/* 보낸 뒤 머무는 이유. 글 칸 위에 두어, 고쳐 쓰기 전에 먼저 읽히게 한다 */}
        {notice ? (
          <InfoBox tone={notice.tone} title={notice.title} action={notice.action}>
            {notice.description}
          </InfoBox>
        ) : (
          // 홈의 실패 카드에서 왔다. 무엇이 더 필요한지 먼저 보여준다. 보낸 뒤에는 위 안내가 대신한다
          entry.ask.kind === 'RESUBMIT' ? (
            <InfoBox tone="critical" title="추가 확인이 필요해요.">
              {detailText(entry.ask.notice)}
            </InfoBox>
          ) : (
            // 반영 결과에서 "다르게 이해했어요"를 누르고 왔다. 무엇을 적으면 되는지 먼저 알린다
            entry.ask.kind === 'RESULT' &&
            correcting && (
              <InfoBox title="앞서 알려주신 내용을 바로잡아 적어 주세요.">
                이미 반영한 내용과 다르면, 필요할 때 어느 쪽이 맞는지 여쭤볼게요.
              </InfoBox>
            )
          )
        )}

        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            submitIfReady()
          }}
        >
          {usingChoices ? (
            <>
              <fieldset disabled={formLocked} className="flex flex-col gap-2">
                <legend className="mb-2 text-17 font-bold">원상복구 범위</legend>
                {([
                  ['FULL', '전부 원래대로 해야 해요'], ['PARTIAL', '일부만 원상복구하면 돼요'],
                  ['NOT_REQUIRED', '원상복구가 필요 없어요'], ['UNKNOWN', '범위는 아직 몰라요'],
                ] as const).map(([value, label]) => (
                  <label key={value} className="flex items-center gap-3 rounded-14 p-3 ring-1 ring-stroke-neutral-weak">
                    <input type="radio" name="restoration_scope" value={value}
                      checked={restorationAnswer.restoration_scope === value}
                      onChange={() => setRestorationAnswer((current) => ({ ...current, restoration_scope: value }))} />
                    {label}
                  </label>
                ))}
              </fieldset>
              <fieldset disabled={formLocked} className="flex flex-col gap-2">
                <legend className="mb-2 text-17 font-bold">철거 필요 여부</legend>
                {([
                  ['REQUIRED', '철거가 필요해요'], ['NOT_REQUIRED', '철거가 필요 없어요'], ['UNKNOWN', '철거 여부는 아직 몰라요'],
                ] as const).map(([value, label]) => (
                  <label key={value} className="flex items-center gap-3 rounded-14 p-3 ring-1 ring-stroke-neutral-weak">
                    <input type="radio" name="demolition_required" value={value}
                      checked={restorationAnswer.demolition_required === value}
                      onChange={() => setRestorationAnswer((current) => ({ ...current, demolition_required: value }))} />
                    {label}
                  </label>
                ))}
              </fieldset>
            </>
          ) : questions ? (
            // 질문이 여럿이면 하나만 답해도 보낼 수 있다. 모르는 것까지 적게 하면 지어낸 답이 들어간다
            questions.map((question, index) => (
              <div key={question} className="flex flex-col gap-2">
                <p id={`question-${index}`} className="text-17 font-bold">
                  {question}
                </p>
                <AnswerTextarea
                  labelledBy={`question-${index}`}
                  rows={2}
                  placeholder="들으신 대로, 아시는 만큼 적어 주세요"
                  value={answers[question] ?? ''}
                  onChange={(value) => setAnswers((current) => ({ ...current, [question]: value }))}
                  disabled={formLocked}
                  onSubmitShortcut={submitIfReady}
                />
              </div>
            ))
          ) : (
            <AnswerTextarea
              labelledBy="result-title"
              rows={4}
              // TODO(UX): 시안의 예시라 철거 상황을 가정한다. 다른 할 일 뒤에도 같은 문구가 뜬다
              placeholder={
                entry.ask.kind === 'RESUBMIT' ? '아시는 만큼 적어 주세요' : '예: 카운터랑 싱크대만 빼래요'
              }
              value={text}
              onChange={setText}
              disabled={formLocked}
              onSubmitShortcut={submitIfReady}
            />
          )}
          {canChoose && (
            <Button variant="outline" disabled={formLocked} onClick={() => setDirectInput((current) => !current)}>
              {usingChoices ? '자세히 직접 적기' : '선택해서 답하기'}
            </Button>
          )}
          {/*
            질문이 여럿인데 일부만 답했다. 막지는 않는다 — 모르는 질문 때문에 아는 답까지 못 보내면 안 된다.
            대신 빠뜨린 것인지 한 번 보게 하고, 남은 질문은 서버가 다시 묻는다는 것을 알린다
          */}
          {partlyAnswered && <InfoBox>답하지 않은 질문은 비워 두셔도 돼요. 필요하면 다시 여쭤볼게요.</InfoBox>}
          {!usingChoices && <LengthNotice length={draft.length} withQuestions={questions !== null} />}
          <Button type="submit" disabled={!canSubmit}>
            보내기
          </Button>
        </form>
      </main>
    </ResultFrame>
  )
}

/**
 * 보낼 글이 길어지면 몇 자인지, 넘으면 줄여 달라고 알린다. 평소에는 아무것도 그리지 않는다.
 *
 * 질문에 답할 때는 물어본 질문도 함께 보내서(`toAnswerInput`), 적은 것보다 숫자가 크다. 그래서 그렇다고 적는다.
 */
function LengthNotice({ length, withQuestions }: { length: number; withQuestions: boolean }) {
  if (length <= RESULT_LENGTH_HINT_FROM) return null
  const count = `${length.toLocaleString('ko-KR')} / ${MAX_RESULT_LENGTH.toLocaleString('ko-KR')}자${
    withQuestions ? ' (물어본 질문까지 함께 세요)' : ''
  }`

  if (length > MAX_RESULT_LENGTH) {
    return (
      <InfoBox tone="critical" title={`${MAX_RESULT_LENGTH.toLocaleString('ko-KR')}자까지 보낼 수 있어요. 조금 줄여 주세요.`}>
        {count}
      </InfoBox>
    )
  }
  return (
    <p aria-live="polite" className="text-right text-14 text-fg-neutral-muted tabular-nums">
      {count}
    </p>
  )
}

/** 탭 없는 화면의 틀. 뒤로 버튼만 두고 제목은 화면 안의 큰 제목이 맡는다 */
function ResultFrame({ children }: { children: ReactNode }) {
  return (
    <div className="screen-frame mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar />
      {children}
    </div>
  )
}

interface AnswerTextareaProps {
  /** 이 칸이 무엇을 묻는지 말하는 제목의 `id` */
  labelledBy: string
  rows: number
  placeholder: string
  value: string
  onChange: (value: string) => void
  /** 보내는 중·보낼 수 없는 상태에는 잠근다. 입력한 내용은 지우지 않는다 */
  disabled: boolean
  onSubmitShortcut: () => void
}

/**
 * 들은 내용을 그대로 적는 칸. 글자는 17px다 — 16px보다 작으면 iOS Safari가 포커스할 때 화면을 확대한다.
 */
function AnswerTextarea({
  labelledBy,
  rows,
  placeholder,
  value,
  onChange,
  disabled,
  onSubmitShortcut,
}: AnswerTextareaProps) {
  return (
    <textarea
      aria-labelledby={labelledBy}
      rows={rows}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        // Enter는 줄바꿈으로 둔다. 되돌리기 수단이 없어서, 문장을 마치기 전에
        // 전송되면 잘못 해석된 상태를 취소할 방법이 없다.
        // 데스크톱에서 빠르게 보내고 싶은 경우만 Ctrl/⌘ + Enter로 받는다.
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
          event.preventDefault()
          onSubmitShortcut()
        }
      }}
      placeholder={placeholder}
      className="w-full resize-none rounded-14 px-4 py-3.5 text-17 ring-1 ring-stroke-neutral-weak outline-none ring-inset placeholder:text-fg-disabled focus:ring-2 focus:ring-fg-neutral disabled:bg-bg-neutral-weak disabled:text-fg-neutral-muted"
    />
  )
}

type NoticeAction = NonNullable<ComponentProps<typeof InfoBox>['action']>

/**
 * 머무는 안내 한 장.
 *
 * `critical` 은 실패다(판단 실패·보내기 실패). 상황이 바뀌었거나 결과를 아직 못 받은 것은
 * 실패가 아니라 알려드릴 것이라 `neutral` 로 둔다.
 */
interface NoticeProps {
  tone: 'neutral' | 'critical'
  title: string
  description: string
  action?: NoticeAction
}

/**
 * 더 적어야 할 항목을 한 문장으로. `/case` 의 `requestedText` 와 같은 모양이다.
 *
 * 항목을 문장 끝에 떼어 둔다. 앞에 두면 "범위를"·"업종을" 처럼 받침에 따라 조사가 갈린다.
 */
function detailText(requested: { fields: string[]; partial: boolean }): string {
  if (requested.fields.length === 0) {
    return '어떤 내용이 더 필요한지는 아직 확인되지 않았어요. 조금 더 자세히 적어서 다시 보내 주세요.'
  }
  return `이 내용을 조금 더 적어서 다시 보내 주세요 — ${requestedFieldsText(requested)}.`
}

/** 더 적어야 할 항목 목록. 화면 안내와 다시 보내는 글의 질문 자리가 같은 말을 쓴다 */
function requestedFieldsText({ fields, partial }: { fields: string[]; partial: boolean }): string {
  return `${fields.join(', ')}${partial ? ' 등' : ''}`
}

/** 판단 실패 이유마다의 안내. "다시 보내기"는 같은 글을 그대로 보내도 될 때만 단다 */
function failureNotice(
  notice: FailureNotice,
  { retry, goToCase }: { retry: NoticeAction; goToCase: NoticeAction },
): NoticeProps {
  switch (notice.kind) {
    case 'RETRY_AVAILABLE':
      return {
        tone: 'critical',
        title: '이번 결과로 다음 할 일을 정하지 못했어요.',
        description: '적어 주신 내용은 그대로 있어요. 같은 내용으로 다시 보내실 수 있어요.',
        action: retry,
      }

    // 더 적어야 하는 실패에 "다시 보내기"를 달면 고치지 않은 글로 같은 실패를 되풀이한다.
    // 아래 폼의 보내기 버튼이 그 자리다
    case 'NEEDS_DETAIL':
      return { tone: 'critical', title: '추가 확인이 필요해요.', description: detailText(notice) }

    case 'SERVICE_SIDE':
      return {
        tone: 'critical',
        title: '서비스에서 확인이 필요한 문제가 생겼어요.',
        description: '적어 주신 내용은 받았어요. 이 건은 저희 쪽에서 봐야 하는 문제예요.',
        action: goToCase,
      }

    case 'NO_RECOVERY':
      return {
        tone: 'critical',
        title: '이번 결과로 다음 할 일을 정하지 못했어요.',
        description: '이번 판단에 대해서는 더 해 보실 수 있는 것이 없어요.',
        action: goToCase,
      }

    case 'UNKNOWN_CAUSE':
      return {
        tone: 'critical',
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
      return failureNotice(state.notice, actions)

    case 'SEND_FAILED':
      return {
        tone: 'critical',
        title: '결과를 보내지 못했어요.',
        description: '연결이 불안정했을 수 있어요. 적어 주신 내용은 그대로 있어요.',
        action: actions.retry,
      }

    case 'SEND_REJECTED':
      return {
        tone: 'critical',
        title: '이대로는 보낼 수 없어요.',
        description: '적어 주신 내용은 그대로 있어요. 고친 뒤 다시 보내 주세요.',
      }

    case 'STALE':
      return {
        tone: 'neutral',
        title: '그사이 상황이 바뀌었어요.',
        description: '이미 접수된 결과가 있거나 새 판단이 나왔어요. 지금 상황 화면에서 확인해 주세요.',
        action: actions.goToCase,
      }

    case 'WAITED_TOO_LONG':
      return {
        tone: 'neutral',
        title: '판단 결과를 아직 받지 못했어요.',
        description: '보내 주신 결과는 접수됐어요. 끝나면 지금 상황 화면에서 보실 수 있어요.',
        action: actions.goToCase,
      }

    case 'UNRECOGNIZED':
      return {
        tone: 'neutral',
        title: '판단 결과를 읽지 못했어요.',
        description: '보내 주신 결과는 접수됐어요. 지금 상황 화면에서 다시 확인해 주세요.',
        action: actions.goToCase,
      }
  }
}
