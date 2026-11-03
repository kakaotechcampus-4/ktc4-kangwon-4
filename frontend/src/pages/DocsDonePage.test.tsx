import { fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DocsDonePage } from './DocsDonePage'
import { completeCheck, issuesCheck, json, serve, serverDocument, serverList, status } from './docsTestServer'

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
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('서버 점검이 통과하지 않았으면 점검 화면으로 돌려보낸다', async () => {
    serve(json(serverList([serverDocument()], issuesCheck)))
    const router = renderAt('/docs/done')

    await vi.waitFor(() => expect(router.state.location.pathname).toBe('/docs/check'))
  })

  /** 로그인 헤더를 실어 받아야 해서 링크가 아니라 요청으로 받는다 */
  it('통과했으면 파일 받기로 제출 파일을 받는다', async () => {
    const { calls } = serve(json(serverList([serverDocument()], completeCheck)), () => new Response('PK'))
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:zip'), revokeObjectURL: vi.fn() }))
    renderAt('/docs/done')

    fireEvent.click(await screen.findByRole('button', { name: '파일 받기' }))

    await vi.waitFor(() => expect(calls()).toHaveLength(2))
    expect(calls()[1].url).toMatch(/\/cases\/documents\/settlement\.zip$/)
    await vi.waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
  })

  /** 그사이 서류가 바뀌면 서버가 422 로 막는다. 아무 말 없이 끝나면 받은 줄 안다 */
  it('파일을 받지 못하면 알린다', async () => {
    serve(json(serverList([serverDocument()], completeCheck)), status(422))
    renderAt('/docs/done')

    fireEvent.click(await screen.findByRole('button', { name: '파일 받기' }))

    expect(await screen.findByText('파일을 받지 못했어요.')).toBeInTheDocument()
  })

  /** 가짜 파일을 진짜 제출 파일처럼 내려주면 안 된다. 받는 길은 서류 API 가 열릴 때 붙인다 */
  it('Mock 에서는 화면만 보여주고 파일 받기는 꺼 둔다', () => {
    renderAt('/docs/done?mock=docs-complete')

    expect(screen.getByRole('heading', { name: /정산 제출 파일을/ })).toBeInTheDocument()
    expect(screen.getByText('리본은 대신 제출하지 않아요. 이 파일로 소상공인24에서 사장님이 직접 제출해요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '파일 받기' })).toBeDisabled()
  })
})
