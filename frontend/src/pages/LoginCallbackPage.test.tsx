import { render, screen } from '@testing-library/react'
import { StrictMode } from 'react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createOAuthState, getAccessToken } from '../lib/auth'
import { LoginCallbackPage } from './LoginCallbackPage'

function mockLoginResponse() {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ nickname: '김사장' }), {
      status: 200,
      headers: { 'Access-Token': 'access-1', 'Refresh-Token': 'refresh-1' },
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/**
 * 카카오가 돌려보내는 주소. 진짜 흐름에서는 `/login` 이 state 를 만들어 두고 나가므로,
 * 테스트도 같은 순서를 밟는다 — 저장해 두고, 그 값을 주소에 실어 돌아온다.
 */
function callbackUrl({ code = 'code-1', state }: { code?: string; state?: string | null } = {}) {
  const saved = createOAuthState()
  const params = new URLSearchParams({ code })

  // `state: null` 은 주소에서 state 를 빼는 뜻이다. 생략하면 저장분을 그대로 싣는다
  const returned = state === undefined ? saved : state
  if (returned !== null) params.set('state', returned)

  return `/login/callback?${params}`
}

function renderAt(path: string, { strict = false } = {}) {
  const router = createMemoryRouter(
    [
      { path: '/login', element: <p>로그인 화면</p> },
      { path: '/login/callback', element: <LoginCallbackPage /> },
      { path: '/', element: <p>진입 분기</p> },
    ],
    { initialEntries: [path] },
  )

  const tree = <RouterProvider router={router} />
  render(strict ? <StrictMode>{tree}</StrictMode> : tree)
  return router
}

const failureHeading = () => screen.findByRole('heading', { name: '로그인하지 못했습니다' })

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 사용자가 볼 일이 거의 없는 화면이지만, 여기서 막히면 로그인 자체가 끝나지 않는다.
 * 카카오까지 다녀와 놓고 돌아온 자리에서 실패하면 사용자는 무엇이 잘못됐는지 알 수 없다.
 */
describe('LoginCallbackPage', () => {
  it('code 를 토큰으로 바꾸고 진입 분기로 보낸다', async () => {
    mockLoginResponse()
    renderAt(callbackUrl())

    expect(await screen.findByText('진입 분기')).toBeInTheDocument()
    expect(getAccessToken()).toBe('access-1')
  })

  /**
   * `code`는 한 번만 쓸 수 있다. React가 개발 중 effect를 두 번 실행하는데 그대로 두면
   * 두 번째 호출이 이미 쓴 code 로 들어가 실패하고, 성공했는데도 실패 화면이 남는다.
   */
  it('effect 가 두 번 실행돼도 로그인 요청은 한 번만 보낸다', async () => {
    const fetchMock = mockLoginResponse()
    renderAt(callbackUrl(), { strict: true })

    await screen.findByText('진입 분기')

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  /**
   * 다 쓴 code 가 주소에 남아 있다. 히스토리에 남으면 뒤로 갔을 때 그 code 로 다시
   * 시도해서, 성공해 놓고 실패 화면을 보게 된다.
   */
  it('성공한 뒤 뒤로 가도 이 화면으로 돌아오지 않는다', async () => {
    mockLoginResponse()
    const router = createMemoryRouter(
      [
        { path: '/login', element: <p>로그인 화면</p> },
        { path: '/login/callback', element: <LoginCallbackPage /> },
        { path: '/', element: <p>진입 분기</p> },
      ],
      { initialEntries: ['/login', callbackUrl()], initialIndex: 1 },
    )
    render(<RouterProvider router={router} />)
    await screen.findByText('진입 분기')

    await router.navigate(-1)

    expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
  })

  /** 카카오 로그인 창에서 "취소"를 누르면 이 주소로 돌아온다 */
  it('카카오가 error 를 보내면 안내를 띄우고 이동하지 않는다', async () => {
    const fetchMock = mockLoginResponse()
    const router = renderAt('/login/callback?error=access_denied')

    expect(await failureHeading()).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login/callback')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('code 가 없으면 서버를 부르지 않고 안내를 띄운다', async () => {
    const fetchMock = mockLoginResponse()
    renderAt('/login/callback')

    expect(await failureHeading()).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  /**
   * 공격자가 자기 계정의 `code` 를 담은 주소를 사장님에게 열게 하는 경우다. 막지 못하면
   * 사장님 브라우저가 공격자 계정으로 로그인되고, 그 뒤 입력하는 폐업 정보가 전부
   * 공격자 쪽에 쌓인다. 화면에는 아무 이상이 없어서 사장님은 알 수 없다.
   *
   * 셋 다 "서버를 부르지 않는다"를 본다. 요청이 나간 뒤에 막으면 늦다 —
   * 그 사이에 `code` 가 이미 토큰으로 바뀐다.
   */
  it('주소에 state 가 없으면 서버를 부르지 않는다', async () => {
    const fetchMock = mockLoginResponse()
    renderAt(callbackUrl({ state: null }))

    expect(await failureHeading()).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('state 가 다르면 서버를 부르지 않는다', async () => {
    const fetchMock = mockLoginResponse()
    renderAt(callbackUrl({ state: '꾸며낸-값' }))

    expect(await failureHeading()).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  /** 공격자가 보낸 주소를 새 탭에서 연 경우다. 돌아온 값도 저장분도 없다 */
  it('저장분이 없으면 서버를 부르지 않는다', async () => {
    const fetchMock = mockLoginResponse()
    renderAt('/login/callback?code=code-1')

    expect(await failureHeading()).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  /**
   * 토큰이 비어 오는 경우도 여기로 온다 — 서버에 노출 설정이 없거나 프록시가 헤더를
   * 지운 경우다. 성공으로 넘기면 로그인한 것처럼 보이다가 다음 요청에서 401이 난다.
   */
  it('서버가 실패하면 안내를 띄우고 토큰을 남기지 않는다', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 400 })))
    renderAt(callbackUrl())

    expect(await failureHeading()).toBeInTheDocument()
    expect(getAccessToken()).toBeNull()
  })
})
