import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DocumentListResponse } from '../types/api'
import { ApplicantSheet, DocsCheckPage } from './DocsCheckPage'
import { completeCheck, issuesCheck, json, serve, serverDocument, serverList, status } from './docsTestServer'

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/docs', element: <p>서류함</p> },
      { path: '/docs/check', element: <DocsCheckPage /> },
      { path: '/docs/done', element: <p>정산 파일</p> },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

const sheet = () => screen.queryByRole('dialog', { name: '점검 전에 알려 주세요' })

afterEach(() => {
  vi.useRealTimers()
})

/** 서류 API(#159). 점검은 서버가 하고, 화면은 보낸 이름·날짜와 서버 결과만 옮긴다 */
describe('DocsCheckPage — 서버', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('이름과 폐업일을 보내고 서버가 돌려준 결과를 그린다', async () => {
    const { calls } = serve(json(serverList([serverDocument()])), json(serverList([serverDocument()], issuesCheck)))
    renderAt('/docs/check')

    fireEvent.click(await screen.findByRole('button', { name: '점검 시작하기' }))
    fireEvent.change(within(sheet()!).getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    fireEvent.change(within(sheet()!).getByLabelText('실제 폐업일 (선택)'), { target: { value: '2026-10-31' } })
    fireEvent.click(within(sheet()!).getByRole('button', { name: '점검하기' }))

    expect(await screen.findByText('정산 점검 목록에서 빠진 서류: 이체확인증')).toBeInTheDocument()
    expect(calls()[1]).toMatchObject({ url: expect.stringMatching(/\/cases\/documents\/check$/), method: 'POST' })
    expect(JSON.parse(calls()[1].body as string)).toEqual({ store_name: '봄날개인카페', applicant_name: '김리본', closure_date: '2026-10-31' })
  })

  it('이름이 없는 기존 가게의 상호를 신청인과 따로 보내고 재진입 때 저장한 이름을 보여준다', async () => {
    const { calls } = serve(
      json(serverList([serverDocument()], null, null)),
      json(serverList([serverDocument()], issuesCheck, '봄날개인카페')),
    )
    const router = renderAt('/docs/check')
    fireEvent.click(await screen.findByRole('button', { name: '점검 시작하기' }))
    expect(within(sheet()!).getByLabelText('가게 이름')).toHaveValue('')
    fireEvent.change(within(sheet()!).getByLabelText('가게 이름'), { target: { value: ' 봄날개인카페 ' } })
    fireEvent.change(within(sheet()!).getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    fireEvent.click(within(sheet()!).getByRole('button', { name: '점검하기' }))
    await screen.findByText('정산 점검 목록에서 빠진 서류: 이체확인증')
    expect(JSON.parse(calls()[1].body as string)).toEqual({ store_name: '봄날개인카페', applicant_name: '김리본', closure_date: null })

    await act(() => router.navigate('/docs'))
    await act(() => router.navigate('/docs/check'))
    fireEvent.click(await screen.findByRole('button', { name: '다시 점검하기' }))
    expect(within(sheet()!).getByLabelText('가게 이름')).toHaveValue('봄날개인카페')
    expect(within(sheet()!).getByLabelText('신청인 이름')).toHaveValue('')
  })

  /** 보내지 못했는데 아무 말이 없으면 점검이 된 줄 안다 */
  it('점검을 보내지 못하면 알리고 다시 할 수 있게 둔다', async () => {
    serve(json(serverList([serverDocument()])), status(500))
    renderAt('/docs/check')

    fireEvent.click(await screen.findByRole('button', { name: '점검 시작하기' }))
    fireEvent.change(within(sheet()!).getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    fireEvent.click(within(sheet()!).getByRole('button', { name: '점검하기' }))

    expect(await screen.findByText('점검을 보내지 못했어요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '점검 시작하기' })).toBeEnabled()
  })

  it('서류함을 불러오지 못하면 다시 불러올 수 있다', async () => {
    serve(status(500))
    renderAt('/docs/check')

    expect(await screen.findByText('서류함을 불러오지 못했어요.')).toBeInTheDocument()
  })
})

/** 점검 결과. 끝난 단계와 확인이 필요한 단계를 하나씩 둔다(Mock 은 시연용이라 바뀌어 테스트가 따로 들고 있는다) */
const PARTLY_CHECKED: DocumentListResponse['check'] = {
  status: 'ISSUES',
  steps: [
    { name: '서류 종류 나누기', status: 'DONE' },
    { name: '빠진 서류 찾기', status: 'NEEDS_CONFIRMATION' },
  ],
  issues: [{ code: 'MISSING_TRANSFER', document_ids: [], message: '정산 점검 목록에서 빠진 서류: 이체확인증' }],
  checked_at: '2026-11-04T10:00:00+09:00',
}

describe('DocsCheckPage — 점검 흐름', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  /** 신청인 이름 없이 점검하면 이체확인증을 맞춰 볼 수 없어 서버가 끝내지 않는다(#159) */
  it('점검 전에 이름을 묻고, 이름을 적어야 점검한다', async () => {
    serve(json(serverList([serverDocument()])))
    renderAt('/docs/check')

    fireEvent.click(await screen.findByRole('button', { name: '점검 시작하기' }))
    const ask = sheet()!
    const submit = within(ask).getByRole('button', { name: '점검하기' })
    expect(submit).toBeDisabled()

    fireEvent.change(within(ask).getByLabelText('신청인 이름'), { target: { value: '   ' } })
    expect(submit).toBeDisabled()

    fireEvent.change(within(ask).getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    expect(submit).toBeEnabled()
  })

  it('점검하는 동안 다시 누르지 못하게 하고, 끝나면 서버가 준 단계 상태를 그대로 보여준다', async () => {
    let finish: (response: Response) => void = () => {}
    serve(json(serverList([serverDocument()])), () => new Promise<Response>((resolve) => (finish = resolve)))
    renderAt('/docs/check')

    fireEvent.click(await screen.findByRole('button', { name: '점검 시작하기' }))
    fireEvent.change(within(sheet()!).getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    fireEvent.click(within(sheet()!).getByRole('button', { name: '점검하기' }))

    expect(await screen.findByRole('button', { name: '점검 중이에요' })).toBeDisabled()

    await act(async () => {
      finish(new Response(JSON.stringify(serverList([serverDocument()], PARTLY_CHECKED))))
    })
    expect(await screen.findByText('정산 점검 목록에서 빠진 서류: 이체확인증')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다시 점검하기' })).toBeInTheDocument()
    // 확인이 필요한 단계를 "완료"로 그리면 점검이 끝난 줄 안다
    expect(screen.getByText('빠진 서류 찾기').closest('li')).not.toHaveTextContent('완료')
    expect(screen.getByText('서류 종류 나누기').closest('li')).toHaveTextContent('완료')
  })

  /** 통과한 점검이 있으면 제출 파일로 간다 */
  it('점검을 통과했으면 결과 보기로 정산 파일 화면에 간다', async () => {
    serve(json(serverList([serverDocument()], completeCheck)))
    const router = renderAt('/docs/check')

    expect(await screen.findByRole('heading', { name: '서류 점검을 마쳤어요' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '결과 보기' }))

    expect(router.state.location.pathname).toBe('/docs/done')
  })
})

/** Mock 은 Preview 에서 화면을 보려고 둔다. 서버를 부르지 않고 그려지는지, 다음 화면에 Mock 표시를 잇는지만 본다 */
describe('DocsCheckPage — Mock', () => {
  it('?mock= 이면 서버를 부르지 않고 그리고, 다음 화면에 Mock 표시를 잇는다', () => {
    const { fetchMock } = serve(json(serverList([])))
    const router = renderAt('/docs/check?mock=docs-complete')

    fireEvent.click(screen.getByRole('button', { name: '결과 보기' }))

    expect(router.state.location.search).toBe('?mock=docs-complete')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('ApplicantSheet', () => {
  function renderSheet(initialStoreName: string | null = '봄날개인카페', onSubmit = vi.fn()) {
    render(<ApplicantSheet open initialStoreName={initialStoreName} onClose={() => {}} onSubmit={onSubmit} />)
    return onSubmit
  }

  /** 폐업일을 모르면 비워 보내야 서버가 "폐업일 미확인"으로 알려 준다. 빈 글자를 날짜로 보내면 422 다 */
  it('이름은 앞뒤 공백을 지우고, 폐업일을 비우면 없는 것으로 보낸다', () => {
    const onSubmit = renderSheet()

    fireEvent.change(screen.getByLabelText('신청인 이름'), { target: { value: ' 김리본 ' } })
    fireEvent.click(screen.getByRole('button', { name: '점검하기' }))

    expect(onSubmit).toHaveBeenCalledWith('봄날개인카페', '김리본', null)
  })

  it('폐업일을 적으면 그 날짜를 보낸다', () => {
    const onSubmit = renderSheet()

    fireEvent.change(screen.getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    fireEvent.change(screen.getByLabelText('실제 폐업일 (선택)'), { target: { value: '2026-10-31' } })
    fireEvent.click(screen.getByRole('button', { name: '점검하기' }))

    expect(onSubmit).toHaveBeenCalledWith('봄날개인카페', '김리본', '2026-10-31')
  })

  it('가게 이름은 공백만 있거나 50자를 넘으면 보내지 않고, 50자까지 받는다', () => {
    const onSubmit = renderSheet(null)
    const store = screen.getByLabelText('가게 이름')
    const submit = screen.getByRole('button', { name: '점검하기' })
    fireEvent.change(screen.getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    for (const value of ['   ', '가'.repeat(51)]) {
      fireEvent.change(store, { target: { value } })
      expect(submit).toBeDisabled()
      fireEvent.submit(store.closest('form')!)
      expect(onSubmit).not.toHaveBeenCalled()
    }
    fireEvent.change(store, { target: { value: '가'.repeat(50) } })
    expect(submit).toBeEnabled()
    expect(store).toHaveAttribute('maxlength', '50')
    fireEvent.click(submit)
    expect(onSubmit).toHaveBeenCalledWith('가'.repeat(50), '김리본', null)
  })
})
