import { IconBellLine } from '@karrotmarket/react-monochrome-icon'
import { Link, Outlet, useLocation } from 'react-router'

import { TabBar } from './TabBar'

/** 탭 화면의 머리말 이름 (시안) */
const TAB_TITLE: Record<string, string> = {
  '/docs': '서류함',
  '/log': '작업 기록',
}

/**
 * 하단 탭이 있는 화면의 틀. 머리말 · 화면 내용 · 하단 탭 순서다.
 *
 * 폭은 시안의 기기 폭(402px)으로 묶고 데스크톱에서는 가운데에 둔다.
 * 머리말과 탭은 제자리에 두고 가운데 내용만 스크롤한다. 앱처럼 탭이 늘 손 닿는 곳에 있게 한다.
 *
 * TODO(3번 PR): 홈을 이 틀 안으로 옮기면 홈 머리말(망치 + 워드마크)을 더한다.
 */
export function TabLayout() {
  const { pathname } = useLocation()

  return (
    <div className="mx-auto flex h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <header className="flex h-14 shrink-0 items-center gap-1 pr-1 pl-4">
        <h1 className="flex-1 text-20 font-bold">{TAB_TITLE[pathname]}</h1>
        <Link
          to="/notifications"
          aria-label="알림"
          className="grid size-12 place-items-center rounded-lg text-fg-neutral active:bg-bg-transparent-pressed"
        >
          <IconBellLine size={24} aria-hidden="true" />
        </Link>
      </header>

      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <Outlet />
      </main>

      <TabBar />
    </div>
  )
}
