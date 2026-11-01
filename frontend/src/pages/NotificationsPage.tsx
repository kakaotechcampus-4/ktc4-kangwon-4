import { IconBellLine } from '@karrotmarket/react-monochrome-icon'

import { EmptyState } from '../components/ui/EmptyState'
import { TopBar } from '../components/ui/TopBar'

/**
 * 알림. 탭 화면 머리말의 종 버튼으로 들어온다.
 *
 * TODO(API): 알림 API가 없어 빈 상태만 보여준다.
 */
export function NotificationsPage() {
  return (
    <div className="mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar title="알림" />
      <main className="flex flex-1 flex-col">
        <EmptyState
          icon={<IconBellLine size={32} />}
          title="알림이 없어요"
          description="새 소식이 생기면 여기서 알려드릴게요"
        />
      </main>
    </div>
  )
}
