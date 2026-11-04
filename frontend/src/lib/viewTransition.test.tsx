import { act, render } from '@testing-library/react'
import { Outlet, RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { useNavigationDirection } from './viewTransition'

function Root() {
  useNavigationDirection()
  return <Outlet />
}

function renderRouter() {
  const router = createMemoryRouter(
    [
      {
        element: <Root />,
        children: [
          { path: '/case', element: <p>홈</p> },
          { path: '/task', element: <p>할 일</p> },
        ],
      },
    ],
    { initialEntries: ['/case'] },
  )
  render(<RouterProvider router={router} />)
  return router
}

/**
 * 화면 이동 움직임(`index.css`)은 이 값으로 방향을 고른다. 틀리면 뒤로 가는데 새 화면이
 * 오른쪽에서 밀려 들어와, 앞으로 간 것처럼 보인다.
 */
describe('useNavigationDirection', () => {
  it('앞으로 가면 forward, 뒤로 가면 back 으로 적는다', async () => {
    const router = renderRouter()

    await act(() => router.navigate('/task'))
    expect(document.documentElement.dataset.nav).toBe('forward')

    await act(() => router.navigate(-1))
    expect(document.documentElement.dataset.nav).toBe('back')
  })

  it('뒤로 온 화면에서 다시 앞으로 가면 forward 로 돌아온다', async () => {
    const router = renderRouter()
    await act(() => router.navigate('/task'))
    await act(() => router.navigate(-1))

    await act(() => router.navigate('/task'))
    expect(document.documentElement.dataset.nav).toBe('forward')
  })
})
