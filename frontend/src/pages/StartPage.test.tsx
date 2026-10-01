import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveTokens } from '../lib/auth'
import { StartPage } from './StartPage'

function mockCase(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(status === 200 ? JSON.stringify(body) : null, { status })),
  )
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/start', element: <StartPage /> },
      { path: '/case', element: <p>현재 Case</p> },
      { path: '/cases/new', element: <p>Case 생성</p> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
  return router
}

const startButton = () => screen.findByRole('link', { name: '시작하기' })

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * Case를 만들고 `/case`에서 뒤로 누르면 이 화면이 다시 나온다. 그때 "시작하기"가
 * 살아 있으면 두 번째 Case를 만들려 들고, 서버는 회원당 하나라 409로 막는다.
 */
describe('StartPage', () => {
  it('Case가 없으면 시작하기를 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase({ case: null })
    renderAt('/start')

    expect(await startButton()).toBeInTheDocument()
  })

  it('Case가 이미 있으면 현재 Case로 되돌린다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase({ case: { business_type: '카페' } })
    renderAt('/start')

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })

  /**
   * 진입 분기가 이미 빈 화면이다. 여기서까지 비우면 흰 화면이 두 번 이어진다.
   * 내용이 고정이라 답을 기다릴 이유가 없다.
   */
  it('답을 기다리는 동안에도 화면을 그린다', () => {
    saveTokens('access-1', 'refresh-1')
    // 응답을 주지 않는다 — 계속 기다리는 상태
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))
    renderAt('/start')

    expect(screen.getByRole('link', { name: '시작하기' })).toBeInTheDocument()
  })

  /**
   * 서버를 못 불렀으면 Case가 있는지 알 수 없다. 화면을 막아버리면 처음 온 사장님이
   * 아무것도 못 하므로, 그대로 두고 만들기를 누르면 서버가 409로 막게 한다.
   */
  it('서버를 부르지 못하면 화면을 그대로 둔다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockCase(null, 500)
    renderAt('/start')

    expect(await startButton()).toBeInTheDocument()
  })
})
