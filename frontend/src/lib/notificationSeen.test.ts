import { afterEach, describe, expect, it, vi } from 'vitest'

import type { NotificationEntry } from '../types/view'
import { logOut } from './auth'
import { hasUnread, isNewSince, markSeen, readSeenAt } from './notificationSeen'

const notification = (occurredAt: string): NotificationEntry => ({
  key: occurredAt,
  actor: 'RIBBON',
  event: 'NEXT_ACTION_DECIDED',
  occurredAt,
  text: '다음 할 일을 정했어요',
  date: '10.18',
  to: '/case',
})

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

/** 종 버튼의 점과 "새 알림" 표시가 이 값으로 갈린다. 틀리면 본 알림이 계속 새것으로 뜨거나 새 알림을 놓친다 */
describe('notificationSeen', () => {
  it('한 번도 안 봤으면 모든 알림이 새것이다', () => {
    expect(hasUnread([notification('2026-10-18T09:00:00+09:00')])).toBe(true)
  })

  it('본 뒤에는 그보다 늦은 알림만 새것이다', () => {
    markSeen([notification('2026-10-18T09:00:00+09:00'), notification('2026-10-17T09:00:00+09:00')])

    expect(hasUnread([notification('2026-10-18T09:00:00+09:00')])).toBe(false)
    expect(hasUnread([notification('2026-10-18T09:00:01+09:00')])).toBe(true)
  })

  /** 서버 시각에는 시간대가 붙어 온다. 글자 순서가 아니라 같은 순간인지로 견준다 */
  it('시간대가 달라도 같은 순간이면 본 것이다', () => {
    markSeen([notification('2026-10-18T09:00:00+09:00')])

    expect(isNewSince(readSeenAt(), '2026-10-18T00:00:00Z')).toBe(false)
  })

  /** 서버 순서에 기대면, 순서가 바뀐 응답에서 옛 시각을 적어 본 알림이 다시 새것으로 뜬다 */
  it('목록 순서와 상관없이 가장 늦은 시각을 적는다', () => {
    markSeen([notification('2026-10-17T09:00:00+09:00'), notification('2026-10-18T09:00:00+09:00')])

    expect(readSeenAt()).toBe('2026-10-18T09:00:00+09:00')
  })

  it('더 옛날 목록을 봐도 본 시각을 되돌리지 않는다', () => {
    markSeen([notification('2026-10-18T09:00:00+09:00')])
    markSeen([notification('2026-10-17T09:00:00+09:00')])

    expect(readSeenAt()).toBe('2026-10-18T09:00:00+09:00')
  })

  it('시각을 읽지 못하는 알림은 새것으로 치지 않는다', () => {
    expect(hasUnread([notification('어제')])).toBe(false)
  })

  /** 브라우저에 남는 값이라, 공용 PC에서 다음 사람의 알림이 이미 본 것으로 보이면 안 된다 */
  it('로그인이 끝나면 본 시각을 지운다', () => {
    markSeen([notification('2026-10-18T09:00:00+09:00')])

    logOut()

    expect(readSeenAt()).toBeNull()
  })

  /** 저장이 막힌 브라우저에서도 이 화면을 쓰는 동안은 본 것을 기억한다 */
  it('저장에 실패해도 이번 방문 동안은 본 것으로 둔다', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('저장 막힘')
    })

    markSeen([notification('2026-10-18T09:00:00+09:00')])

    expect(hasUnread([notification('2026-10-18T09:00:00+09:00')])).toBe(false)
  })
})
