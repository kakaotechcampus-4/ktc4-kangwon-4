import type { LogEntry, NotificationEntry } from '../types/view'

/**
 * 알림으로 보여줄 사건과 누르면 갈 화면.
 *
 * 리본이 한 일만 둔다. 사장님이 한 일은 본인이 아는 일이라 알릴 것이 아니고, 기록 탭에 이미 있다.
 *
 * **옛 알림도 "지금 상태" 화면으로 보낸다.** 기록에는 판단 번호가 없어서 그때의 결과 화면을
 * 다시 열 수 없다. 그래서 판단에 관한 알림은 지금 상황을 보여주는 홈(`/case`)으로 보낸다 —
 * 지나간 "더 여쭤볼 게 있어요"를 눌러도 홈은 지금 할 일을 보여준다.
 */
const DESTINATION: Record<string, string> = {
  NEXT_ACTION_DECIDED: '/case',
  MORE_INFO_REQUESTED: '/case',
  CONFLICT_FOUND: '/case',
  JUDGMENT_FAILED: '/case',
  ROADMAP_TASKS_ADDED: '/roadmap',
  DOCUMENTS_CHECKED: '/docs',
}

/**
 * 기록 줄에서 알림을 고른다. 문구와 순서(최근 것부터)는 기록 그대로 쓴다.
 *
 * 위 표에 없는 사건은 뺀다. 리본이 한 일이 늘어도 갈 곳을 정하기 전까지는 알림에 넣지 않는다.
 * 누가 했는지(`actor`)는 다시 보지 않는다 — 표에는 리본의 사건만 있고, 사건과 `actor`가
 * 어긋난 줄은 기록 어댑터(`toLogEntries`)가 이미 뺐다.
 */
export function toNotifications(entries: LogEntry[]): NotificationEntry[] {
  return entries.flatMap((entry) => {
    if (!Object.hasOwn(DESTINATION, entry.event)) return []
    return [{ ...entry, to: DESTINATION[entry.event] }]
  })
}
