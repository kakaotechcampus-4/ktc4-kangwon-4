import { animate, m, useMotionValue, useReducedMotion } from 'motion/react'
import { type PointerEvent, type ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'

interface BottomSheetProps {
  /** 열려 있는지. 여닫기는 쓰는 쪽이 정한다 */
  open: boolean
  /** 바깥을 누르거나 Esc 로 닫을 때. 쓰는 쪽이 `open` 을 내린다 */
  onClose: () => void
  /** 시트 맨 위의 굵은 한 줄. 화면 읽기 프로그램이 이 시트의 이름으로 읽는다 */
  title: string
  /** 제목 아래 한 줄 (예: "여러 장을 한꺼번에 올려도 돼요.") */
  description?: string
  children: ReactNode
}

/** 올라올 때는 용수철로 살짝 넘쳤다 멈춘다. 내려갈 때는 넘치지 않고 빠르게 빠진다(iOS 시트 곡선) */
const SHEET_IN = { type: 'spring', visualDuration: 0.4, bounce: 0.15 } as const
const SHEET_OUT = { duration: 0.25, ease: [0.32, 0.72, 0, 1] } as const

/** 손을 놓았을 때 이만큼 넘게 끌어 내렸거나, 이 속도(px/초)보다 빠르게 튕겼으면 닫는다 */
const CLOSE_DISTANCE = 100
const CLOSE_VELOCITY = 500
/** 위로 끌어 올릴 때 따라오는 한계(px). 아래 덧댄 흰 바탕(`shadow-[0_120px…]`)보다 작아야 한다 */
const MAX_LIFT = 40

/**
 * 아래에서 올라오는 시트 (시안의 서류 올리기 · 도움말 시트).
 *
 * `<dialog>` 의 `showModal()` 로 띄운다. 직접 겹쳐 그리면 뒤 화면으로 키보드가 새 나가고,
 * Esc 닫기 · 포커스 가두기 · 뒤 화면 막기를 손으로 맞춰야 한다. 브라우저가 이미 해 주는 것을
 * 쓴다(인계 문서 "시트는 `<dialog>`").
 *
 * 바깥(어두운 곳)을 누르면 닫는다. `<dialog>` 는 바깥을 눌러도 그 자신이 눌린 것으로 잡혀서,
 * 눌린 것이 시트 안쪽이 아니라 `<dialog>` 자체일 때만 닫는다.
 *
 * **움직임.** 열면 용수철처럼 올라오고, 닫으면 내려간 **뒤에** `<dialog>` 를 닫는다. 그래서 Esc 도
 * 브라우저가 바로 닫지 못하게 막고(`cancel`) 쓰는 쪽에 닫기를 알린다. 손잡이와 제목 줄을 아래로
 * 끌면 손을 따라 내려오고, 많이 끌었거나 빠르게 튕겼으면 닫는다. 아니면 제자리로 돌아온다.
 * 끄는 자리를 위쪽으로만 둔 것은 시트 안의 목록·입력칸을 스크롤할 때 시트가 끌려 내려오지 않게 하려는 것이다.
 *
 * 높이는 Motion 의 움직이는 값(`y`) 하나로 옮긴다. 이 값은 Motion 기능 묶음(`lib/motionFeatures`)을
 * 아직 받지 못했어도 움직이므로, 그 사이에 닫아도 시트가 닫히지 않고 남는 일이 없다.
 * "동작 줄이기"를 켰으면 움직이지 않고 바로 열고 닫는다.
 *
 * 시트 아래에는 같은 흰색을 화면 밖까지 길게 덧대 둔다(같은 색 그림자). 시트는 화면 바닥에 붙어 있어서,
 * 용수철로 살짝 넘치거나 위로 끌어 올리면 그만큼 아래에 틈이 생겨 뒤의 어두운 막이 비친다(11/04 시우님 확인).
 */
export function BottomSheet({ open, onClose, title, description, children }: BottomSheetProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const y = useMotionValue(0)
  const reduceMotion = useReducedMotion()
  const drag = useRef<{ startY: number; startOffset: number } | null>(null)

  /*
    닫히는 동안에도 마지막 내용을 그린다. 쓰는 쪽이 서류 같은 값으로 여닫으면(`open={document !== null}`)
    닫는 순간 제목·내용도 함께 비어서, 내려가는 시트가 빈 상자로 보인다.
  */
  const [kept, setKept] = useState({ title, description, children })
  if (open && (kept.title !== title || kept.description !== description || kept.children !== children)) {
    setKept({ title, description, children })
  }
  const shown = open ? { title, description, children } : kept

  // 여는 것은 그리기 직후에 한다. 한 프레임이라도 제자리에 그려진 뒤 내려가면 번쩍인다
  useLayoutEffect(() => {
    const element = dialog.current
    if (!element || !open) return
    if (!element.open) {
      element.showModal()
      y.jump(reduceMotion ? 0 : element.offsetHeight)
    }
    const animation = reduceMotion ? (y.jump(0), null) : animate(y, 0, SHEET_IN)
    return () => animation?.stop()
  }, [open, reduceMotion, y])

  useEffect(() => {
    const element = dialog.current
    if (!element || open || !element.open) return
    if (reduceMotion) {
      element.close()
      return
    }
    const animation = animate(y, element.offsetHeight, SHEET_OUT)
    let stopped = false
    animation.then(() => {
      if (!stopped) element.close()
    })
    // 내려가는 중에 다시 열면 닫지 않는다. 위 여는 쪽이 제자리로 되돌린다
    return () => {
      stopped = true
      animation.stop()
    }
  }, [open, reduceMotion, y])

  function startDrag(event: PointerEvent<HTMLDivElement>) {
    if (!open) return
    drag.current = { startY: event.clientY, startOffset: y.get() }
    // 손가락이 시트 밖으로 나가도 계속 따라오게 잡아 둔다(테스트 환경 jsdom 에는 없다)
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  function moveDrag(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return
    const offset = drag.current.startOffset + event.clientY - drag.current.startY
    // 위로는 조금만, 최대 `MAX_LIFT` 까지 따라온다(고무줄). 시트가 화면 위로 떠오르지 않게
    y.set(offset < 0 ? Math.max(offset * 0.2, -MAX_LIFT) : offset)
  }

  function endDrag() {
    if (!drag.current) return
    drag.current = null
    if (y.get() > CLOSE_DISTANCE || y.getVelocity() > CLOSE_VELOCITY) onClose()
    else animate(y, 0, { ...SHEET_IN, velocity: y.getVelocity() })
  }

  return (
    <m.dialog
      ref={dialog}
      aria-labelledby={titleId}
      style={{ y }}
      // Esc 는 브라우저가 바로 닫는다. 막고 쓰는 쪽에 알려서, 내려가는 움직임 뒤에 닫히게 한다
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      // 그래도 브라우저가 먼저 닫았으면(Esc 를 연달아 누르면 막을 수 없다) 쓰는 쪽도 내려야 다음에 다시 열 수 있다
      onClose={() => {
        if (open) onClose()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      data-closing={open ? undefined : ''}
      className="mx-auto mt-auto mb-0 w-full max-w-[402px] rounded-t-3xl bg-bg-layer-default p-0 shadow-[0_120px_0_0_var(--color-bg-layer-default)] text-fg-neutral backdrop:bg-bg-overlay backdrop:transition-opacity backdrop:duration-300 data-closing:backdrop:opacity-0 starting:open:backdrop:opacity-0 motion-reduce:backdrop:transition-none"
    >
      <div className="flex flex-col gap-4 px-5 pt-3 pb-8.5">
        <div
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          className="-mx-5 -mt-3 flex cursor-grab touch-none flex-col gap-4 px-5 pt-3 active:cursor-grabbing"
        >
          <span aria-hidden="true" className="mx-auto h-1 w-10 rounded-full bg-bg-neutral-weak" />
          <div>
            <h2 id={titleId} className="text-20 font-bold">
              {shown.title}
            </h2>
            {shown.description && <p className="mt-1 text-15 text-fg-neutral-muted">{shown.description}</p>}
          </div>
        </div>
        {shown.children}
      </div>
    </m.dialog>
  )
}
