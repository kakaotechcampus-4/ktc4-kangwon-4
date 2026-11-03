import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MAX_UPLOAD_BYTES } from '../hooks/useDocuments'
import { MOCK_UPLOAD_MS } from '../mocks/documents'
import { ConfirmSheet, DocsPage } from './DocsPage'

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
    // 사진처럼 서버가 확신하지 못한 서류는 확인하러 가는 버튼이 배지 자리에 온다. 확인한 서류에는 없다
    expect(screen.getByRole('button', { name: '철거 전 사진 확인하기' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '철거공사내역서 확인하기' })).not.toBeInTheDocument()
  })

  /** 고친 값이 다음 점검에 쓰인다. 확인한 뒤에도 "확인하기"가 남으면 점검이 끝나지 않는 줄 안다 */
  it('확인 시트에서 고친 값으로 확인하면 확인하기가 사라진다', () => {
    renderAt('/docs?mock=docs')

    fireEvent.click(screen.getByRole('button', { name: '폐업신고 접수증 확인하기' }))
    const ask = screen.getByRole('dialog', { name: '서류 확인하기' })
    // 서버가 꺼낸 값을 칸에 채워 보여준다
    const date = within(ask).getByLabelText('날짜')
    expect(date).toHaveValue('2026-10-31')

    fireEvent.change(date, { target: { value: '2026-11-01' } })
    fireEvent.click(within(ask).getByRole('button', { name: '맞아요, 확인했어요' }))

    expect(screen.queryByRole('dialog', { name: '서류 확인하기' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '폐업신고 접수증 확인하기' })).not.toBeInTheDocument()
    expect(screen.getByText('IMG_0420.jpg').closest('li')).toHaveTextContent('보관 중')
  })

  /** 종류를 모르는 채로 확인하면 점검이 그 서류를 어디에도 넣지 못한다 */
  it('종류를 모르는 서류는 종류를 골라야 확인할 수 있다', async () => {
    vi.useFakeTimers()
    renderAt('/docs?mock=docs')
    pick(new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MOCK_UPLOAD_MS)
    })

    fireEvent.click(screen.getByRole('button', { name: '종류 확인 필요 확인하기' }))
    const ask = screen.getByRole('dialog', { name: '서류 확인하기' })
    const submit = within(ask).getByRole('button', { name: '맞아요, 확인했어요' })
    expect(submit).toBeDisabled()

    fireEvent.change(within(ask).getByLabelText('서류 종류'), { target: { value: 'TRANSFER' } })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)

    expect(screen.getByText('scan.pdf').closest('li')).toHaveTextContent('이체확인증')
  })

  /** 빈 값으로 보내면 서버가 그것을 사장님이 확인한 값으로 남긴다 */
  it('값을 비우면 확인할 수 없다', () => {
    renderAt('/docs?mock=docs')

    fireEvent.click(screen.getByRole('button', { name: '폐업신고 접수증 확인하기' }))
    const ask = screen.getByRole('dialog', { name: '서류 확인하기' })
    fireEvent.change(within(ask).getByLabelText('날짜'), { target: { value: '  ' } })

    expect(within(ask).getByRole('button', { name: '맞아요, 확인했어요' })).toBeDisabled()
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

  /** 서버에서 지운 서류는 되돌릴 수 없다. 줄 끝 휴지통을 잘못 눌러도 바로 사라지면 안 된다 */
  it('빼기 전에 한 번 묻고, 그대로 두면 남긴다', () => {
    renderAt('/docs?mock=docs')
    const before = screen.getAllByRole('listitem').length

    fireEvent.click(screen.getByRole('button', { name: '전자세금계산서 빼기' }))
    const ask = screen.getByRole('dialog', { name: '이 서류를 뺄까요?' })
    expect(ask).toHaveTextContent('전자세금계산서 · 전자세금계산서.pdf')
    // 묻는 동안에는 아직 지우지 않았다
    expect(screen.getAllByRole('listitem')).toHaveLength(before)

    fireEvent.click(within(ask).getByRole('button', { name: '그대로 두기' }))

    expect(screen.queryByRole('dialog', { name: '이 서류를 뺄까요?' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(before)
  })

  it('빼기를 한 번 더 누르면 목록에서 사라진다', () => {
    renderAt('/docs?mock=docs')
    const before = screen.getAllByRole('listitem').length

    fireEvent.click(screen.getByRole('button', { name: '전자세금계산서 빼기' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: '이 서류를 뺄까요?' })).getByRole('button', { name: '빼기' }))

    expect(screen.getAllByRole('listitem')).toHaveLength(before - 1)
    expect(screen.queryByText('전자세금계산서.pdf')).not.toBeInTheDocument()
  })
})

/**
 * 확인 시트가 서버로 보낼 값. 서버는 받은 값만 사장님이 확인한 값으로 저장해서(#159),
 * 화면에 안 보이는 칸을 빼고 보내면 그 칸이 점검에서 "값 없음"이 된다.
 */
describe('ConfirmSheet', () => {
  it('화면에 안 보이는 칸도 원래 값 그대로 같이 보낸다', () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmSheet
        document={{
          id: 'doc-1',
          filename: 'transfer.jpg',
          kind: 'TRANSFER',
          kindLabel: '이체확인증',
          needsConfirmation: true,
          fields: [
            { name: 'amount', label: '금액', value: '3,300,000원' },
            { name: 'bank_code', label: null, value: '088' },
          ],
        }}
        onCancel={() => {}}
        onConfirm={onConfirm}
      />,
    )
    const ask = screen.getByRole('dialog', { name: '서류 확인하기' })

    // 이름을 모르는 칸은 보여주지 않는다
    expect(within(ask).getAllByRole('textbox')).toHaveLength(1)
    fireEvent.change(within(ask).getByLabelText('금액'), { target: { value: ' 3,000,000원 ' } })
    fireEvent.click(within(ask).getByRole('button', { name: '맞아요, 확인했어요' }))

    expect(onConfirm).toHaveBeenCalledWith('doc-1', 'TRANSFER', { amount: '3,000,000원', bank_code: '088' })
  })
  /** 안 보이는 칸이 비어 있어도 잠그면, 사장님은 무엇을 채워야 하는지 알 수 없다 */
  it('안 보이는 칸이 비어 있어도 확인할 수 있다', () => {
    render(
      <ConfirmSheet
        document={{
          id: 'doc-2',
          filename: 'receipt.jpg',
          kind: 'CLOSURE_RECEIPT',
          kindLabel: '폐업신고 접수증',
          needsConfirmation: true,
          fields: [{ name: 'bank_code', label: null, value: '' }],
        }}
        onCancel={() => {}}
        onConfirm={() => {}}
      />,
    )

    expect(screen.getByRole('button', { name: '맞아요, 확인했어요' })).toBeEnabled()
  })
})

/** 주 버튼은 하나다. 점검을 통과했는데 다시 점검하러 보내면 제출 파일을 찾지 못한다 */
describe('DocsPage — 다음 단계 버튼', () => {
  it('서류가 있으면 점검하러 가고, 통과했으면 제출 파일을 보러 간다', () => {
    renderAt('/docs?mock=docs')
    expect(screen.getByRole('button', { name: '정산 서류 점검하기' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '정산 제출 파일 보기' })).not.toBeInTheDocument()

    cleanup()
    renderAt('/docs?mock=docs-complete')
    expect(screen.getByRole('button', { name: '정산 제출 파일 보기' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '정산 서류 점검하기' })).not.toBeInTheDocument()
  })
})
