import { describe, expect, it } from 'vitest'

import type { LogEntry } from '../types/view'
import { toNotifications } from './notifications'

const entry = (actor: LogEntry['actor'], event: string, key = event): LogEntry => ({
  key,
  actor,
  event,
  occurredAt: '2026-10-17T14:02:11+09:00',
  text: `${event} 문구`,
  date: '10.17',
})

/** 알림은 리본이 한 일을 알리는 자리다. 사장님이 한 일이 섞이면 본인이 한 일을 알림으로 받는다 */
describe('toNotifications', () => {
  it('리본이 한 일만 고르고 기록 순서를 지킨다', () => {
    const notifications = toNotifications([
      entry('RIBBON', 'NEXT_ACTION_DECIDED'),
      entry('OWNER', 'RESULT_SUBMITTED'),
      entry('RIBBON', 'CONFLICT_FOUND'),
    ])

    expect(notifications.map((item) => item.event)).toEqual(['NEXT_ACTION_DECIDED', 'CONFLICT_FOUND'])
  })

  /** 기록에 판단 번호가 없어 그때 결과를 열 수 없다. 판단 알림은 지금 상태를 보여주는 홈으로 간다 */
  it('사건마다 누르면 갈 화면을 붙인다', () => {
    const notifications = toNotifications([
      entry('RIBBON', 'NEXT_ACTION_DECIDED'),
      entry('RIBBON', 'MORE_INFO_REQUESTED'),
      entry('RIBBON', 'CONFLICT_FOUND'),
      entry('RIBBON', 'JUDGMENT_FAILED'),
      entry('RIBBON', 'ROADMAP_TASKS_ADDED'),
      entry('RIBBON', 'DOCUMENTS_CHECKED'),
    ])

    expect(notifications.map((item) => item.to)).toEqual(['/case', '/case', '/case', '/case', '/roadmap', '/docs'])
  })

  it('갈 곳을 정하지 않은 사건은 뺀다', () => {
    expect(toNotifications([entry('RIBBON', 'SOMETHING_NEW'), entry('RIBBON', 'toString')])).toEqual([])
  })

  it('문구와 날짜는 기록 그대로 쓴다', () => {
    const [notification] = toNotifications([{ ...entry('RIBBON', 'NEXT_ACTION_DECIDED'), detail: '철거 업체 견적 받기' }])

    expect(notification).toMatchObject({ text: 'NEXT_ACTION_DECIDED 문구', detail: '철거 업체 견적 받기', date: '10.17' })
  })
})
