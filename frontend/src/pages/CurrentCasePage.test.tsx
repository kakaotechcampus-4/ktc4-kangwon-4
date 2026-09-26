import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { CurrentCasePage } from './CurrentCasePage'

/**
 * 화면이 어떤 Mock을 쓸지는 `?mock=` 쿼리가 정한다.
 * 컴포넌트에 데이터를 직접 넣지 않고 주소로 고르는 것은, 리뷰어가 링크로 보는 경로와
 * 테스트가 같은 길을 타게 하려는 것이다 — 그래야 Mock 전환이 깨져도 여기서 잡힌다.
 */
function renderAt(path: string) {
  const router = createMemoryRouter([{ path: '/', element: <CurrentCasePage /> }], {
    initialEntries: [path],
  })

  render(<RouterProvider router={router} />)
}

/**
 * 이 화면의 규칙은 `types/view.ts`의 표에 있다. 핵심은 "막혀 있는 것 없음"을
 * **할 일이 있을 때만** 보여주는 것이다. 할 일을 못 정한 상태에서 막힌 게 없다고 하면
 * 사용자는 다 끝났다는 긍정 신호로 읽는다.
 */
describe('CurrentCasePage', () => {
  it('막고 있는 것이 있으면 "막혀 있는 것 없음"을 보여주지 않는다', () => {
    renderAt('/')

    expect(screen.getByRole('heading', { name: '지금 할 일' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '막혀 있는 것 없음' })).not.toBeInTheDocument()
  })

  it('막고 있는 것이 없고 할 일이 있으면 "막혀 있는 것 없음"을 보여준다', () => {
    renderAt('/?mock=no-blocker')

    expect(screen.getByRole('heading', { name: '지금 할 일' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '막혀 있는 것 없음' })).toBeInTheDocument()
  })

  it('할 일을 정하지 못했으면 정보 부족을 알리고 "막혀 있는 것 없음"은 숨긴다', () => {
    renderAt('/?mock=insufficient')

    expect(screen.getByRole('heading', { name: '아직 정할 수 없음' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '지금 할 일' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '막혀 있는 것 없음' })).not.toBeInTheDocument()
  })
})
