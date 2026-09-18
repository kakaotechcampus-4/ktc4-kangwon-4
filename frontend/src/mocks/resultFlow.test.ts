import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { conflictConfirm, simulateConfirm, simulateSubmit, updatedReplan } from './resultFlow'

/**
 * 제출 함수에는 처리 중 화면을 눌러볼 수 있게 7초 지연이 들어 있다.
 * 실제로 기다리면 테스트가 그만큼 멈추므로 가짜 타이머로 건너뛴다.
 */
beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

/**
 * 대기 중인 타이머를 모두 흘려보내고 결과를 받는다.
 *
 * 지연 시간을 숫자로 적지 않는 것은, 그 값이 `PendingCard`의 문구 전환에 맞춰
 * 조정될 수 있어서다. 테스트가 구현의 숫자를 따라다니게 만들지 않는다.
 */
async function skipPending<T>(promise: Promise<T>): Promise<T> {
  await vi.runAllTimersAsync()
  return promise
}

describe('simulateSubmit', () => {
  /**
   * Mock 목록을 `OUTCOMES[key]`로 바로 찾으면 `constructor`나 `toString` 같은
   * 이름이 Object.prototype의 값을 집어 와, 화면이 형태가 다른 결과를 받고 깨진다.
   * 실제로 한 번 터져서 `Object.hasOwn` 조회로 바꾼 자리다.
   */
  it.each(['constructor', 'toString', '__proto__', 'hasOwnProperty'])(
    'Mock 목록에 없는 이름(%s)이 와도 정상 경로를 돌려준다',
    async (key) => {
      const outcome = await skipPending(simulateSubmit(key, '아무 문장'))

      expect(outcome).toEqual({ kind: 'REPLAN', view: updatedReplan })
    },
  )

  /**
   * 충돌 화면은 "이번에 하신 말씀"으로 사용자가 친 문장을 보여준다.
   * 서버가 이 문장을 응답에 돌려주지 않으므로 프론트가 실어 보내야 하고,
   * 빠지면 사용자는 무엇 때문에 고르는지 모르는 채로 고르게 된다.
   */
  it('충돌 경로에서 사용자가 친 문장을 그대로 싣는다', async () => {
    const outcome = await skipPending(simulateSubmit('conflict', '임대인이 철거하래요'))

    expect(outcome).toMatchObject({
      kind: 'CONFIRM',
      view: { rawInput: '임대인이 철거하래요' },
    })
  })

  /**
   * 문장을 실을 때 Mock 원본을 고쳐 쓰면, 두 번째 제출에 첫 번째 문장이 남거나
   * 뒤섞인다. Mock은 여러 화면이 함께 읽는 값이라 호출이 원본을 건드리면 안 된다.
   */
  it('두 번 호출해도 Mock 원본이 그대로다', async () => {
    const before = conflictConfirm.rawInput

    const first = await skipPending(simulateSubmit('conflict', '첫 번째 문장'))
    const second = await skipPending(simulateSubmit('conflict', '두 번째 문장'))

    expect(first).toMatchObject({ view: { rawInput: '첫 번째 문장' } })
    expect(second).toMatchObject({ view: { rawInput: '두 번째 문장' } })
    expect(conflictConfirm.rawInput).toBe(before)
  })
})

describe('simulateConfirm', () => {
  /**
   * 기존 값을 그대로 두기로 했으면 Case가 바뀌지 않았다는 뜻이다.
   * 여기서 변경 내역이 나오면 "바뀐 것이 없다"는 안내와 화면이 서로 다른 말을 한다.
   */
  it('전부 기존 값을 고르면 변경 목록이 비어 있다', async () => {
    const replan = await skipPending(simulateConfirm({ demolition_required: 'STORED' }))

    expect(replan.changes).toEqual([])
  })

  /** 위 테스트만 있으면 늘 빈 목록을 주는 구현도 통과하므로 반대쪽을 함께 고정한다 */
  it('새 값을 고르면 변경 목록에 그 항목이 담긴다', async () => {
    const replan = await skipPending(simulateConfirm({ demolition_required: 'INCOMING' }))

    expect(replan.changes).toHaveLength(1)
    expect(replan.changes[0]).toMatchObject({ key: 'demolition_required' })
  })
})
