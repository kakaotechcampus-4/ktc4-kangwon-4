import { IconCheckmarkFatFill, IconChevronLeftLine, IconPlusLine } from '@karrotmarket/react-monochrome-icon'
import { useId, useState, type ReactNode } from 'react'

import { Badge } from './Badge'
import { Button } from './Button'

/** 보기 하나. `emoji`는 `assets/emoji/`에서 가져온 그림 주소다 */
interface ChoiceOption {
  value: string
  label: string
  /** 목록 모양에서 보기 아래 붙는 한 줄 */
  sub?: string
  emoji?: string
  /** 목록 모양에서 보이기만 하고 고를 수 없는 보기 */
  disabled?: boolean
  /** 목록 모양에서 체크 표시 자리에 붙는 짧은 상태 글자. 고를 수 없는 이유를 적는다 */
  badge?: string
}

interface StepperRow {
  label: string
  sub: string
  value: number
  onDecrease: () => void
  onIncrease: () => void
  /** 더 늘릴 수 없을 때(상한) 더하기를 잠근다. 빼기는 0에서 저절로 잠긴다 */
  increaseDisabled?: boolean
}

/**
 * 시안의 질문 모양 네 가지.
 *
 * - `list`    큰 그림이 붙은 세로 목록. 하나만 고른다 (어떤 가게)
 * - `grid`    그림 카드 2열. 여럿 고른다 (해당하는 것 모두)
 * - `pills`   글자만 있는 세로 버튼. 하나만 고른다 (원상복구 조항, 폐업 시기)
 * - `stepper` 줄마다 빼기·더하기 (직원 수)
 */
type QuestionInput =
  | { type: 'list'; options: ChoiceOption[]; selected: string | null; onSelect: (value: string) => void }
  | { type: 'pills'; options: ChoiceOption[]; selected: string | null; onSelect: (value: string) => void }
  | { type: 'grid'; options: ChoiceOption[]; selected: string[]; onToggle: (value: string) => void }
  | { type: 'stepper'; rows: StepperRow[] }

interface QuestionScreenProps {
  /** 몇 번째 질문인지. 뒤 질문이 답에 따라 늘고 줄어 전체 수도 바뀐다 */
  position: { current: number; total: number }
  /** 비우면 뒤로 버튼을 두지 않는다. 첫 질문처럼 돌아갈 곳이 없는 경우다 */
  onBack?: () => void
  /** 제목 세 조각. 가운데만 주황으로 칠한다. 줄바꿈 자리는 `\n` */
  title: { pre: string; highlight: string; post: string }
  sub: string
  input: QuestionInput
  /** 회색 안내 상자 ("찾아볼 곳", "왜 여쭤보냐면") */
  box?: { label: string; items: { emoji: string; title: string; description: string }[] }
  /** 보기 대신 놓는 큰 그림 하나 (폐업 시기의 달력) */
  illustration?: string
  action: { label: string; onClick: () => void; disabled?: boolean; variant?: 'brand' | 'neutral' }
  /**
   * 보기 아래의 글자 버튼 하나 ("잘 모르겠어요"). 시안에 없는 자리라, 보기 안에 섞어 다른 보기와
   * 함께 골라지지 않게 따로 둔다. 아래쪽 버튼보다 약하게 그려 주요 행동을 하나로 남긴다(FE 규칙 5)
   */
  secondary?: { label: string; onClick: () => void }
  /** 아래쪽 [이전] 버튼. 시안은 마지막 질문에만 둔다 */
  onPrevious?: () => void
  /** 제목 위에 놓는 안내 하나 (보내기에 실패했을 때) */
  notice?: ReactNode
}

/** 고른 것과 안 고른 것의 테두리. 고르면 2px 진한 선, 아니면 1px 옅은 선 */
const ringOf = (on: boolean) => (on ? 'ring-2 ring-fg-neutral' : 'ring-1 ring-stroke-neutral-weak')

function CheckDot({ on, size }: { on: boolean; size: 'sm' | 'md' }) {
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center rounded-full text-fg-on-brand-solid ${
        size === 'md' ? 'size-6.5' : 'size-6'
      } ${on ? 'bg-bg-brand-solid' : 'bg-stroke-neutral-weak'}`}
    >
      <IconCheckmarkFatFill size={size === 'md' ? 13 : 12} />
    </span>
  )
}

interface PillChoicesProps<T extends string> {
  options: { value: T; label: string }[]
  selected: T | null
  onSelect: (value: T) => void
  /** 이 보기 묶음의 제목 요소 id. 화면 낭독기가 무엇을 고르는 묶음인지 읽는다 */
  labelledBy: string
  /** 보내는 중처럼 고를 수 없을 때 */
  disabled?: boolean
  className?: string
}

/**
 * 글자만 있는 세로 보기. 하나만 고른다 (진단의 원상복구 조항·폐업 시기, 결과 입력의 원상복구 답).
 *
 * 진단 질문 안에서만 쓰다가 결과 입력 화면의 선택 보기(#197)도 시안에서 같은 모양이라 꺼냈다.
 * 값의 종류(`T`)를 받아서, 서버 값을 그대로 고르는 화면이 문자열을 다시 맞춰 볼 필요가 없게 한다.
 */
export function PillChoices<T extends string>({
  options,
  selected,
  onSelect,
  labelledBy,
  disabled = false,
  className = '',
}: PillChoicesProps<T>) {
  return (
    <div role="radiogroup" aria-labelledby={labelledBy} className={`flex flex-col gap-2.5 ${className}`}>
      {options.map((option) => {
        const on = selected === option.value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => onSelect(option.value)}
            className={`press-scale h-15 w-full shrink-0 cursor-pointer rounded-14 bg-bg-layer-default px-5 text-18 active:bg-bg-transparent-pressed disabled:cursor-not-allowed disabled:text-fg-disabled ${
              on ? 'font-bold' : 'font-medium'
            } ${ringOf(on)}`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/**
 * 하나만 고르는 보기는 `radio` 역할을, 여럿 고르는 보기는 누름 상태(`aria-pressed`)를 준다.
 * 겉모양이 같은 버튼이라도 화면 낭독기가 "몇 개 중 하나를 고른 것"인지 "켜고 끈 것"인지
 * 구분해 읽을 수 있게 한다.
 */
function Choices({ input, labelledBy }: { input: QuestionInput; labelledBy: string }) {
  if (input.type === 'list') {
    return (
      <div role="radiogroup" aria-labelledby={labelledBy} className="-mx-2 flex flex-col gap-1">
        {input.options.map((option) => {
          const on = input.selected === option.value
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={on}
              disabled={option.disabled}
              onClick={() => input.onSelect(option.value)}
              className={`flex min-h-20 items-center gap-4 rounded-14 px-2 py-2.5 text-left ${
                option.disabled
                  ? 'cursor-not-allowed text-fg-disabled'
                  : 'press-scale cursor-pointer active:bg-bg-transparent-pressed'
              }`}
            >
              <span className="grid size-15 shrink-0 place-items-center rounded-full bg-bg-neutral-weak">
                {option.emoji && (
                  <img src={option.emoji} alt="" className={`size-8.5 ${option.disabled ? 'opacity-40' : ''}`} />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-19 font-bold">{option.label}</span>
                {option.sub && (
                  <span className={`mt-0.5 block text-15 ${option.disabled ? '' : 'text-fg-neutral-subtle'}`}>
                    {option.sub}
                  </span>
                )}
              </span>
              {option.badge ? <Badge>{option.badge}</Badge> : <CheckDot on={on} size="md" />}
            </button>
          )
        })}
      </div>
    )
  }

  if (input.type === 'grid') {
    return (
      <div role="group" aria-labelledby={labelledBy} className="grid grid-cols-2 gap-3">
        {input.options.map((option) => {
          const on = input.selected.includes(option.value)
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={on}
              onClick={() => input.onToggle(option.value)}
              className={`press-scale relative flex min-h-31 cursor-pointer flex-col justify-between gap-3 rounded-2xl p-4.5 text-left ${
                on ? 'bg-bg-layer-default-pressed' : 'bg-bg-layer-default'
              } ${ringOf(on)}`}
            >
              {option.emoji && <img src={option.emoji} alt="" className="size-10" />}
              <span className={`text-16 whitespace-pre-line ${on ? 'font-bold' : 'font-medium'}`}>{option.label}</span>
              <span className="absolute top-3.5 right-3.5">
                <CheckDot on={on} size="sm" />
              </span>
            </button>
          )
        })}
      </div>
    )
  }

  if (input.type === 'pills') {
    return (
      <PillChoices
        options={input.options}
        selected={input.selected}
        onSelect={input.onSelect}
        labelledBy={labelledBy}
        className="-mt-2"
      />
    )
  }

  return (
    <div className="flex flex-col">
      {input.rows.map((row) => (
        <div key={row.label} className="flex min-h-16 items-center gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-18">{row.label}</p>
            <p className="mt-0.5 text-14 text-fg-neutral-subtle">{row.sub}</p>
          </div>
          <button
            type="button"
            aria-label={`${row.label} 빼기`}
            disabled={row.value === 0}
            onClick={row.onDecrease}
            className="grid size-10 cursor-pointer place-items-center rounded-full bg-bg-layer-default text-fg-neutral ring-1 ring-stroke-neutral-weak ring-inset disabled:cursor-not-allowed disabled:text-stroke-neutral-weak"
          >
            <span aria-hidden="true" className="h-0.5 w-3.5 rounded-xs bg-current" />
          </button>
          {/* 숫자가 바뀌면 화면 낭독기가 새 값을 읽는다 */}
          <output aria-live="polite" className="min-w-12 text-center text-18 font-bold tabular-nums">
            {row.value}명
          </output>
          <button
            type="button"
            aria-label={`${row.label} 더하기`}
            disabled={row.increaseDisabled}
            onClick={row.onIncrease}
            className="grid size-10 cursor-pointer place-items-center rounded-full bg-bg-layer-default text-fg-neutral ring-1 ring-stroke-neutral-weak ring-inset disabled:cursor-not-allowed disabled:text-stroke-neutral-weak"
          >
            <IconPlusLine size={18} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  )
}

/**
 * 상황 진단 질문 한 장 (시안 M01).
 *
 * 무엇을 물을지, 고른 답을 어디에 둘지는 모른다. 받은 제목·보기·버튼을 시안 모양대로
 * 그리기만 한다. 질문 순서와 답 저장은 진단 화면(`CaseCreatePage`)이 맡는다.
 *
 * 놓는 순서는 시안을 따른다: 목록·그리드 → 안내 상자 → 큰 그림 → 버튼 보기·스테퍼.
 * 그래서 원상복구 질문은 "찾아볼 곳" 상자가 보기 **위**에 온다.
 *
 * 뒤로 버튼은 시안의 44px 대신 48px다(`TopBar`와 같은 이유, UI 가이드라인).
 *
 * 질문이 바뀌면 내용이 옆에서 조금 밀려 들어온다. 번호가 커졌으면 오른쪽에서(앞으로), 작아졌으면
 * 왼쪽에서(뒤로) 온다. [이전]·뒤로 버튼·브라우저 뒤로 가기를 따로 가르지 않고 번호로만 본다.
 * 처음 연 질문은 움직이지 않는다 — 새로고침이나 주소로 들어왔을 때 옆에서 날아오면 이상하다.
 */
export function QuestionScreen({
  position,
  onBack,
  title,
  sub,
  input,
  box,
  illustration,
  action,
  secondary,
  onPrevious,
  notice,
}: QuestionScreenProps) {
  const titleId = useId()
  const optionsFirst = input.type === 'list' || input.type === 'grid'

  // 앞에 그린 질문 번호를 들고 있다가, 번호가 바뀐 그 그리기에서 방향을 정한다
  const [shown, setShown] = useState<{ at: number; enter: 'forward' | 'back' | null }>({
    at: position.current,
    enter: null,
  })
  if (shown.at !== position.current) {
    setShown({ at: position.current, enter: position.current > shown.at ? 'forward' : 'back' })
  }
  const enter =
    shown.enter === 'forward'
      ? 'motion-safe:animate-step-forward'
      : shown.enter === 'back'
        ? 'motion-safe:animate-step-back'
        : ''

  const boxNode: ReactNode = box && (
    <div className="flex flex-col gap-4 rounded-2xl bg-bg-neutral-weak p-5">
      <p className="text-15 font-medium text-fg-neutral-muted">{box.label}</p>
      {box.items.map((item) => (
        <div key={item.title} className="flex items-center gap-4">
          <span className="grid size-14 shrink-0 place-items-center rounded-full bg-bg-layer-default">
            <img src={item.emoji} alt="" className="size-7.5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-17 font-bold">{item.title}</p>
            <p className="mt-0.5 text-15 text-fg-neutral-muted">{item.description}</p>
          </div>
        </div>
      ))}
    </div>
  )

  return (
    <div className="screen-frame mx-auto flex h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <header className="flex h-14 shrink-0 items-center pr-4 pl-1">
        {onBack ? (
          <button
            type="button"
            aria-label="뒤로"
            onClick={onBack}
            className="grid size-12 cursor-pointer place-items-center rounded-lg text-fg-neutral active:bg-bg-transparent-pressed"
          >
            <IconChevronLeftLine size={26} aria-hidden="true" />
          </button>
        ) : (
          <span className="size-12" />
        )}
        <span className="flex-1" />
        <span className="flex h-8 items-center rounded-full px-3 text-14 font-bold text-fg-neutral-muted tabular-nums ring-1 ring-stroke-neutral-weak ring-inset">
          <span className="sr-only">질문 </span>
          {position.current} / {position.total}
        </span>
      </header>

      {/* 질문마다 새로 그려야 움직임이 처음부터 다시 돈다. 스크롤도 맨 위로 돌아간다 */}
      <main
        key={position.current}
        className={`flex min-h-0 flex-1 flex-col gap-8 overflow-y-auto px-5 pt-4 pb-4 ${enter}`}
      >
        {notice && <div className="motion-safe:animate-fade-in-short">{notice}</div>}
        <div>
          <h1 id={titleId} className="text-26 font-bold whitespace-pre-line">
            {title.pre}
            <span className="text-fg-brand-contrast">{title.highlight}</span>
            {title.post}
          </h1>
          <p className="mt-2.5 text-17 text-fg-neutral-muted">{sub}</p>
        </div>

        {optionsFirst && <Choices input={input} labelledBy={titleId} />}
        {boxNode}
        {illustration && (
          <span className="-my-1 grid size-45 shrink-0 place-items-center self-center rounded-full bg-bg-brand-weak">
            <img src={illustration} alt="" className="size-26" />
          </span>
        )}
        {!optionsFirst && <Choices input={input} labelledBy={titleId} />}
        {secondary && (
          <button
            type="button"
            onClick={secondary.onClick}
            className="-mt-4 h-12 cursor-pointer self-center rounded-lg px-3 text-16 font-medium text-fg-neutral-muted underline underline-offset-4 active:bg-bg-transparent-pressed"
          >
            {secondary.label}
          </button>
        )}
      </main>

      <div className="flex shrink-0 gap-2 px-4 pt-3 pb-8.5">
        {onPrevious && (
          <Button variant="outline" onClick={onPrevious} className="flex-1">
            이전
          </Button>
        )}
        <Button
          variant={action.variant ?? 'brand'}
          disabled={action.disabled}
          onClick={action.onClick}
          className="flex-2"
        >
          {action.label}
        </Button>
      </div>
    </div>
  )
}
