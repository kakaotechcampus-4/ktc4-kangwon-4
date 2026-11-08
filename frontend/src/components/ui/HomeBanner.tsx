import { IconSparkle2Fill } from '@karrotmarket/react-monochrome-icon'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { prefersReducedMotion } from '../../lib/reducedMotion'
import type { LogEntry } from '../../types/view'

/** 한 줄을 보여주는 시간. 시안과 같다 */
export const BANNER_INTERVAL_MS = 3_500

interface HomeBannerProps {
  /** 리본이 한 일. 최근 것부터. 비어 있으면 빈 모양을 그린다 */
  items?: LogEntry[]
}

/**
 * 홈 맨 위의 "리본이 해둔 일" 띠. 누르면 작업 기록으로 간다(시안과 같음).
 *
 * 리본이 한 일을 한 줄씩 넘겨 보여주고 `1 / 3` 처럼 쪽수를 단다. 한 줄뿐이면 넘기지 않는다.
 * 기기에서 "동작 줄이기"를 켰으면 넘기지 않고 가장 최근 줄만 둔다 — 저절로 바뀌는 글은
 * 읽는 도중에 사라진다.
 *
 * 아직 리본이 한 일이 없으면 무엇이 모일 곳인지만 알린다.
 */
export function HomeBanner({ items = [] }: HomeBannerProps) {
  const [index, setIndex] = useState(0)
  const count = items.length

  useEffect(() => {
    if (count < 2 || prefersReducedMotion()) return
    const timer = window.setInterval(() => setIndex((current) => current + 1), BANNER_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [count])

  // 줄 수가 줄어도 넘친 쪽수를 가리키지 않게 나머지로 고른다
  const item = count > 0 ? items[index % count] : null

  return (
    <Link
      to="/log"
      className="relative flex min-h-19 shrink-0 items-center gap-3 bg-bg-brand-weak px-4 py-3.5 active:bg-bg-brand-weak-pressed"
    >
      {/* 줄이 바뀔 때마다 새로 그려 흐리게 들어오게 한다(0.3초). 쪽수 배지는 움직이지 않는다 */}
      <span key={item ? index % count : 'empty'} className="min-w-0 flex-1 motion-safe:animate-fade-in" aria-live="off">
        <span className="block truncate text-17 font-bold">{item ? item.text : '리본이 해둔 일이 여기 모여요'}</span>
        <span className="mt-0.5 block truncate text-14 text-fg-neutral-muted">
          {item ? `리본이 해둔 일 · ${item.date}` : '서류를 읽거나 정리하면 알려드릴게요'}
        </span>
      </span>
      <span
        aria-hidden="true"
        className="grid size-11 shrink-0 place-items-center rounded-full bg-bg-layer-default text-fg-brand"
      >
        <IconSparkle2Fill size={24} />
      </span>
      {count > 1 && (
        <span className="absolute right-2.5 bottom-2 h-5 rounded-full bg-bg-neutral-solid px-1.75 text-11 leading-5 font-bold text-fg-on-brand-solid tabular-nums">
          <span className="sr-only">전체 {count}개 중 </span>
          {(index % count) + 1} / {count}
        </span>
      )}
    </Link>
  )
}
