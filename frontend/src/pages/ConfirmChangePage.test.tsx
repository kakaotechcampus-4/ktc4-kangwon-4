import { act, fireEvent, render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ConfirmView } from '../types/view'
import { ConfirmChangePage } from './ConfirmChangePage'

/**
 * 이 화면의 규칙을 확인하는 데 필요한 최소한의 데이터.
 *
 * Mock에 기대지 않고 여기 두는 이유는, `mocks/resultFlow.ts`가 화면을 눈으로 보려고
 * 만든 데이터라 언제든 바뀌기 때문이다. 충돌 항목을 하나로 줄이는 순간
 * "다 고르기 전에는 진행할 수 없다"를 검증할 수 없게 된다.
 *
 * 일부러 두 건을 둔다. 한 건짜리로는 "하나라도 안 골랐으면 막는다"와
 * "아무것도 안 골랐으면 막는다"가 같은 상황이 되어 구분되지 않는다.
 */
const TWO_CONFLICTS: ConfirmView = {
  rawInput: '다시 확인했는데 철거까지 해야 한대요.',
  conflicts: [
    {
      key: 'demolition_required',
      label: '철거 필요 여부',
      storedValue: '필요 없음',
      incomingValue: '필요함',
    },
    {
      key: 'restoration_scope',
      label: '원상복구 범위',
      storedValue: '일부만',
      incomingValue: '전체',
    },
  ],
}

/**
 * 앞뒤 화면을 실제 경로로 함께 등록한다. 히스토리가 어떻게 쌓이는지를 보는 테스트가
 * 있어서 이 화면만 띄워서는 확인할 수 없다. `/results`에서 넘어온 상황을 흉내 낸다.
 */
function renderWith(view: ConfirmView | null) {
  const router = createMemoryRouter(
    [
      { path: '/', element: <p>진입 분기</p> },
      { path: '/results', element: <p>결과 입력</p> },
      { path: '/confirm', element: <ConfirmChangePage /> },
      { path: '/replan', element: <p>재계획 결과</p> },
    ],
    {
      initialEntries: ['/results', { pathname: '/confirm', state: view }],
      initialIndex: 1,
    },
  )

  render(<RouterProvider router={router} />)
  return router
}

const proceedButton = () => screen.getByRole('button', { name: /이대로 진행하기/ })

/**
 * 새 값 쪽을 고른다.
 *
 * 설명("이번에 말씀하신 내용")과 값이 붙은 `span` 두 개라 접근 이름이 띄어쓰기 없이
 * 이어진다. 그 모양에 기대면 마크업을 손볼 때마다 깨지므로 값으로만 찾는다.
 */
function chooseIncoming(value: string) {
  fireEvent.click(screen.getByRole('button', { name: new RegExp(value) }))
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
    renderWith(TWO_CONFLICTS)

    expect(proceedButton()).toBeDisabled()
  })

  /** 여러 건이 한 화면에 오면 앞의 것만 고르고 넘어가려 한다 */
  it('일부만 고르면 아직 진행할 수 없다', () => {
    renderWith(TWO_CONFLICTS)

    chooseIncoming('필요함')

    expect(proceedButton()).toBeDisabled()
  })

  it('모든 항목을 고르면 진행할 수 있다', () => {
    renderWith(TWO_CONFLICTS)

    chooseIncoming('필요함')
    chooseIncoming('전체')

    expect(proceedButton()).toBeEnabled()
  })

  /** 고를 것이 없으면 이 화면의 존재 이유가 없다. 막다른 골목이 되지 않게 돌려보낸다 */
  it('충돌 항목이 비어 있으면 진입 분기로 돌려보낸다', async () => {
    renderWith({ rawInput: '철거해야 한대요.', conflicts: [] })

    expect(await screen.findByText('진입 분기')).toBeInTheDocument()
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
    const router = renderWith(TWO_CONFLICTS)

    chooseIncoming('필요함')
    chooseIncoming('전체')
    fireEvent.click(proceedButton())

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

  /**
   * 라우터 state 없이 주소만으로 열었을 때 Mock으로 그려지는지 하나만 확인한다.
   * 리뷰어가 링크로 이 화면을 보는 경로라, 끊기면 화면을 볼 방법이 없다.
   *
   * 나머지 테스트는 state를 직접 태운다. 여기에 전부 기대면 Mock 데이터를 손볼 때마다
   * 관계없는 테스트가 함께 깨진다.
   */
  it('state 없이 열면 Mock으로 그린다', () => {
    renderWith(null)

    expect(proceedButton()).toBeInTheDocument()
  })
})
