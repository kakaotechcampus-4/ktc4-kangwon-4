import type { ReactNode } from 'react'

interface EmptyStateProps {
  /** SEED 아이콘. 꾸밈이라 화면 읽기 프로그램이 읽지 않는다 */
  icon: ReactNode
  title: string
  description?: string
  /** 빈 상태에서 바로 할 수 있는 행동. 보통 `Button` 하나 */
  action?: ReactNode
}

/**
 * 보여줄 것이 아직 없을 때의 화면.
 *
 * 시안에는 늘 데모 데이터가 차 있어서 이 화면이 없다. 시안의 아이콘 원·글자 크기로 맞췄다.
 * API가 없는 화면은 가짜 데이터로 채우지 않고 이 화면을 보여준다.
 *
 * 놓인 칸의 남은 높이를 채우고 그 가운데에 선다. 위에 붙어 있으면 화면이 덜 그려진 것처럼 보인다.
 * 그래서 감싸는 칸은 세로 flex(`flex flex-col`)여야 한다.
 */
export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center">
      <span
        aria-hidden="true"
        className="grid size-16 place-items-center rounded-full bg-bg-neutral-weak text-fg-neutral-subtle"
      >
        {icon}
      </span>
      <h2 className="mt-4 text-18 font-bold">{title}</h2>
      {description && (
        <p className="mt-1.5 text-15 whitespace-pre-line text-fg-neutral-muted">{description}</p>
      )}
      {action && <div className="mt-6 w-full max-w-xs">{action}</div>}
    </div>
  )
}
