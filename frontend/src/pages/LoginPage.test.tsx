import { fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { isLoggedIn, logIn } from '../lib/auth'
import { LoginPage } from './LoginPage'

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/login', element: <LoginPage /> },
      { path: '/', element: <p>진입 분기</p> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
  return router
}

const kakaoButton = () => screen.getByRole('button', { name: '카카오로 시작하기' })

/**
 * 인증 가드 밖에 있는 유일한 화면이다. 여기서 로그인 상태가 실제로 남지 않으면
 * 사용자는 버튼을 눌러도 계속 이 화면으로 되돌아온다 — 빠져나갈 방법이 없다.
 */
describe('LoginPage', () => {
  it('카카오로 시작하면 로그인 상태가 되어 진입 분기로 간다', async () => {
    renderAt('/login')

    fireEvent.click(kakaoButton())

    expect(await screen.findByText('진입 분기')).toBeInTheDocument()
    // 이동만 확인하면 로그인이 실제로 남았는지는 모른 채 통과한다.
    // 그 상태로는 다음 화면에서 인증 가드에 걸려 다시 여기로 돌아온다
    expect(isLoggedIn('')).toBe(true)
  })

  /** 뒤로가기로는 닿을 수 없고 주소를 직접 열었을 때만 생기는 경로다 */
  it('이미 로그인했으면 로그인 화면을 그리지 않는다', async () => {
    logIn()
    renderAt('/login')

    expect(await screen.findByText('진입 분기')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '카카오로 시작하기' })).not.toBeInTheDocument()
  })

  /**
   * 로그인 화면을 다시 보려고 만든 Mock이다. 여기서 저장된 상태에 져 버리면
   * 한 번 로그인한 리뷰어는 이 화면을 다시 볼 방법이 없다.
   */
  it('로그인했어도 ?mock=logged-out이면 로그인 화면을 보여준다', () => {
    logIn()
    renderAt('/login?mock=logged-out')

    expect(kakaoButton()).toBeInTheDocument()
  })
})