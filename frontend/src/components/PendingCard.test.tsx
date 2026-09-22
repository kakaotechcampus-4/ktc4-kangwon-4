import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PendingCard } from './PendingCard'

const MESSAGES = ['첫 번째 안내', '두 번째 안내', '세 번째 안내']

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

/**
 * 문구 전환이 끝날 때까지 타이머를 흘려보낸다.
 *
 * 간격을 숫자로 적지 않는 것은 그 값이 조정될 수 있어서다. 대신 대기 중인 타이머가
 * 없어질 때까지 돌린다 — 마지막 문구에서 더 걸지 않는 것이 이 컴포넌트의 규칙이라
 * 이 반복은 끝난다.
 *
 * `act` 안에서는 동기 타이머 함수를 쓴다. 비동기 버전은 act의 flush와 맞물려
 * 상태 변경이 화면에 반영되지 않는다.
 */
async function flushMessages() {
  while (vi.getTimerCount() > 0) {
    await act(async () => {
      vi.runAllTimers()
    })
  }
}

describe('PendingCard', () => {
  /**
   * `role="status"`는 `aria-atomic`이 기본 `true`라, 문구가 한 번 바뀔 때마다
   * 카드 전체를 다시 읽는다. 진행 상황을 알리려던 문구 전환이 화면을 못 보는
   * 사용자에게는 같은 안내의 반복이 된다.
   *
   * 속성 하나라 다른 작업을 하다 쉽게 사라지는데, 사라져도 화면은 그대로여서
   * 스크린리더를 켜보지 않으면 모른다.
   */
  it('바뀐 문장만 읽히도록 라이브 영역을 설정한다', () => {
    render(<PendingCard messages={MESSAGES} />)

    const status = screen.getByRole('status')

    expect(status).toHaveAttribute('aria-live', 'polite')
    expect(status).toHaveAttribute('aria-atomic', 'false')
  })

  /** 문구가 실제로 넘어가는지 — 이게 안 되면 위 설정도 의미가 없다 */
  it('시간이 지나면 다음 문구로 넘어간다', async () => {
    render(<PendingCard messages={MESSAGES} />)

    expect(screen.getByText(MESSAGES[0])).toBeInTheDocument()

    await flushMessages()

    expect(screen.getByText(MESSAGES[2])).toBeInTheDocument()
    expect(screen.queryByText(MESSAGES[0])).not.toBeInTheDocument()
  })
})
