import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MAX_UPLOAD_BYTES } from '../hooks/useDocuments'
import { MOCK_UPLOAD_MS } from '../mocks/documents'
import { DocsPage } from './DocsPage'

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <DocsPage />
    </MemoryRouter>,
  )
}

const uploadButton = () => screen.getByRole('button', { name: /서류 올리기/ })
const sheet = () => screen.queryByRole('dialog', { name: '서류 올리기' })

/** 시트에서 파일을 고른다. `<label>` 이 감싼 숨긴 입력이라 이름으로 찾는다 */
function pick(file: File, option = '파일에서 고르기') {
  fireEvent.click(uploadButton())
  fireEvent.change(within(sheet()!).getByLabelText(option), { target: { files: [file] } })
}

afterEach(() => {
  vi.useRealTimers()
})

/** 서류 API(#159)가 머지 전이다. 눌러도 받을 곳이 없는 버튼을 열어 두면 고장으로 읽힌다 */
describe('DocsPage — 서버', () => {
  it('받을 곳이 생기기 전에는 빈 상태와 꺼진 올리기 버튼을 둔다', () => {
    renderAt('/docs')

    expect(screen.getByText('아직 모인 서류가 없어요')).toBeInTheDocument()
    expect(uploadButton()).toBeDisabled()
  })
})

describe('DocsPage — Mock', () => {
  it('올린 서류를 종류 이름과 상태 배지로 늘어놓는다', () => {
    renderAt('/docs?mock=docs')

    const rows = screen.getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('철거공사내역서')
    expect(rows[0]).toHaveTextContent('보관 중')
    // 사진처럼 서버가 확신하지 못한 서류는 확인이 필요하다고 서버가 알려 준다
    expect(screen.getByText('철거 전 사진').closest('li')).toHaveTextContent('확인 필요')
  })

  /** 무엇이 빠졌는지는 서버 문구로만 말한다. FE가 필요한 서류 목록을 들고 있지 않는다 */
  it('점검에서 빠진 서류가 나오면 서버 문구 그대로 알린다', () => {
    renderAt('/docs?mock=docs-issues')

    expect(screen.getByText('정산 점검 목록에서 빠진 서류: 이체확인증')).toBeInTheDocument()
  })

  it('시트에서 파일을 고르면 시트를 닫고, 읽는 동안 기다리라고 알린 뒤 서류가 늘어난다', async () => {
    vi.useFakeTimers()
    renderAt('/docs?mock=docs')
    const before = screen.getAllByRole('listitem').length

    pick(new File(['%PDF'], '이체확인증.pdf', { type: 'application/pdf' }))

    expect(sheet()).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('서류를 읽는 중')
    // 한 장을 읽는 동안 또 올리면 결과가 서로를 덮는다
    expect(uploadButton()).toBeDisabled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MOCK_UPLOAD_MS)
    })
    expect(screen.getAllByRole('listitem')).toHaveLength(before + 1)
    expect(screen.getByText('이체확인증.pdf')).toBeInTheDocument()
  })

  /** 서버가 20MB 넘는 파일을 거절한다. 수십 초 올린 뒤에 거절당하지 않게 고르는 순간 막는다 */
  it('너무 큰 파일은 올리지 않고 바로 알린다', () => {
    renderAt('/docs?mock=docs')
    const big = new File(['x'], '큰사진.jpg', { type: 'image/jpeg' })
    Object.defineProperty(big, 'size', { value: MAX_UPLOAD_BYTES + 1 })

    pick(big, '앨범에서 고르기')

    expect(screen.getByText('파일이 너무 커요.')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('서류를 빼면 목록에서 사라진다', () => {
    renderAt('/docs?mock=docs')
    const before = screen.getAllByRole('listitem').length

    fireEvent.click(screen.getByRole('button', { name: '전자세금계산서 빼기' }))

    expect(screen.getAllByRole('listitem')).toHaveLength(before - 1)
    expect(screen.queryByText('전자세금계산서.pdf')).not.toBeInTheDocument()
  })
})
