import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { DocsPage } from '../../pages/DocsPage'
import { LogPage } from '../../pages/LogPage'
import { NotificationsPage } from '../../pages/NotificationsPage'
import { TabLayout } from './TabLayout'

/** `routes.tsx`와 같은 구조 */
function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      {
        element: <TabLayout />,
        children: [
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
  it('서류함은 아직 서류가 없다는 화면을 보여준다', () => {
    renderAt('/docs')

    expect(screen.getByRole('heading', { level: 1, name: '서류함' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2 })).toBeInTheDocument()
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
