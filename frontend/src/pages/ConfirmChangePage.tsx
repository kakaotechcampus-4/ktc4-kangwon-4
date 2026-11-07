import { IconCheckmarkCircleFill } from '@karrotmarket/react-monochrome-icon'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { toDecisionRequest, toResultSteps, toSubmitOutcome } from '../adapters/results'
import { Button } from '../components/ui/Button'
import { InfoBox } from '../components/ui/InfoBox'
import { ProcessingScreen } from '../components/ui/ProcessingScreen'
import { TopBar } from '../components/ui/TopBar'
import { ApiError, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { submitDecision, waitForResult } from '../lib/resultSubmit'
import { conflictConfirm, simulateConfirm } from '../mocks/resultFlow'
import type { CaseConflictsDecisionRequest } from '../types/api'
import type { ConfirmView, ConflictItem, ConflictSide, SubmitOutcome } from '../types/view'

/**
 * ④ 충돌 확인.
 *
 * 기존 기록과 새 입력이 어긋날 때만 들른다. 정상 경로는 ③에서 ⑤로 바로 간다.
 *
 * **시안에 이 화면이 없다.** 처리 화면(M05c)의 "이렇게 이해했어요" 상자 — 사장님 글을 인용하고
 * 항목과 값을 줄로 놓는 모양 — 를 빌려 만들었다.
 *
 * `rollback` API가 계약에서 빠져, 값을 되돌릴 수 있는 지점은 여기뿐이다.
 * 그래서 한 항목이라도 고르지 않으면 진행할 수 없게 한다.
 *
 * 고른 것은 `POST /cases/results/decision` 으로 보내고, 결과 입력과 같은 길(`waitForResult`)로
 * 판단을 기다린다(#136). 결과에 따라 옮기는 곳은 `settle` 에 모았다.
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
  const [sending, setSending] = useState<SendState>({ kind: 'IDLE' })
  /** 판단을 기다리는 중이면 그 기다림을 끊는 손잡이. 화면을 떠날 때 당긴다 */
  const waiting = useRef<AbortController | null>(null)

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
      waiting.current?.abort()
    }
  }, [])

  if (!view) return <Navigate to={{ pathname: '/', search }} replace />
  // 고를 것이 없으면 이 화면의 존재 이유가 없다. 서버가 빈 목록을 보내도 막다른 골목이
  // 되지 않게 진입 분기로 돌린다 — 거기서 지금 상태에 맞는 화면을 다시 고른다.
  if (view.conflicts.length === 0) return <Navigate to={{ pathname: '/', search }} replace />

  const { rawInput, conflicts } = view
  const decision = toDecisionRequest(conflicts, choices)
  const goToCase = { label: '지금 상황 보기', onClick: () => navigate({ pathname: '/case', search }) }
  const notice = sendNotice(sending, goToCase)
  // 접수된 뒤 결과를 못 받았거나 보낼 수 없는 요청이었으면, 다시 눌러도 같은 답이 온다
  const locked = sending.kind === 'STUCK'

  /*
   * 이동은 모두 `replace` 다. 이미 보낸 결정 화면으로 뒤로 돌아가 같은 결정을 다시 제출하는
   * 일을 막는다 — 표시만 어긋나는 다른 화면과 달리 서버 상태를 바꾸는 요청이다.
   */
  const leave = (to: string) => navigate(to, { replace: true })

  /** 판단이 끝난 결과에 따라 옮긴다. 머무는 경우만 이 화면의 상태를 바꾼다 */
  function settle(outcome: SubmitOutcome, acceptedId: number) {
    switch (outcome.kind) {
      // 반영 결과는 판단 번호로 다시 묻는다. 결과를 들고 가면 새로고침 때 지난 판단이 지금 것처럼 뜬다
      case 'REPLAN':
        // `from=confirm` 은 반영 결과가 "이해했어요" 대신 고른 것을 반영했다고 말하게 하는 표시다
        return leave(`/replan?history=${acceptedId}&from=confirm`)

      // AI에는 결정 뒤 또 충돌이 나는 경로가 없다(#136 승준님). 그래도 오면 새 충돌을 처음부터 고른다.
      // 고른 것은 비우지 않아도 된다 — 서버 번호로 열쇠를 만들어(`toConflicts`) 앞의 선택이
      // 새 충돌에 붙지 않는다
      case 'CONFIRM':
        setSending({ kind: 'IDLE' })
        return navigate({ pathname: '/confirm', search }, { state: outcome.view, replace: true })

      case 'STAY':
        switch (outcome.state.kind) {
          // 고른 값은 저장됐고 되물을 것이 남았다. 결과 입력이 질문 답하기로 연다
          case 'NEEDS_MORE_INFO':
            return leave('/results')

          // 실패하면 서버가 아무것도 바꾸지 않아 충돌이 그대로 남는다. 다시 해볼 수 있는 실패만
          // 여기 머물며 같은 선택으로 다시 보내게 한다. 나머지는 다시 보내도 풀리지 않아 홈이 안내한다
          case 'FAILED':
            if (outcome.state.notice.kind === 'RETRY_AVAILABLE') return setSending({ kind: 'RETRY' })
            return leave('/case')

          default:
            return setSending({ kind: 'STUCK', reason: 'UNRECOGNIZED' })
        }

      default: {
        // 갈래가 늘면 여기서 컴파일이 막힌다
        const unhandled: never = outcome
        return unhandled
      }
    }
  }

  /**
   * 실제 서버에 보내고 판단을 기다린다.
   *
   * 보내기와 기다리기의 실패를 따로 받는다. 보내다 실패하면 서버가 받았는지조차 모르고,
   * 기다리다 실패하면 접수는 된 것이라 사장님에게 할 말이 다르다(결과 입력과 같은 규칙).
   */
  async function sendToServer(body: CaseConflictsDecisionRequest) {
    setSending({ kind: 'PENDING', accepted: false })

    let acceptedId: number
    try {
      acceptedId = await submitDecision(body)
    } catch (error: unknown) {
      if (!alive.current) return
      if (error instanceof UnauthorizedError) return leave('/login')
      // 남은 충돌 없음·직전 결정 판단 중·이미 해결(409), Case 없음(404) — 이 화면이 아는 충돌이
      // 낡았다. 결과 입력이 지금 상태를 다시 물어 맞는 화면으로 보낸다
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) return leave('/results')
      // 그 밖의 4xx 는 요청을 잘못 만든 것이라 다시 보내도 같다
      if (error instanceof ApiError && error.status < 500) return setSending({ kind: 'STUCK', reason: 'REJECTED' })
      return setSending({ kind: 'SEND_FAILED' })
    }

    if (!alive.current) return
    setSending({ kind: 'PENDING', accepted: true })

    const controller = new AbortController()
    waiting.current = controller
    try {
      const waited = await waitForResult(acceptedId, { signal: controller.signal })
      switch (waited.kind) {
        case 'SETTLED':
          return settle(toSubmitOutcome(waited.body), acceptedId)
        // 그사이 다른 판단이 생겼다(다른 탭 등)
        case 'STALE':
          return leave('/results')
        case 'WAITED_TOO_LONG':
          return setSending({ kind: 'STUCK', reason: 'WAITED_TOO_LONG' })
      }
    } catch (error: unknown) {
      if (controller.signal.aborted || !alive.current) return
      if (error instanceof UnauthorizedError) return leave('/login')
      // 다시 물어도 답이 같은 4xx 다. 접수는 됐으니 홈에서 확인하게 한다
      setSending({ kind: 'STUCK', reason: 'UNRECOGNIZED' })
    } finally {
      waiting.current = null
    }
  }

  async function handleConfirm() {
    // 버튼이 다 고르기 전에는 잠겨 있지만, 반쪽 요청이 나가지 않게 여기서도 거른다
    if (decision === null) return

    if (!usesMock) return sendToServer(decision)

    // Mock 은 접수 단계가 없어 둘째 줄부터다
    setSending({ kind: 'PENDING', accepted: true })
    const replan = await simulateConfirm(choices)
    if (!alive.current) return
    const params = new URLSearchParams(search)
    params.set('from', 'confirm')
    navigate({ pathname: '/replan', search: `?${params.toString()}` }, { state: replan, replace: true })
  }

  // 보내는 동안은 결과 입력과 같은 처리 화면을 보여준다
  if (sending.kind === 'PENDING') {
    return (
      <ConfirmFrame>
        <ProcessingScreen
          title="고르신 내용을 반영하고 있어요"
          loaderLabel="고르신 내용을 반영하는 중"
          steps={toResultSteps(sending.accepted ? 'WAITING' : 'SENDING', 'DECISION')}
        />
      </ConfirmFrame>
    )
  }

  return (
    <ConfirmFrame>
      <main className="flex flex-col gap-6 px-4 pt-2 pb-8">
        <div>
          <h1 className="text-26 font-bold">어느 쪽이 맞나요?</h1>
          <p className="mt-2 text-15 text-fg-neutral-muted">
            기록과 다른 부분이 있어요. 맞는 쪽을 골라 주세요.
          </p>
        </div>

        {/* 어떤 새 내용과 기록이 다른지 알 수 있도록 확인할 내용을 함께 보여준다 */}
        <figure className="rounded-2xl p-4.5 ring-1 ring-stroke-neutral-muted ring-inset">
          <figcaption className="sr-only">새로 확인한 내용</figcaption>
          <blockquote className="text-15 text-fg-neutral-subtle">“{rawInput}”</blockquote>
        </figure>

        {conflicts.map((conflict) => (
          <ConflictChoice
            key={conflict.key}
            item={conflict}
            selected={choices[conflict.key] ?? null}
            onSelect={(side) => setChoices((current) => ({ ...current, [conflict.key]: side }))}
          />
        ))}

        {notice && (
          <InfoBox tone={notice.tone} title={notice.title} action={notice.action}>
            {notice.description}
          </InfoBox>
        )}

        {/* 실패해 머물러도 고른 것은 그대로다. 다시 보내는 것도 이 버튼이다 */}
        <Button disabled={decision === null || locked} onClick={handleConfirm}>
          이대로 진행하기
        </Button>
      </main>
    </ConfirmFrame>
  )
}

/** 고른 것을 보내는 상태 */
type SendState =
  /** 아직 보내지 않았다 */
  | { kind: 'IDLE' }
  /** 보내는 중이다. `accepted` 면 접수 번호를 받고 판단을 기다린다 */
  | { kind: 'PENDING'; accepted: boolean }
  /** 판단이 실패했고 다시 해볼 수 있다. 충돌은 그대로 남아 있다 */
  | { kind: 'RETRY' }
  /** 보내다 끊겼다. 서버가 받았는지 모른다 */
  | { kind: 'SEND_FAILED' }
  /**
   * 다시 눌러도 같은 답이 온다 — 서버가 받지 않는 요청이었거나(`REJECTED`), 접수는 됐지만
   * 결과를 끝내 못 받았거나(`WAITED_TOO_LONG`) 읽지 못했다(`UNRECOGNIZED`). 홈에서 확인하게 한다
   */
  | { kind: 'STUCK'; reason: 'REJECTED' | 'WAITED_TOO_LONG' | 'UNRECOGNIZED' }

type NoticeAction = { label: string; onClick: () => void }

/**
 * 머무는 상태마다 띄울 안내. 안내할 것이 없으면 `null`.
 *
 * 결과 입력의 `stayNotice` 와 같은 나눔이고, 문구만 "적어 주신 글"이 아니라 "고르신 것"으로 바꿨다.
 * 다시 보낼 수 있는 경우에는 안내에 버튼을 달지 않는다 — 아래 [이대로 진행하기]가 그 자리다.
 */
function sendNotice(
  sending: SendState,
  goToCase: NoticeAction,
): { tone: 'critical' | 'neutral'; title: string; description: string; action?: NoticeAction } | null {
  switch (sending.kind) {
    case 'IDLE':
    case 'PENDING':
      return null

    case 'RETRY':
      return {
        tone: 'critical',
        title: '고르신 내용을 반영하지 못했어요.',
        description: '기록은 그대로예요. 같은 선택으로 다시 보내실 수 있어요.',
      }

    case 'SEND_FAILED':
      return {
        tone: 'critical',
        title: '고르신 내용을 보내지 못했어요.',
        description: '연결이 불안정했을 수 있어요. 고르신 것은 그대로 있어요.',
      }

    case 'STUCK':
      switch (sending.reason) {
        case 'REJECTED':
          return {
            tone: 'neutral',
            title: '지금은 이 선택을 보낼 수 없어요.',
            description: '지금 상황 화면에서 다시 확인해 주세요.',
            action: goToCase,
          }
        case 'WAITED_TOO_LONG':
          return {
            tone: 'neutral',
            title: '반영 결과를 아직 받지 못했어요.',
            description: '고르신 내용은 접수됐어요. 끝나면 지금 상황 화면에서 보실 수 있어요.',
            action: goToCase,
          }
        case 'UNRECOGNIZED':
          return {
            tone: 'neutral',
            title: '반영 결과를 읽지 못했어요.',
            description: '고르신 내용은 접수됐어요. 지금 상황 화면에서 다시 확인해 주세요.',
            action: goToCase,
          }
      }
  }
}

interface ConflictChoiceProps {
  item: ConflictItem
  /** 아직 고르지 않았으면 null. 기본 선택을 두지 않는다 */
  selected: ConflictSide | null
  onSelect: (side: ConflictSide) => void
}

/**
 * 어긋난 항목 하나를 두 칸으로 놓고 고르게 한다.
 *
 * 어느 쪽도 미리 선택해두지 않는다. 기본값이 있으면 사용자가 읽지 않고 넘길 수 있고,
 * 그러면 서버가 자동으로 고른 것과 다를 바가 없다. 충돌은 항상 사용자 확인을
 * 거친다는 것이 이 제품의 약속이다.
 */
function ConflictChoice({ item, selected, onSelect }: ConflictChoiceProps) {
  return (
    <section className="flex flex-col gap-2.5">
      <h2 className="text-17 font-bold">{item.label}</h2>
      <ChoiceButton
        caption="지금 기록"
        value={item.storedValue}
        pressed={selected === 'STORED'}
        onClick={() => onSelect('STORED')}
      />
      <ChoiceButton
        caption="이번에 말씀하신 것"
        value={item.incomingValue}
        pressed={selected === 'INCOMING'}
        onClick={() => onSelect('INCOMING')}
      />
    </section>
  )
}

interface ChoiceButtonProps {
  caption: string
  value: string
  pressed: boolean
  onClick: () => void
}

function ChoiceButton({ caption, value, pressed, onClick }: ChoiceButtonProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`flex min-h-16 cursor-pointer items-center gap-3 rounded-14 px-4 py-3.5 text-left ring-inset focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stroke-brand-solid ${
        pressed ? 'bg-bg-brand-weak ring-2 ring-stroke-brand-solid' : 'ring-1 ring-stroke-neutral-weak'
      }`}
    >
      <span className="flex-1">
        <span className="block text-14 text-fg-neutral-muted">{caption}</span>
        <span className="mt-0.5 block text-17 font-bold">{value}</span>
      </span>
      {pressed && <IconCheckmarkCircleFill aria-hidden="true" className="size-6 shrink-0 text-fg-brand" />}
    </button>
  )
}

/** 탭 없는 화면의 틀. 뒤로 버튼만 두고 제목은 화면 안의 큰 제목이 맡는다 */
function ConfirmFrame({ children }: { children: ReactNode }) {
  return (
    <div className="screen-frame mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar />
      {children}
    </div>
  )
}
