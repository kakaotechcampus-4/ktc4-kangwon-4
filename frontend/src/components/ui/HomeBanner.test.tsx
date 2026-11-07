import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { LogEntry } from '../../types/view'
import { BANNER_INTERVAL_MS, HomeBanner } from './HomeBanner'

const entry = (text: string, date = '10.17'): LogEntry => ({ key: text, actor: 'RIBBON', text, date })

function renderBanner(items?: LogEntry[]) {
  render(
    <MemoryRouter>
      <HomeBanner items={items} />
    </MemoryRouter>,
  )
}

const banner = () => screen.getByRole('link')

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

/**
 * 홈에 들어오면 가장 먼저 보이는 줄이다. 리본이 한 일이 있는데 빈 모양이 뜨거나,
 * 넘기다 없는 쪽을 가리키면 리본이 아무것도 안 한 것처럼 읽힌다.
 */
describe('HomeBanner', () => {
  it('리본이 한 일이 없으면 무엇이 모일 곳인지만 알린다', () => {
    renderBanner([])

    expect(banner()).toHaveTextContent('리본이 해둔 일이 여기 모여요')
    expect(banner()).not.toHaveTextContent('/')
  })

  it('한 일을 최근 것부터 한 줄씩 넘기고 쪽수를 단다', () => {
    vi.useFakeTimers()
    renderBanner([entry('다음 할 일을 정했어요', '10.18'), entry('기록과 다른 부분을 찾았어요')])

    expect(banner()).toHaveTextContent('다음 할 일을 정했어요')
    expect(banner()).toHaveTextContent('리본이 해둔 일 · 10.18')
    expect(banner()).toHaveTextContent('1 / 2')

    act(() => {
      vi.advanceTimersByTime(BANNER_INTERVAL_MS)
    })
    expect(banner()).toHaveTextContent('기록과 다른 부분을 찾았어요')
    expect(banner()).toHaveTextContent('2 / 2')

    act(() => {
      vi.advanceTimersByTime(BANNER_INTERVAL_MS)
    })
    expect(banner()).toHaveTextContent('1 / 2')
  })

  /** 한 줄뿐인데 쪽수를 달면 넘길 것이 있는 줄 안다 */
  it('한 줄뿐이면 넘기지 않고 쪽수도 달지 않는다', () => {
    renderBanner([entry('다음 할 일을 정했어요')])

    expect(banner()).not.toHaveTextContent('1 / 1')
  })

  /** 저절로 바뀌는 글은 읽는 도중에 사라진다 */
  it('동작 줄이기를 켰으면 넘기지 않는다', () => {
    vi.useFakeTimers()
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce') }))
    renderBanner([entry('다음 할 일을 정했어요'), entry('기록과 다른 부분을 찾았어요')])

    act(() => {
      vi.advanceTimersByTime(BANNER_INTERVAL_MS)
    })

    expect(banner()).toHaveTextContent('다음 할 일을 정했어요')
  })
})
