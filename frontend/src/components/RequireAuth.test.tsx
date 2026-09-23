import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { logIn } from '../lib/auth'
import { RequireAuth } from './RequireAuth'

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/login', element: <p>로그인</p> },
      {
        element: <RequireAuth />,
        children: [{ path: '/case', element: <p>현재 Case</p> }],
      },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
  return router
}

/**
 * 이 가드가 뚫리면 로그인하지 않은 사람이 Case 화면에 들어온다. 지금은 Mock이라
 * 보이는 것이 없지만, 연동 후에는 남의 폐업 정보 앞에 아무나 서게 된다.
 *
 * 화면마다 검사를 넣지 않고 라우트 구조에 한 번 끼우는 방식이라, 새 화면이 늘어도
 * 여기만 통과하면 보호된다 — 반대로 여기가 깨지면 전부 열린다.
 */
describe('RequireAuth', () => {
  it('로그인하지 않았으면 보호된 화면을 그리지 않고 로그인으로 보낸다', async () => {
    renderAt('/case')

    expect(await screen.findByText('로그인')).toBeInTheDocument()
    expect(screen.queryByText('현재 Case')).not.toBeInTheDocument()
  })

  it('로그인했으면 그대로 통과시킨다', async () => {
    logIn()
    renderAt('/case')

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })

  /** 로그인 화면을 다시 보려고 만든 Mock이다. 저장된 상태를 이기지 못하면 쓸 수 없다 */
  it('로그인했어도 ?mock=logged-out이면 막는다', async () => {
    logIn()
    renderAt('/case?mock=logged-out')

    expect(await screen.findByText('로그인')).toBeInTheDocument()
  })

  it('로그인으로 보낼 때 ?mock= 을 그대로 이어준다', async () => {
    const router = renderAt('/case?mock=logged-out')
    await screen.findByText('로그인')

    expect(router.state.location.search).toBe('?mock=logged-out')
  })
})
