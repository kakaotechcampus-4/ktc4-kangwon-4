import type { ReactNode } from 'react'

/**
 * 카드 색.
 *
 * - `brand`    사장님 할 일, 리본이 일하는 중
 * - `critical` 확인이 필요한 것 (추가 질문·충돌·실패)
 * - `neutral`  상태를 읽지 못한 것
 */
type TaskCardTone = 'brand' | 'critical' | 'neutral'

interface TaskCardProps {
  tone: TaskCardTone
  /** SEED 아이콘 40px. 꾸밈이라 화면 읽기 프로그램이 읽지 않는다 */
  icon: ReactNode
  /** 배지 글자 앞에 붙는 작은 아이콘. 리본(AI)이 일하는 중일 때 반짝이를 둔다 */
  badgeIcon?: ReactNode
  badge: string
  title: string
  /** 왜 이걸 먼저 하는지. 비면 문단을 그리지 않는다 */
  description?: string
  /** 지금 막고 있는 것. 할 일의 이유를 돕는 보조 정보라 한 줄로 약하게 둔다 */
  blocker?: string
  /** 설명 아래에 더 보여줄 것. 추가 질문 목록 같은 것 */
  children?: ReactNode
  /** 카드 맨 아래 버튼. 보통 `Button size="lg"` 하나 */
  actions: ReactNode
}

const TONE_STYLE: Record<TaskCardTone, { icon: string; badge: string }> = {
  brand: { icon: 'bg-bg-brand-weak text-fg-brand', badge: 'text-fg-brand-contrast' },
  critical: { icon: 'bg-bg-critical-weak text-fg-critical', badge: 'text-fg-critical-contrast' },
  neutral: { icon: 'bg-bg-neutral-weak text-fg-neutral-subtle', badge: 'text-fg-neutral-muted' },
}

/**
 * 홈의 할 일 카드. 지금 사장님이 할 일 하나, 또는 지금 상태 하나를 크게 보여준다.
 *
 * 남은 높이를 채우고 버튼은 맨 아래에 붙인다. 화면마다 내용 길이가 달라도 버튼이 늘 같은
 * 자리에 있어 엄지가 찾기 쉽다. 그래서 감싸는 칸은 세로 flex여야 한다.
 *
 * 제목은 `h2`다. 화면의 제목(`h1`)은 카드 위의 머리 문구가 맡는다.
 */
export function TaskCard({
  tone,
  icon,
  badgeIcon,
  badge,
  title,
  description,
  blocker,
  children,
  actions,
}: TaskCardProps) {
  const style = TONE_STYLE[tone]

  return (
    <section className="flex flex-1 flex-col gap-3 rounded-20 bg-bg-layer-default px-5 pt-6 pb-5 shadow-raised">
      <span
        aria-hidden="true"
        className={`grid size-18 shrink-0 place-items-center rounded-20 ${style.icon}`}
      >
        {icon}
      </span>

      <p className={`mt-2 flex items-center gap-1 text-16 font-bold ${style.badge}`}>
        {badgeIcon}
        {badge}
      </p>
      <h2 className="text-26 font-bold text-pretty">{title}</h2>
      {description && <p className="text-17 text-pretty text-fg-neutral-muted">{description}</p>}
      {blocker && (
        <p className="text-15 text-fg-neutral-subtle">
          <span className="font-medium">막힌 것</span> · {blocker}
        </p>
      )}
      {children}

      <div className="mt-auto flex flex-col gap-2">{actions}</div>
    </section>
  )
}
