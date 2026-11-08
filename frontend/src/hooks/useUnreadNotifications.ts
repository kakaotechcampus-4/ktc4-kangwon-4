import { toNotifications } from '../adapters/notifications'
import { hasUnread } from '../lib/notificationSeen'
import { useLogs } from './useLogs'

/**
 * 안 본 알림이 있는지. 종 버튼의 점에 쓴다.
 *
 * 알림 화면과 같은 기록(`GET /cases/logs`)을 따로 한 번 묻는다. 홈과 기록 탭도 같은 기록을 묻지만
 * 공유하는 상태를 두지 않았다 — 기록 조회는 가볍고 판단 중에 되풀이하지 않아서, 한 번 더 묻는 쪽이
 * 상태를 한 곳에 모으는 구조보다 단순하다.
 *
 * 불러오는 중이거나 실패하면 점을 찍지 않는다. 모르는 것을 새 알림이 있다고 하지 않는다.
 */
export function useUnreadNotifications(): boolean {
  const { query } = useLogs()
  return query.status === 'READY' && hasUnread(toNotifications(query.entries))
}
