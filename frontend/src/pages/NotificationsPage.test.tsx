import { fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveTokens } from '../lib/auth'
import type { CaseLogItem } from '../types/api'
import { NotificationsPage } from './NotificationsPage'

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/notifications', element: <NotificationsPage /> },
      { path: '/case', element: <p>홈</p> },
      { path: '/roadmap', element: <p>로드맵</p> },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

type Answer = () => Response

const json = (body: unknown): Answer => () => new Response(JSON.stringify(body), { status: 200 })
const status = (code: number): Answer => () => new Response(null, { status: code })

/** 부를 때마다 차례로 답한다. 목록이 끝나면 마지막 답을 계속 준다 */
function serve(...answers: Answer[]) {
  let calls = 0
  const fetchMock = vi.fn(async () => answers[Math.min(calls++, answers.length - 1)]())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const item = (overrides: Partial<CaseLogItem>): CaseLogItem => ({
  actor: 'RIBBON',
  event: 'NEXT_ACTION_DECIDED',
  occurred_at: '2026-10-18T09:00:00+09:00',
  task_id: null,
  detail: '철거 업체 견적 받기',
  ...overrides,
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('NotificationsPage', () => {
  /** 사장님이 한 일은 본인이 아는 일이라 알림에 넣지 않는다 */
  it('리본이 한 일만 알림으로 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve(
      json({
        logs: [
          item({}),
          item({ actor: 'OWNER', event: 'RESULT_SUBMITTED', detail: null }),
          item({ event: 'ROADMAP_TASKS_ADDED', detail: '3' }),
        ],
      }),
    )
    renderAt('/notifications')

    const links = await screen.findAllByRole('link')
    expect(links).toHaveLength(2)
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['/case', '/roadmap'])
  })

  it('알림을 누르면 이어서 볼 화면으로 간다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve(json({ logs: [item({ event: 'ROADMAP_TASKS_ADDED', detail: '3' })] }))
    const router = renderAt('/notifications')

    fireEvent.click(await screen.findByRole('link'))

    expect(router.state.location.pathname).toBe('/roadmap')
  })

  /** 기록이 있어도 리본이 한 일이 없으면 알림은 없다 */
  it('알릴 것이 없으면 빈 화면을 보여준다', async () => {
    saveTokens('access-1', 'refresh-1')
    serve(json({ logs: [item({ actor: 'OWNER', event: 'CASE_CREATED', detail: null })] }))
    renderAt('/notifications')

    expect(await screen.findByRole('heading', { name: '알림이 없어요' })).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('불러오지 못하면 다시 불러올 수 있다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = serve(status(500), json({ logs: [item({})] }))
    renderAt('/notifications')

    fireEvent.click(await screen.findByRole('button', { name: '다시 불러오기' }))

    expect(await screen.findByRole('link')).toHaveAttribute('href', '/case')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
