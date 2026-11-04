import { act, render, screen } from '@testing-library/react'
import { Outlet, RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { useEntersForward, useNavigationDirection } from './viewTransition'

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

function Entered() {
  return <p>{useEntersForward() ? '앞으로 들어옴' : '뒤로 돌아옴'}</p>
}

/**
 * 뒤로 돌아온 화면은 밀려 나가는 움직임 중이라, 내용까지 올라오면 움직임이 두 겹이 된다.
 * 앞으로 들어온 화면에서만 내용을 올린다
 */
describe('useEntersForward', () => {
  it('앞으로 들어온 화면은 true, 뒤로 돌아온 화면은 false', async () => {
    const router = createMemoryRouter(
      [
        { path: '/case', element: <Entered /> },
        { path: '/task', element: <p>할 일</p> },
      ],
      { initialEntries: ['/task'] },
    )
    render(<RouterProvider router={router} />)

    await act(() => router.navigate('/case'))
    expect(screen.getByText('앞으로 들어옴')).toBeInTheDocument()

    await act(() => router.navigate('/task'))
    await act(() => router.navigate(-1))
    expect(screen.getByText('뒤로 돌아옴')).toBeInTheDocument()
  })
})
