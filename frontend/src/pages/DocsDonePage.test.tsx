import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'

import { DocsDonePage } from './DocsDonePage'

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/docs/check', element: <p>점검</p> },
      { path: '/docs/done', element: <DocsDonePage /> },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

/**
 * 서버는 점검을 통과했을 때만 제출 파일을 준다(#159). 통과하지 않았는데 이 화면이 뜨면
 * 사장님은 [파일 받기]를 누르고 나서야 실패를 안다.
 */
describe('DocsDonePage', () => {
  /*
   * TODO(#159): 서류 API 에 연결하면 "서버 점검이 ISSUES 면 돌려보낸다"를 따로 본다. 지금은 실서버가
   * 준비 중이라 늘 돌려보내고, Mock 은 이 화면을 통과한 점검으로 열어서 그 갈래를 만들 수 없다
   */
  it('통과한 점검이 없으면 점검 화면으로 돌려보낸다', () => {
    const router = renderAt('/docs/done')

    expect(router.state.location.pathname).toBe('/docs/check')
  })

  /** 가짜 파일을 진짜 제출 파일처럼 내려주면 안 된다. 받는 길은 서류 API 가 열릴 때 붙인다 */
  it('Mock 에서는 화면만 보여주고 파일 받기는 꺼 둔다', () => {
    renderAt('/docs/done?mock=docs-complete')

    expect(screen.getByRole('heading', { name: /정산 제출 파일을/ })).toBeInTheDocument()
    expect(screen.getByText('리본은 대신 제출하지 않아요. 이 파일로 소상공인24에서 사장님이 직접 제출해요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '파일 받기' })).toBeDisabled()
  })
})
