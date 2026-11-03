import { type ReactNode, useEffect, useId, useRef } from 'react'

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
 * 올라오는 움직임은 8번 PR(화면 전환)에서 붙인다.
 */
export function BottomSheet({ open, onClose, title, description, children }: BottomSheetProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (open && !element.open) element.showModal()
    if (!open && element.open) element.close()
  }, [open])

  return (
    <dialog
      ref={dialog}
      aria-labelledby={titleId}
      // Esc 는 브라우저가 먼저 닫는다. 쓰는 쪽의 `open` 도 같이 내려야 다음에 다시 열 수 있다
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      className="mx-auto mt-auto mb-0 w-full max-w-[402px] rounded-t-3xl bg-bg-layer-default p-0 text-fg-neutral backdrop:bg-bg-overlay"
    >
      <div className="flex flex-col gap-4 px-5 pt-3 pb-8.5">
        <span aria-hidden="true" className="mx-auto h-1 w-10 rounded-full bg-bg-neutral-weak" />
        <div>
          <h2 id={titleId} className="text-20 font-bold">
            {title}
          </h2>
          {description && <p className="mt-1 text-15 text-fg-neutral-muted">{description}</p>}
        </div>
        {children}
      </div>
    </dialog>
  )
}
