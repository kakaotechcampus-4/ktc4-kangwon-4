import {
  IconExclamationmarkCircleFill,
  IconILowercaseSerifCircleFill,
} from '@karrotmarket/react-monochrome-icon'
import type { ReactNode } from 'react'

/**
 * 안내의 무게.
 *
 * - `neutral`  알아두실 것
 * - `critical` 실패했거나 사장님이 확인하셔야 하는 것
 */
type InfoTone = 'neutral' | 'critical'

interface InfoBoxProps {
  tone?: InfoTone
  /** 굵게 쓰는 한 줄. 없으면 본문만 쓴다 */
  title?: string
  children?: ReactNode
  /** 안내에서 바로 할 수 있는 행동 하나. 주 버튼과 겹치지 않게 글자 버튼으로 둔다 */
  action?: { label: string; onClick: () => void; disabled?: boolean }
}

/**
 * 회색 바탕의 안내 상자 (시안 M07 "리본은 대신 제출하지 않아요" 상자).
 *
 * 바탕은 무게와 상관없이 회색이고 아이콘 색만 바꾼다. 빨간 바탕을 쓰면 이 상자가 화면에서
 * 가장 눈에 띄어, 강하게 강조하는 것은 할 일 하나라는 원칙과 어긋난다.
 */
export function InfoBox({ tone = 'neutral', title, children, action }: InfoBoxProps) {
  const Icon = tone === 'critical' ? IconExclamationmarkCircleFill : IconILowercaseSerifCircleFill

  return (
    <div className="flex gap-2.5 rounded-[10px] bg-bg-neutral-weak p-3.5 text-15">
      <Icon
        aria-hidden="true"
        className={`mt-px size-4.5 shrink-0 ${tone === 'critical' ? 'text-fg-critical' : 'text-fg-neutral-muted'}`}
      />
      <div className="flex flex-1 flex-col gap-1">
        {title && <p className="font-bold">{title}</p>}
        {children && <div className="text-fg-neutral-muted">{children}</div>}
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            disabled={action.disabled}
            className="mt-1 cursor-pointer self-start font-bold underline underline-offset-2 disabled:cursor-not-allowed disabled:text-fg-disabled"
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  )
}
