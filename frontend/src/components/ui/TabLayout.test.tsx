import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { announceLogsChanged } from '../../hooks/useLogs'
import { saveTokens } from '../../lib/auth'
import { DocsPage } from '../../pages/DocsPage'
import { LogPage } from '../../pages/LogPage'
import { NotificationsPage } from '../../pages/NotificationsPage'
import { TabLayout } from './TabLayout'

/**
 * `routes.tsx`와 같은 구조.
 * 홈(`/case`)은 서버를 불러오는 화면이라 여기서는 빈 자리로 둔다. 이 파일은 틀만 본다.
 */
function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      {
        element: <TabLayout />,
        children: [
          { path: '/case', element: <div /> },
          { path: '/docs', element: <DocsPage /> },
          { path: '/log', element: <LogPage /> },
        ],
      },
      { path: '/notifications', element: <NotificationsPage /> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
}

describe('TabLayout', () => {
  /** 서류함은 서버(#159)에서 목록을 불러온다. 비어 있다고 답하면 빈 서류함을 그린다 */
  it('서류함은 머리말에 이름을 두고, 서류가 없으면 없다는 화면을 보여준다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ documents: [], check: null }), { status: 200 })))
    renderAt('/docs')

    expect(screen.getByRole('heading', { level: 1, name: '서류함' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 2 })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('홈 머리말은 이름 대신 워드마크를 두고, 제목은 화면에 맡긴다', () => {
    renderAt('/case')

    expect(screen.getByRole('img', { name: '리본' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument()
  })

  it('탭을 누르면 머리말 이름도 그 화면으로 바뀐다', async () => {
    renderAt('/docs')

    await userEvent.click(screen.getByRole('link', { name: '기록' }))

    expect(await screen.findByRole('heading', { level: 1, name: '작업 기록' })).toBeInTheDocument()
  })

  it('종 버튼을 누르면 알림 화면으로 가고, 뒤로 누르면 돌아온다', async () => {
    renderAt('/docs')

    await userEvent.click(screen.getByRole('link', { name: '알림' }))
    expect(await screen.findByRole('heading', { level: 1, name: '알림' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '주요 화면' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '뒤로' }))
    expect(await screen.findByRole('heading', { level: 1, name: '서류함' })).toBeInTheDocument()
  })
})

/** 종 버튼의 점. 기록(`GET /cases/logs`)에서 리본이 한 일이 본 시각보다 늦으면 찍는다 */
describe('TabLayout — 새 알림 점', () => {
  const logs = {
    logs: [
      { actor: 'RIBBON', event: 'NEXT_ACTION_DECIDED', occurred_at: '2026-10-18T09:00:00+09:00', task_id: null, detail: null },
    ],
  }

  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  function serveLogs() {
    saveTokens('access-1', 'refresh-1')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        new Response(JSON.stringify(url.includes('/cases/logs') ? logs : { documents: [], check: null }), { status: 200 }),
      ),
    )
  }

  it('안 본 알림이 있으면 종 버튼이 새 알림이 있다고 알린다', async () => {
    serveLogs()
    renderAt('/docs')

    expect(await screen.findByRole('link', { name: '알림, 새 알림 있음' })).toBeInTheDocument()
  })

  it('이미 본 알림뿐이면 알리지 않는다', async () => {
    localStorage.setItem('reborn:notifications-seen-at', '2026-10-18T09:00:00+09:00')
    serveLogs()
    renderAt('/docs')

    // 기록을 받은 뒤에도 이름이 그대로인지 본다. 서류함 목록이 뜰 때쯤이면 기록도 받았다
    expect(await screen.findByRole('heading', { level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '알림' })).toBeInTheDocument()
  })

  it('알림 화면을 보고 돌아오면 점이 사라진다', async () => {
    serveLogs()
    renderAt('/docs')

    await userEvent.click(await screen.findByRole('link', { name: '알림, 새 알림 있음' }))
    expect(await screen.findByRole('link', { name: /다음 할 일을 정했어요/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '뒤로' }))

    expect(await screen.findByRole('link', { name: '알림' })).toBeInTheDocument()
  })

  /** 다른 화면에 있을 때 판단이 끝나면(`JudgmentWatcher`) 화면을 옮기지 않아도 점이 켜져야 한다 */
  it('기록이 늘었다는 신호를 받으면 다시 물어 점을 찍는다', async () => {
    saveTokens('access-1', 'refresh-1')
    let answer: unknown = { logs: [] }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        new Response(JSON.stringify(url.includes('/cases/logs') ? answer : { documents: [], check: null }), { status: 200 }),
      ),
    )
    renderAt('/docs')
    expect(await screen.findByRole('heading', { level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '알림' })).toBeInTheDocument()

    answer = logs
    act(() => announceLogsChanged())

    expect(await screen.findByRole('link', { name: '알림, 새 알림 있음' })).toBeInTheDocument()
  })
})
