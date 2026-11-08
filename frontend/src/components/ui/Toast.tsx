import { IconSparkle2Fill, IconXmarkLine } from '@karrotmarket/react-monochrome-icon'
import { useEffect } from 'react'
import { Link } from 'react-router'

import { prefersReducedMotion } from '../../lib/reducedMotion'

/** 저절로 닫히기까지의 시간. 한 줄과 버튼 하나를 읽고 누를 만큼 둔다 */
export const TOAST_DURATION_MS = 8_000

interface ToastProps {
  /** 무슨 일이 있었는지 한 줄 */
  message: string
  /** 이어서 볼 화면으로 가는 버튼 이름 */
  actionLabel: string
  /** 버튼을 누르면 갈 주소 */
  to: string
  onClose: () => void
}

/**
 * 화면 위쪽에 잠깐 뜨는 알림 띠. 지금 보는 화면을 가리지 않고, 이어서 볼 곳으로 가는 버튼 하나를 둔다.
 *
 * `role="status"` 라 화면 읽기 프로그램이 하던 일을 끊지 않고 읽는다.
 *
 * 저절로 닫힌다. 다만 기기에서 "동작 줄이기"를 켰으면 닫지 않는다 — 읽는 도중에 사라진다.
 * 닫기 버튼은 늘 있다.
 */
export function Toast({ message, actionLabel, to, onClose }: ToastProps) {
  useEffect(() => {
    if (prefersReducedMotion()) return
    const timer = window.setTimeout(onClose, TOAST_DURATION_MS)
    return () => window.clearTimeout(timer)
  }, [onClose])

  return (
    <div className="pointer-events-none fixed inset-x-0 top-2 z-50 mx-auto max-w-[402px] px-3">
      <div
        role="status"
        className="pointer-events-auto flex items-center gap-2 rounded-xl bg-bg-layer-default py-2 pr-1 pl-3 shadow-card ring-1 ring-stroke-neutral-weak"
      >
        <IconSparkle2Fill size={20} aria-hidden="true" className="shrink-0 text-fg-brand" />
        <p className="min-w-0 flex-1 text-16 font-medium">{message}</p>
        <Link
          to={to}
          onClick={onClose}
          className="flex h-12 shrink-0 items-center rounded-lg px-3 text-16 font-bold text-fg-brand active:bg-bg-transparent-pressed"
        >
          {actionLabel}
        </Link>
        <button
          type="button"
          aria-label="알림 닫기"
          onClick={onClose}
          className="grid size-12 shrink-0 cursor-pointer place-items-center rounded-lg text-fg-neutral-muted active:bg-bg-transparent-pressed"
        >
          <IconXmarkLine size={20} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}
