import { createLocalValue } from './sessionStore'
import type { NotificationEntry } from '../types/view'

/**
 * 알림을 어디까지 봤는지. 본 알림 가운데 가장 최근 것의 시각 하나만 둔다.
 *
 * 알림마다 읽음을 따로 두지 않는 것은 기록에 번호가 없어서다. 시각으로 줄을 가리킬 수밖에 없고,
 * 그러면 "이 시각까지 봤다" 하나로 충분하다.
 *
 * 시각은 서버 글자 그대로(`+09:00` 이 붙은 한국 시각) 두고 견줄 때만 `Date.parse` 로 읽는다.
 * 시간대가 붙어 있어 브라우저 시간대와 상관없이 같은 순간을 가리킨다.
 */
const seenAt = createLocalValue('reborn:notifications-seen-at')

/** 저장해 둔 본 시각. 한 번도 안 봤으면 `null` */
export function readSeenAt(): string | null {
  return seenAt.read()
}

/** `seen` 뒤에 생긴 알림인지. 한 번도 안 봤으면 다 새것이고, 시각을 못 읽는 알림은 새것으로 치지 않는다 */
export function isNewSince(seen: string | null, occurredAt: string): boolean {
  const at = Date.parse(occurredAt)
  if (Number.isNaN(at)) return false
  if (seen === null) return true
  const seenTime = Date.parse(seen)
  return Number.isNaN(seenTime) || at > seenTime
}

/** 안 본 알림이 있는지 */
export function hasUnread(notifications: NotificationEntry[]): boolean {
  const seen = readSeenAt()
  return notifications.some((item) => isNewSince(seen, item.occurredAt))
}

/** 목록을 봤다고 적는다. 가장 늦은 시각을 고른다 — 서버 순서(최근 것부터)에 기대지 않는다 */
export function markSeen(notifications: NotificationEntry[]): void {
  const latest = notifications
    .map((item) => item.occurredAt)
    .filter((value) => !Number.isNaN(Date.parse(value)))
    .reduce<string | null>((max, value) => (max === null || Date.parse(value) > Date.parse(max) ? value : max), null)
  if (latest !== null && isNewSince(readSeenAt(), latest)) seenAt.write(latest)
}

/** 로그인이 끝나면 지운다. 공용 PC에서 다음 사람의 알림이 이미 본 것으로 보이지 않게 한다 */
export function forgetSeen(): void {
  seenAt.write(null)
}
