import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MOCK_UPLOAD_MS } from '../mocks/documents'
import { ApplicantSheet, DocsCheckPage } from './DocsCheckPage'

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

/** 서류 API(#159) 머지 전이다. 점검할 곳이 없는데 점검 버튼이 눌리면 고장으로 읽힌다 */
describe('DocsCheckPage — 서버', () => {
  it('준비 중이라고 알리고 서류함으로 가는 길만 둔다', () => {
    renderAt('/docs/check')

    expect(screen.getByText('서류 점검은 준비 중이에요.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '점검 시작하기' })).not.toBeInTheDocument()
  })
})

describe('DocsCheckPage — Mock', () => {
  /** 신청인 이름 없이 점검하면 이체확인증을 맞춰 볼 수 없어 서버가 끝내지 않는다(#159) */
  it('점검 전에 이름을 묻고, 이름을 적어야 점검한다', () => {
    renderAt('/docs/check?mock=docs')

    fireEvent.click(screen.getByRole('button', { name: '점검 시작하기' }))
    const ask = sheet()!
    const submit = within(ask).getByRole('button', { name: '점검하기' })
    expect(submit).toBeDisabled()

    fireEvent.change(within(ask).getByLabelText('신청인 이름'), { target: { value: '   ' } })
    expect(submit).toBeDisabled()

    fireEvent.change(within(ask).getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    expect(submit).toBeEnabled()
  })

  it('점검하는 동안 기다리게 하고, 서버가 찾은 것을 그대로 보여준다', async () => {
    vi.useFakeTimers()
    renderAt('/docs/check?mock=docs')

    fireEvent.click(screen.getByRole('button', { name: '점검 시작하기' }))
    fireEvent.change(within(sheet()!).getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    fireEvent.click(within(sheet()!).getByRole('button', { name: '점검하기' }))

    expect(screen.getByRole('button', { name: '점검 중이에요' })).toBeDisabled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MOCK_UPLOAD_MS)
    })
    // 확인이 필요한 서류가 남은 Mock 이라 확인할 것이 나온다. 문구는 서버(여기서는 Mock)가 쓴 그대로다
    expect(screen.getByText('정산 점검 목록에서 빠진 서류: 이체확인증')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다시 점검하기' })).toBeInTheDocument()
    // 확인이 필요한 단계를 "완료"로 그리면 점검이 끝난 줄 안다
    expect(screen.getByText('빠진 서류 찾기').closest('li')).not.toHaveTextContent('완료')
    expect(screen.getByText('서류 종류 나누기').closest('li')).toHaveTextContent('완료')
  })

  /** 통과한 점검이 있으면 제출 파일로 간다. Mock 표시는 다음 화면에도 이어진다 */
  it('점검을 통과했으면 결과 보기로 정산 파일 화면에 간다', () => {
    const router = renderAt('/docs/check?mock=docs-complete')

    expect(screen.getByRole('heading', { name: '서류 점검을 마쳤어요' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '결과 보기' }))

    expect(router.state.location.pathname).toBe('/docs/done')
    expect(router.state.location.search).toBe('?mock=docs-complete')
  })
})

describe('ApplicantSheet', () => {
  function renderSheet(onSubmit = vi.fn()) {
    render(<ApplicantSheet open onClose={() => {}} onSubmit={onSubmit} />)
    return onSubmit
  }

  /** 폐업일을 모르면 비워 보내야 서버가 "폐업일 미확인"으로 알려 준다. 빈 글자를 날짜로 보내면 422 다 */
  it('이름은 앞뒤 공백을 지우고, 폐업일을 비우면 없는 것으로 보낸다', () => {
    const onSubmit = renderSheet()

    fireEvent.change(screen.getByLabelText('신청인 이름'), { target: { value: ' 김리본 ' } })
    fireEvent.click(screen.getByRole('button', { name: '점검하기' }))

    expect(onSubmit).toHaveBeenCalledWith('김리본', null)
  })

  it('폐업일을 적으면 그 날짜를 보낸다', () => {
    const onSubmit = renderSheet()

    fireEvent.change(screen.getByLabelText('신청인 이름'), { target: { value: '김리본' } })
    fireEvent.change(screen.getByLabelText('실제 폐업일 (선택)'), { target: { value: '2026-10-31' } })
    fireEvent.click(screen.getByRole('button', { name: '점검하기' }))

    expect(onSubmit).toHaveBeenCalledWith('김리본', '2026-10-31')
  })
})
