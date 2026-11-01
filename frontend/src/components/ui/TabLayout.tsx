import { IconBellLine } from '@karrotmarket/react-monochrome-icon'
import { Link, Outlet, useLocation } from 'react-router'

import hammerUrl from '../../assets/brand/reborn-hammer.svg'
import wordmarkUrl from '../../assets/brand/reborn-wordmark.svg'
import { TabBar } from './TabBar'

/** 홈 탭의 경로. 홈만 머리말에 이름 대신 망치와 워드마크를 둔다 */
const HOME_PATH = '/case'

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
 * 홈 머리말의 망치와 워드마크는 제목(`h1`)이 아니다. 홈은 "오늘 하실 일은 하나예요" 같은
 * 머리 문구가 화면의 제목이라, 여기서 `h1`을 하나 더 두면 제목이 둘이 된다.
 */
export function TabLayout() {
  const { pathname } = useLocation()

  return (
    <div className="mx-auto flex h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <header className="flex h-14 shrink-0 items-center gap-1 pr-1 pl-4">
        {pathname === HOME_PATH ? (
          <div className="flex flex-1 items-center gap-1">
            <img src={hammerUrl} alt="" className="size-7.5" />
            {/* 높이는 시안의 글자 크기 22px × 0.854(SVG 높이 비율). 3px 내려 글자 기준선을 망치에 맞춘다 */}
            <img src={wordmarkUrl} alt="리본" className="mt-0.75 h-4.75" />
          </div>
        ) : (
          <h1 className="flex-1 text-20 font-bold">{TAB_TITLE[pathname]}</h1>
        )}
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
