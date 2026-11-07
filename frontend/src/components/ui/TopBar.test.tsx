import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { TopBar } from './TopBar'

function renderAt(entries: string[]) {
  const router = createMemoryRouter(
    [
      { path: '/', element: <p>홈</p> },
      { path: '/docs', element: <p>서류함</p> },
      { path: '/notifications', element: <TopBar title="알림" /> },
    ],
    { initialEntries: entries, initialIndex: entries.length - 1 },
  )

  render(<RouterProvider router={router} />)
}

describe('TopBar', () => {
  it('뒤로 버튼은 앞 화면으로 돌아간다', async () => {
    renderAt(['/docs', '/notifications'])

    await userEvent.click(screen.getByRole('button', { name: '뒤로' }))

    expect(await screen.findByText('서류함')).toBeInTheDocument()
  })

  /** 그대로 뒤로 가면 앱을 떠나 버린다 */
  it('주소로 바로 들어와 돌아갈 곳이 없으면 홈으로 간다', async () => {
    renderAt(['/notifications'])

    await userEvent.click(screen.getByRole('button', { name: '뒤로' }))

    expect(await screen.findByText('홈')).toBeInTheDocument()
  })
})
