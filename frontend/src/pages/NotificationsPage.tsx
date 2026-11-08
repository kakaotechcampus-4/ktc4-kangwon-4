import { IconBellLine, IconChevronRightLine, IconSparkle2Fill } from '@karrotmarket/react-monochrome-icon'
import { Link } from 'react-router'

import { toNotifications } from '../adapters/notifications'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { HammerLoader } from '../components/ui/HammerLoader'
import { TopBar } from '../components/ui/TopBar'
import { useLogs } from '../hooks/useLogs'

/**
 * 알림. 탭 화면 머리말의 종 버튼으로 들어온다.
 *
 * 알림 API는 따로 없다. 작업 기록(`GET /cases/logs`) 가운데 리본이 한 일을 골라 보여준다
 * (`toNotifications`). 줄을 누르면 그 일을 이어서 볼 화면으로 간다.
 */
export function NotificationsPage() {
  return (
    <div className="screen-frame mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar title="알림" />
      <main className="flex flex-1 flex-col">
        <NotificationList />
      </main>
    </div>
  )
}

function NotificationList() {
  const { query, reload } = useLogs()

  if (query.status === 'LOADING') {
    return (
      <div className="flex flex-1 items-center justify-center">
        <HammerLoader size={48} label="알림을 불러오는 중" />
      </div>
    )
  }

  if (query.status === 'LOAD_FAILED') {
    return (
      <EmptyState
        icon={<IconBellLine size={32} />}
        title="알림을 불러오지 못했어요"
        description="연결 상태를 확인하고 다시 불러와 주세요"
        action={<Button onClick={reload}>다시 불러오기</Button>}
      />
    )
  }

  const notifications = toNotifications(query.entries)
  if (notifications.length === 0) {
    return (
      <EmptyState
        icon={<IconBellLine size={32} />}
        title="알림이 없어요"
        description="새 소식이 생기면 여기서 알려드릴게요"
      />
    )
  }

  return (
    <ul className="flex flex-col px-4 pt-2 pb-6">
      {notifications.map((item) => (
        <li key={item.key}>
          <Link
            to={item.to}
            className="flex items-center gap-3 rounded-lg py-3.5 active:bg-bg-transparent-pressed"
          >
            <span
              aria-hidden="true"
              className="grid size-10 shrink-0 place-items-center rounded-full bg-bg-brand-weak text-fg-brand"
            >
              <IconSparkle2Fill size={20} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-17 font-medium">{item.text}</span>
              {item.detail && <span className="mt-0.5 block text-15 text-fg-neutral">{item.detail}</span>}
              <span className="mt-0.5 block text-14 text-fg-neutral-muted">{item.date}</span>
            </span>
            <IconChevronRightLine size={20} aria-hidden="true" className="shrink-0 text-fg-neutral-subtle" />
          </Link>
        </li>
      ))}
    </ul>
  )
}
