import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ConfirmChangePage } from './ConfirmChangePage'

function renderPage() {
  const router = createMemoryRouter([{ path: '/confirm', element: <ConfirmChangePage /> }], {
    initialEntries: ['/confirm'],
  })

  render(<RouterProvider router={router} />)
}

/**
 * 앞뒤 화면을 실제 경로로 함께 등록한다. 히스토리가 어떻게 쌓이는지를 보는 테스트라
 * 이 화면만 띄워서는 확인할 수 없다. `/results`에서 넘어온 상황을 흉내 낸다.
 */
function renderFlow() {
  const router = createMemoryRouter(
    [
      { path: '/results', element: <p>결과 입력</p> },
      { path: '/confirm', element: <ConfirmChangePage /> },
      { path: '/replan', element: <p>재계획 결과</p> },
    ],
    { initialEntries: ['/results', '/confirm'], initialIndex: 1 },
  )

  render(<RouterProvider router={router} />)
  return router
}

afterEach(() => {
  vi.useRealTimers()
})

/**
 * 되돌리기 API가 계약에서 빠져, 잘못 반영된 값을 되돌릴 수 있는 지점은 이 화면뿐이다.
 * 그래서 고르지 않은 항목이 하나라도 있으면 진행할 수 없어야 한다 —
 * 기본 선택을 두지 않는 것과 같은 이유다.
 */
describe('ConfirmChangePage', () => {
  it('고르기 전에는 진행할 수 없다', () => {
    renderPage()

    expect(screen.getByRole('button', { name: /이대로 진행하기/ })).toBeDisabled()
  })

  it('충돌 항목을 고르면 진행할 수 있다', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: /이번에 말씀하신 내용/ }))

    expect(screen.getByRole('button', { name: /이대로 진행하기/ })).toBeEnabled()
  })

  /**
   * 확인을 마친 화면이 히스토리에 남아 있으면, 뒤로 가서 같은 결정을 다시 제출할 수 있다.
   * 표시만 어긋나는 다른 화면과 달리 이쪽은 서버 상태를 바꾸는 요청이라 피해가 다르다.
   *
   * `navigate`의 `replace` 옵션 하나로 막고 있어서, 파일을 옮기거나 고치는 과정에서
   * 조용히 사라지기 쉽다. 사라져도 화면은 그대로여서 뒤로가기를 해보지 않으면 모른다.
   */
  it('확인을 마치면 그 화면으로 뒤로 돌아갈 수 없다', async () => {
    // 클릭은 fireEvent로 한다. userEvent는 내부 지연이 있어 가짜 타이머와 맞물리면 멈춘다
    vi.useFakeTimers()
    const router = renderFlow()

    fireEvent.click(screen.getByRole('button', { name: /이번에 말씀하신 내용/ }))
    fireEvent.click(screen.getByRole('button', { name: /이대로 진행하기/ }))

    // 처리 중 지연을 흘려보낸다. act 안에서는 동기 타이머 함수를 쓴다
    await act(async () => {
      vi.runAllTimers()
    })
    expect(router.state.location.pathname).toBe('/replan')

    await act(async () => {
      await router.navigate(-1)
    })

    expect(router.state.location.pathname).toBe('/results')
  })
})
