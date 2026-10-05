import { fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { isLoggedIn, saveTokens, verifyOAuthState } from '../lib/auth'
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
 * 카카오로 나가는 것은 라우터가 아니라 브라우저가 한다. jsdom에는 진짜 이동이 없어서
 * `location`을 가짜로 세우고 무엇을 불렀는지만 본다.
 */
function stubNavigation() {
  const assign = vi.fn()
  vi.stubGlobal('location', { assign })
  return assign
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 인증 가드 밖에 있는 유일한 화면이다. 여기서 로그인 상태가 실제로 남지 않으면
 * 사용자는 버튼을 눌러도 계속 이 화면으로 되돌아온다 — 빠져나갈 방법이 없다.
 */
describe('LoginPage', () => {
  /**
   * 우리 화면 안에서 이동하면 안 된다. 서버가 카카오로 넘기는 303을 브라우저가 따라가야
   * 하는데, 라우터로 옮기면 그 주소를 찾지 못해 아무 일도 일어나지 않는다.
   */
  it('카카오로 시작하면 서버의 로그인 진입 주소로 이동한다', () => {
    const assign = stubNavigation()
    renderAt('/login')

    fireEvent.click(kakaoButton())

    expect(assign).toHaveBeenCalledWith(expect.stringContaining('/login/form'))
  })

  /**
   * 이 값이 안 실려 나가면 돌아왔을 때 맞춰볼 것이 없다. 그래도 로그인은 멀쩡히
   * 되기 때문에, 빠뜨려도 화면만 봐서는 알 수 없다.
   */
  it('카카오로 나가는 주소에 state 를 실어 보낸다', () => {
    const assign = stubNavigation()
    renderAt('/login')

    fireEvent.click(kakaoButton())

    const [url] = assign.mock.calls[0] as [string]
    const sent = new URL(url, 'http://localhost').searchParams.get('state')

    // 보낸 값이 저장돼 있어야 돌아왔을 때 통과한다
    expect(sent).not.toBeNull()
    expect(verifyOAuthState(sent)).toBe(true)
  })

  /**
   * feature 브랜치 Preview 에서는 진짜 로그인을 할 수 없어 리뷰어가 화면을 볼 방법이
   * 이것뿐이다. 눌러도 로그인이 남지 않으면 그 뒤 화면을 전부 못 본다.
   */
  it('가짜 로그인을 누르면 로그인 상태가 되어 진입 분기로 간다', async () => {
    renderAt('/login')

    fireEvent.click(screen.getByRole('button', { name: /가짜로 로그인/ }))

    expect(await screen.findByText('진입 분기')).toBeInTheDocument()
    expect(isLoggedIn('')).toBe(true)
  })

  /** 뒤로가기로는 닿을 수 없고 주소를 직접 열었을 때만 생기는 경로다 */
  it('이미 로그인했으면 로그인 화면을 그리지 않는다', async () => {
    saveTokens('access', 'refresh')
    renderAt('/login')

    expect(await screen.findByText('진입 분기')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '카카오로 시작하기' })).not.toBeInTheDocument()
  })

  /**
   * 로그인 화면을 다시 보려고 만든 Mock이다. 여기서 저장된 상태에 져 버리면
   * 한 번 로그인한 리뷰어는 이 화면을 다시 볼 방법이 없다.
   */
  it('로그인했어도 ?mock=logged-out이면 로그인 화면을 보여준다', () => {
    saveTokens('access', 'refresh')
    renderAt('/login?mock=logged-out')

    expect(kakaoButton()).toBeInTheDocument()
  })
})