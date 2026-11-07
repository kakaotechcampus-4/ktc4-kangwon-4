import {
  IconClockFill,
  IconClockLine,
  IconDocumentTrayFill,
  IconDocumentTrayLine,
  IconHouseFill,
  IconHouseLine,
} from '@karrotmarket/react-monochrome-icon'
import { NavLink } from 'react-router'

/** 고른 탭은 채운 아이콘, 나머지는 선 아이콘 (시안) */
const TABS = [
  { to: '/case', label: '홈', OnIcon: IconHouseFill, OffIcon: IconHouseLine },
  { to: '/docs', label: '서류함', OnIcon: IconDocumentTrayFill, OffIcon: IconDocumentTrayLine },
  { to: '/log', label: '기록', OnIcon: IconClockFill, OffIcon: IconClockLine },
]

/**
 * 하단 탭.
 *
 * 시안은 아이폰 틀 안이라 아래 26px를 홈 바 자리로 비워 둔다. 실제 기기에서는 브라우저가
 * 알려주는 안전 영역(`safe-area-inset-bottom`)만큼만 비운다. 홈 바가 없는 기기에서는 0이다.
 *
 * 지금 탭은 `NavLink`가 `aria-current="page"`로 알린다. 색만으로 구분하지 않는다.
 */
export function TabBar() {
  return (
    <nav
      aria-label="주요 화면"
      className="grid shrink-0 grid-cols-3 border-t border-stroke-neutral-muted bg-bg-layer-default pb-[env(safe-area-inset-bottom)]"
    >
      {TABS.map(({ to, label, OnIcon, OffIcon }) => (
        <NavLink
          key={to}
          to={to}
          end
          className={({ isActive }) =>
            `flex h-14.5 flex-col items-center justify-center gap-0.75 text-12 font-medium ${isActive ? 'text-fg-neutral' : 'text-fg-neutral-subtle'}`
          }
        >
          {({ isActive }) => {
            const Icon = isActive ? OnIcon : OffIcon
            return (
              <>
                <Icon size={26} aria-hidden="true" />
                {label}
              </>
            )
          }}
        </NavLink>
      ))}
    </nav>
  )
}
