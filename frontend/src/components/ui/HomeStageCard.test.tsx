import { fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'

import { HomeStageCard } from './HomeStageCard'

function renderCard(stage?: { number: number; title: string } | null, path = '/case', completed = false) {
  const router = createMemoryRouter(
    [
      { path: '/case', element: <HomeStageCard stage={stage} completed={completed} /> },
      { path: '/roadmap', element: <p>로드맵</p> },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

/** 지금 단계는 서버가 정한다. 화면이 짐작해 칠하면 정하지 않은 진행 상황이 확정된 것처럼 보인다 */
describe('HomeStageCard', () => {
  it('지금 단계를 모르면 이름을 칠하지 않고 곧 보여준다고만 한다', () => {
    renderCard(null)

    expect(screen.getByRole('link')).toHaveTextContent('폐업 단계')
    expect(screen.getByText('단계 정보는 곧 보여드릴게요')).toBeInTheDocument()
  })

  it('지금 단계를 받으면 그 단계 이름으로 부른다', () => {
    renderCard({ number: 2, title: '원상복구·철거' })

    expect(screen.getByRole('link')).toHaveTextContent('지금은 원상복구·철거 단계')
    expect(screen.queryByText('단계 정보는 곧 보여드릴게요')).not.toBeInTheDocument()
  })

  /** 서버가 1~5 밖의 단계를 주면 막대가 넘친다. 모르는 것으로 둔다 */
  it('없는 단계 번호면 모르는 것으로 둔다', () => {
    renderCard({ number: 7, title: '알 수 없음' })

    expect(screen.getByRole('link')).toHaveTextContent('폐업 단계')
  })

  /**
   * 마친 뒤에 "지금은 ○○ 단계"라고 하면 아직 그 단계에 있는 것으로 읽힌다. 단계 이름은 로드맵이 주는
   * 값이라 FE 가 마지막 단계 이름을 적지 않고, "곧 보여드릴게요"처럼 아직 모른다는 말도 하지 않는다
   */
  it('폐업 정리를 마쳤으면 지금 단계로 부르지 않고 곧 보여준다고도 하지 않는다', () => {
    renderCard({ number: 5, title: '세금·마무리' }, '/case', true)

    expect(screen.getByRole('link')).toHaveTextContent('폐업 단계')
    expect(screen.getByRole('link')).not.toHaveTextContent('지금은')
    expect(screen.queryByText('단계 정보는 곧 보여드릴게요')).not.toBeInTheDocument()
  })

  it('누르면 Mock 표시를 이어 로드맵으로 간다', () => {
    const router = renderCard(null, '/case?mock=done')

    fireEvent.click(screen.getByRole('link'))

    expect(router.state.location.pathname).toBe('/roadmap')
    expect(router.state.location.search).toBe('?mock=done')
  })
})
