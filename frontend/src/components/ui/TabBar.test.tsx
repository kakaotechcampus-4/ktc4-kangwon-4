import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { TabBar } from './TabBar'

function renderAt(path: string) {
  const page = (name: string) => (
    <>
      <p>{name} 화면</p>
      <TabBar />
    </>
  )
  const router = createMemoryRouter(
    [
      { path: '/', element: page('홈') },
      { path: '/docs', element: page('서류함') },
      { path: '/log', element: page('기록') },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
}

describe('TabBar', () => {
  it('지금 있는 탭을 알린다', () => {
    renderAt('/docs')

    expect(screen.getByRole('link', { name: '서류함' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: '홈' })).not.toHaveAttribute('aria-current')
  })

  it('탭을 누르면 그 화면으로 간다', async () => {
    renderAt('/docs')

    await userEvent.click(screen.getByRole('link', { name: '기록' }))

    expect(await screen.findByText('기록 화면')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '기록' })).toHaveAttribute('aria-current', 'page')
  })
})
