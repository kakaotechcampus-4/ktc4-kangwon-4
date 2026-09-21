import { act, fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ResultInputPage } from './ResultInputPage'

/**
 * 앞뒤 화면을 실제 경로로 함께 등록한다. 대기 중에 화면을 떠나는 상황을 만들어야 해서
 * 이 화면만 띄워서는 확인할 수 없다.
 */
function renderFlow() {
  const router = createMemoryRouter(
    [
      { path: '/case', element: <p>현재 Case</p> },
      { path: '/results', element: <ResultInputPage /> },
      { path: '/replan', element: <p>재계획 결과</p> },
    ],
    { initialEntries: ['/case', '/results'], initialIndex: 1 },
  )

  render(<RouterProvider router={router} />)
  return router
}

/** 입력하고 제출한다. 클릭은 fireEvent로 — userEvent는 가짜 타이머와 맞물리면 멈춘다 */
function submit(text: string) {
  fireEvent.change(screen.getByLabelText(/어떻게 되었나요/), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: /알려주기/ }))
}

afterEach(() => {
  vi.useRealTimers()
})

describe('ResultInputPage', () => {
  /** 기다린 사람은 결과 화면으로 간다 — 아래 테스트가 이동 자체를 막아버리지 않았는지 함께 본다 */
  it('응답이 오면 재계획 화면으로 이동한다', async () => {
    vi.useFakeTimers()
    const router = renderFlow()

    submit('임대인이 철거하래요')
    await act(async () => {
      vi.runAllTimers()
    })

    expect(router.state.location.pathname).toBe('/replan')
  })

  /**
   * 응답을 기다리는 동안 사용자가 뒤로 갈 수 있다. 그때 이동을 그대로 실행하면
   * 일부러 빠져나온 화면으로 몇 초 뒤에 끌려간다 — 사용자에게는 고장으로 읽힌다.
   *
   * 화면이 아직 붙어 있는지 확인하는 한 줄로 막고 있어서, 파일을 옮기거나 고치는
   * 과정에서 조용히 사라지기 쉽다. 사라져도 기다리다 뒤로 가보지 않으면 모른다.
   */
  it('대기 중에 화면을 떠나면 이동하지 않는다', async () => {
    vi.useFakeTimers()
    const router = renderFlow()

    submit('임대인이 철거하래요')

    await act(async () => {
      await router.navigate(-1)
    })
    expect(router.state.location.pathname).toBe('/case')

    await act(async () => {
      vi.runAllTimers()
    })

    expect(router.state.location.pathname).toBe('/case')
  })
})
