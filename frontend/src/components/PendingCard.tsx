import { useEffect, useState } from 'react'

interface PendingCardProps {
  /** 순서대로 보여줄 문구. 마지막에 도달하면 그 자리에 머문다 */
  messages: string[]
}

/** 문구를 넘기는 간격 */
const STEP_MS = 1200

/**
 * 처리 중 상태.
 *
 * 버튼 안 스피너가 아니라 카드 한 칸을 차지한다. `/results` 한 번에 여러 Agent와
 * 필수 Review가 순차로 돌아 대기가 길 수 있는데, 정지한 스피너는 몇 초만 지나도
 * 고장으로 읽힌다. 사용자가 새로고침하면 요청이 두 번 나간다.
 *
 * 문구가 바뀌면 진행 중이라는 것이 전해진다. 그래서 넓이가 필요하다.
 */
export function PendingCard({ messages }: PendingCardProps) {
  const [index, setIndex] = useState(0)

  useEffect(() => {
    // 마지막 문구에 도달하면 더 넘기지 않는다. 다시 처음으로 돌아가면
    // 같은 단계를 반복하는 것처럼 보여 오히려 진행이 멈춘 인상을 준다.
    if (index >= messages.length - 1) return

    const timer = window.setTimeout(() => setIndex((current) => current + 1), STEP_MS)
    return () => window.clearTimeout(timer)
  }, [index, messages.length])

  return (
    <section
      className="rounded-2xl border border-gray-200 bg-white p-5"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="size-5 shrink-0 rounded-full border-2 border-gray-200 border-t-gray-900 motion-safe:animate-spin"
        />
        <p className="text-lg font-bold text-gray-900">확인하고 있습니다</p>
      </div>

      <p className="mt-3 text-base leading-relaxed text-gray-600">{messages[index]}</p>
      <p className="mt-1 text-sm text-gray-500">잠시만 기다려 주세요.</p>
    </section>
  )
}
