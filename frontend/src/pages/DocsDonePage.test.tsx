import { act, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { REQUEST_TIMEOUT_MS } from '../lib/api'
import { UPLOAD_TIMEOUT_MS } from '../lib/documentsApi'
import { DocsDonePage, RELEASE_FILE_URL_MS } from './DocsDonePage'
import { completeCheck, hanging, issuesCheck, json, serve, serverDocument, serverList, status } from './docsTestServer'

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
    vi.useRealTimers()
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

  /** 아이폰 사파리는 누른 뒤에 파일을 읽어서, 바로 돌려주면 아무 말 없이 받기가 실패한다 */
  it('받은 파일 주소는 누르자마자 돌려주지 않고 잠시 뒤에 돌려준다', async () => {
    vi.useFakeTimers()
    serve(json(serverList([serverDocument()], completeCheck)), () => new Response('PK'))
    const revoke = vi.fn()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:zip'), revokeObjectURL: revoke }))
    renderAt('/docs/done')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    fireEvent.click(screen.getByRole('button', { name: '파일 받기' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(revoke).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RELEASE_FILE_URL_MS)
    })
    expect(revoke).toHaveBeenCalledWith('blob:zip')
  })

  /** ZIP 에는 사진·내역서가 여러 장 들어 크다. 다른 요청의 15초에 끊으면 휴대폰에서는 받을 수 없다 */
  it('제출 파일은 다른 요청의 제한 시간이 지나도 계속 받는다', async () => {
    vi.useFakeTimers()
    serve(json(serverList([serverDocument()], completeCheck)), hanging)
    renderAt('/docs/done')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    fireEvent.click(screen.getByRole('button', { name: '파일 받기' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1_000)
    })
    expect(screen.getByRole('button', { name: '받는 중이에요' })).toBeInTheDocument()
    expect(screen.queryByText('파일을 받지 못했어요.')).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPLOAD_TIMEOUT_MS - REQUEST_TIMEOUT_MS)
    })
    expect(screen.getByText('파일을 받지 못했어요.')).toBeInTheDocument()
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
