import { describe, expect, it, vi } from 'vitest'

import { toLogEntries } from './logs'

const log = (actor: string, event: string, occurred_at = '2026-10-17T14:02:11') => ({ actor, event, occurred_at })

/**
 * 기록은 사장님이 무엇을 했고 리본이 무엇을 했는지 돌아보는 자리다. 여기서 틀리면
 * 한 적 없는 일이 남거나, 한 사람이 바뀌어 기록이 거짓이 된다.
 */
describe('toLogEntries', () => {
  it('사건 코드를 문장으로, 날짜를 월.일로 바꾸고 서버 순서를 지킨다', () => {
    expect(
      toLogEntries({
        logs: [log('RIBBON', 'NEXT_ACTION_DECIDED', '2026-10-18T09:00:00'), log('OWNER', 'RESULT_SUBMITTED')],
      }),
    ).toEqual([
      { key: '0-NEXT_ACTION_DECIDED', actor: 'RIBBON', text: '다음 할 일을 정했어요', date: '10.18' },
      { key: '1-RESULT_SUBMITTED', actor: 'OWNER', text: '할 일 결과를 알려주셨어요', date: '10.17' },
    ])
  })

  /**
   * `Date` 로 읽으면 시간대 없는 값을 브라우저 시간대로 해석해, 한국 밖에서는 날짜가 밀린다.
   * 밤 11시 기록이 다음 날로 넘어가면 안 된다
   */
  it('날짜는 글자에서 잘라 쓴다', () => {
    // 테스트는 UTC 에서 돌아 밀림이 안 보인다. 한국보다 느린 시간대로 바꿔 본다
    vi.stubEnv('TZ', 'America/Los_Angeles')
    try {
      expect(toLogEntries({ logs: [log('OWNER', 'CASE_CREATED', '2026-10-31T23:59:59')] })?.[0].date).toBe('10.31')
    } finally {
      vi.unstubAllEnvs()
    }
  })

  /** 서버가 사건을 늘려도(#149·#159 예정) 목록 전체가 사라지거나 영어 코드가 뜨면 안 된다 */
  it('모르는 사건과 날짜를 못 읽는 줄만 뺀다', () => {
    const entries = toLogEntries({
      logs: [log('OWNER', 'CHECKLIST_COMPLETED'), log('RIBBON', 'CONFLICT_FOUND', '어제'), log('RIBBON', 'CONFLICT_FOUND')],
    })

    expect(entries?.map((entry) => entry.text)).toEqual(['기록과 다른 부분을 찾았어요'])
  })

  it('누가 했는지가 사건과 어긋나면 그 줄을 뺀다', () => {
    expect(toLogEntries({ logs: [log('RIBBON', 'RESULT_SUBMITTED')] })).toEqual([])
  })

  it('목록 모양이 아니면 읽지 못한 것으로 둔다', () => {
    expect(toLogEntries(null)).toBeNull()
    expect(toLogEntries({ logs: 'none' })).toBeNull()
    expect(toLogEntries({ logs: [] })).toEqual([])
  })
})
