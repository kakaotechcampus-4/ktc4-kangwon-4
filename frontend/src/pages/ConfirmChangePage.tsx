import { IconCheckmarkCircleFill } from '@karrotmarket/react-monochrome-icon'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { toResultSteps } from '../adapters/results'
import { Button } from '../components/ui/Button'
import { HammerLoader } from '../components/ui/HammerLoader'
import { InfoBox } from '../components/ui/InfoBox'
import { ProcessSteps } from '../components/ui/ProcessSteps'
import { TopBar } from '../components/ui/TopBar'
import { usesMockData } from '../lib/auth'
import { conflictConfirm, simulateConfirm } from '../mocks/resultFlow'
import type { ConfirmView, ConflictItem, ConflictSide } from '../types/view'

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
 * **실서버에서는 아직 고른 것을 보내지 않는다.** 충돌 결정을 받는 API(#108)는 머지됐지만
 * 판단(AI)에 이어지지 않았다(BE `TODO(AI팀 연동)`). 실제 충돌을 보여주고 고르게는 하되 보내는
 * 버튼만 잠근다. 보낼 곳이 이어지면 버튼만 풀면 되도록 항목마다 서버 번호(`referenceId`)를
 * 이미 들고 있다.
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

  // 보내는 동안은 결과 입력과 같은 처리 화면을 보여준다. Mock 은 접수 단계가 없어 둘째 줄부터다
  if (isPending) {
    return (
      <ConfirmFrame>
        <main className="flex flex-col gap-6 px-4 pt-2 pb-8">
          <div className="flex flex-col items-center gap-5 pt-2 text-center">
            <HammerLoader size={72} label="고르신 내용을 반영하는 중" />
            <div>
              <h1 className="text-26 font-bold">고르신 내용을 반영하고 있어요</h1>
              <p className="mt-2 text-17 text-fg-neutral-muted">사장님이 하실 일은 없어요.</p>
            </div>
          </div>
          <ProcessSteps steps={toResultSteps('WAITING')} />
          {/* 결과 입력의 처리 화면과 같은 말을 한다 */}
          <InfoBox>화면을 떠나셔도 계속 처리돼요. 끝나면 홈에서 보실 수 있어요.</InfoBox>
          <Button disabled>처리 중이에요</Button>
        </main>
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

        {/* 어느 문장 때문에 이 화면이 떴는지 모르면 무엇을 고르는지도 알 수 없다 */}
        <figure className="rounded-2xl p-4.5 ring-1 ring-stroke-neutral-muted ring-inset">
          <figcaption className="sr-only">이번에 하신 말씀</figcaption>
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

        {!canSend && (
          <InfoBox
            title="선택을 보내는 기능은 준비 중이에요."
            action={{ label: '지금 상황 보기', onClick: () => navigate({ pathname: '/case', search }) }}
          >
            고르신 내용은 아직 저장되지 않아요. 기록은 지금 그대로예요.
          </InfoBox>
        )}

        <Button disabled={!allDecided || !canSend} onClick={handleConfirm}>
          이대로 진행하기
        </Button>
      </main>
    </ConfirmFrame>
  )
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
    <div className="mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar />
      {children}
    </div>
  )
}
