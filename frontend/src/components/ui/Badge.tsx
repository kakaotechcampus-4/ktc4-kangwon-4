import type { ReactNode } from 'react'

/**
 * 배지 색.
 *
 * - `brand`    진행 중인 것, 사장님이 할 일
 * - `critical` 확인이 필요한 것
 * - `neutral`  그 밖의 상태
 */
type BadgeTone = 'brand' | 'critical' | 'neutral'

interface BadgeProps {
  tone?: BadgeTone
  /** 색만으로 상태를 전달하지 않는다. 배지에는 항상 글자가 들어간다 */
  children: ReactNode
}

const TONE_STYLE: Record<BadgeTone, string> = {
  brand: 'bg-bg-brand-weak text-fg-brand-contrast',
  critical: 'bg-bg-critical-weak text-fg-critical-contrast',
  neutral: 'bg-bg-neutral-weak text-fg-neutral-muted',
}

export function Badge({ tone = 'neutral', children }: BadgeProps) {
  return (
    <span
      className={`inline-flex h-6 shrink-0 items-center rounded-md px-2 text-12 font-medium whitespace-nowrap ${TONE_STYLE[tone]}`}
    >
      {children}
    </span>
  )
}
