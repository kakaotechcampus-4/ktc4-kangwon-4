import { IconSparkle2Fill } from '@karrotmarket/react-monochrome-icon'
import { Link } from 'react-router'

/**
 * 홈 맨 위의 "리본이 해둔 일" 띠. 누르면 작업 기록으로 간다(시안과 같음).
 *
 * 시안에서는 리본이 한 일을 한 줄씩 넘겨 보여주고 `1 / 3`처럼 쪽수를 단다.
 * 지금은 그 목록을 주는 API가 없어 빈 모양만 그린다. 쪽수는 셀 것이 없어 그리지 않는다.
 *
 * TODO(API): "리본이 해둔 일" 목록이 오면 제목·설명 자리에 한 줄씩 넣고 쪽수를 단다.
 */
export function HomeBanner() {
  return (
    <Link
      to="/log"
      className="flex min-h-19 shrink-0 items-center gap-3 bg-bg-brand-weak px-4 py-3.5 active:bg-bg-brand-weak-pressed"
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-17 font-bold">리본이 해둔 일이 여기 모여요</span>
        <span className="mt-0.5 block truncate text-14 text-fg-neutral-muted">
          서류를 읽거나 정리하면 알려드릴게요
        </span>
      </span>
      <span
        aria-hidden="true"
        className="grid size-11 shrink-0 place-items-center rounded-full bg-bg-layer-default text-fg-brand"
      >
        <IconSparkle2Fill size={24} />
      </span>
    </Link>
  )
}
