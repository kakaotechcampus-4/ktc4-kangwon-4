import { fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { logInWithMock, saveTokens } from '../lib/auth'
import { CaseCreatePage } from './CaseCreatePage'

function mockPost(status: number) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(status === 200 ? JSON.stringify({ id: 1 }) : null, { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPage() {
  const router = createMemoryRouter(
    [
      { path: '/cases/new', element: <CaseCreatePage /> },
      { path: '/case', element: <p>현재 Case</p> },
      { path: '/login', element: <p>로그인 화면</p> },
    ],
    { initialEntries: ['/cases/new'] },
  )

  render(<RouterProvider router={router} />)
  return router
}

/** 필수 세 가지만 채운다. 직원 수와 예정일은 비워 둔 채로 보낸다 */
function fillRequired() {
  fireEvent.change(screen.getByLabelText('어떤 가게인가요?'), { target: { value: '카페' } })
  fireEvent.click(screen.getByRole('radio', { name: /아니에요/ }))
  fireEvent.click(screen.getByRole('radio', { name: /월세를 내고 있어요/ }))
}

const submitButton = () => screen.getByRole('button', { name: '시작하기' })

afterEach(() => {
  vi.unstubAllGlobals()
})

/**
 * 이 화면이 사장님이 처음으로 무언가를 서버에 남기는 자리다. 여기서 값이 잘못 나가면
 * Case 하나가 틀린 채로 만들어지고, 회원당 하나라 다시 만들 수도 없다.
 */
describe('CaseCreatePage', () => {
  it('폼 값을 서버 모양으로 보낸다', () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = mockPost(200)
    renderPage()

    fillRequired()
    fireEvent.click(submitButton())

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toEqual({
      business_type: '카페',
      franchise_status: false,
      lease_status: 'LEASED_PAID',
      employee_count: null,
      planned_closure_date: null,
    })
  })

  it('저장되면 현재 Case로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockPost(200)
    renderPage()

    fillRequired()
    fireEvent.click(submitButton())

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })

  /**
   * 회원당 Case는 하나다. 두 탭에서 동시에 만들거나, 요청이 오래 걸리다 끊겨 다시 눌렀을 때
   * 온다. 이미 만들어졌다는 뜻이라 실패 화면을 보여주면 사장님이 다시 만들려 든다.
   */
  it('이미 Case가 있으면 실패가 아니라 현재 Case로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockPost(409)
    renderPage()

    fillRequired()
    fireEvent.click(submitButton())

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })

  it('인증이 통하지 않으면 로그인 화면으로 보낸다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockPost(401)
    renderPage()

    fillRequired()
    fireEvent.click(submitButton())

    expect(await screen.findByText('로그인 화면')).toBeInTheDocument()
  })

  /** 적어 넣은 값이 남아 있어야 다시 시도할 수 있다 */
  it('실패하면 안내를 띄우고 입력한 값을 남긴다', async () => {
    saveTokens('access-1', 'refresh-1')
    mockPost(500)
    renderPage()

    fillRequired()
    fireEvent.click(submitButton())

    expect(await screen.findByText('저장하지 못했습니다.')).toBeInTheDocument()
    expect(screen.getByLabelText('어떤 가게인가요?')).toHaveValue('카페')
  })

  /** Preview에서 가짜 로그인으로 화면을 보는 리뷰어다. 서버를 부르면 401로 막힌다 */
  it('가짜 세션이면 서버를 부르지 않고 넘어간다', async () => {
    logInWithMock()
    const fetchMock = mockPost(200)
    renderPage()

    fillRequired()
    fireEvent.click(submitButton())

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
