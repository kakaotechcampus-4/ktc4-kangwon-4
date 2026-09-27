import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { markCaseCreated } from '../lib/caseState'
import { EntryPage } from './EntryPage'

/**
 * 도착지를 글자로 확인한다. 라우터 객체의 경로를 읽어도 되지만, 화면이 실제로
 * 그려졌는지까지 보려면 렌더 결과를 보는 쪽이 낫다.
 */
function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/', element: <EntryPage /> },
      { path: '/case', element: <p>현재 Case</p> },
      { path: '/start', element: <p>시작 화면</p> },
    ],
    { initialEntries: [path] },
  )

  render(<RouterProvider router={router} />)
  return router
}

/**
 * 이 화면은 보낼 곳만 정한다. 판단이 틀리면 Case가 있는 사용자에게 "시작하기"를 다시
 * 물어보거나, 없는 사용자에게 빈 Case 화면을 보여주게 된다.
 */
describe('EntryPage', () => {
  it('Case를 만든 적이 없으면 시작 화면으로 보낸다', async () => {
    renderAt('/')

    expect(await screen.findByText('시작 화면')).toBeInTheDocument()
  })

  it('Case를 만들었으면 현재 Case로 보낸다', async () => {
    markCaseCreated()
    renderAt('/')

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })

  it('Case를 만들었어도 ?mock=no-case면 시작 화면으로 보낸다', async () => {
    markCaseCreated()
    renderAt('/?mock=no-case')

    expect(await screen.findByText('시작 화면')).toBeInTheDocument()
  })

  /**
   * 리뷰어가 링크 하나로 흐름을 따라간다. 여기서 쿼리가 끊기면 다음 화면이 기본 Mock으로
   * 돌아가, 보려던 예외 상황이 아닌 다른 화면이 뜬다.
   */
  it('보낼 때 ?mock= 을 그대로 이어준다', async () => {
    const router = renderAt('/?mock=no-case')
    await screen.findByText('시작 화면')

    expect(router.state.location.search).toBe('?mock=no-case')
  })

  /**
   * 뒤로가기로 여기 돌아오면 다시 튕겨 나가 빠져나갈 수 없다.
   * `/case`에서 뒤로 눌렀을 때 진입 분기가 아니라 그 앞으로 가야 한다.
   */
  it('히스토리에 남지 않는다', async () => {
    const router = createMemoryRouter(
      [
        { path: '/', element: <EntryPage /> },
        { path: '/case', element: <p>현재 Case</p> },
        { path: '/start', element: <p>시작 화면</p> },
      ],
      { initialEntries: ['/case', '/'], initialIndex: 1 },
    )

    render(<RouterProvider router={router} />)
    await screen.findByText('시작 화면')

    await router.navigate(-1)

    expect(await screen.findByText('현재 Case')).toBeInTheDocument()
  })
})
