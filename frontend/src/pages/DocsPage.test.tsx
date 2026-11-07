import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MAX_UPLOAD_BYTES } from '../hooks/useDocuments'
import { REQUEST_TIMEOUT_MS } from '../lib/api'
import { UPLOAD_TIMEOUT_MS } from '../lib/documentsApi'
import type { DocumentResponse } from '../types/api'
import { ConfirmSheet, DocsPage } from './DocsPage'
import { type Answer, completeCheck, hanging, issuesCheck, json, serve, serverDocument, serverList, status } from './docsTestServer'

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
/**
 * 서류 API(#159). 서류함은 사장님이 정산에 낼 서류를 모으는 곳이라, 불러오지 못한 것을 빈 서류함으로
 * 그리거나 저장이 끝나기 전에 목록을 바꾸면 올린 서류가 사라지거나 생긴 줄 안다.
 */
describe('DocsPage — 서버', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('들어올 때 서류 목록을 불러와 그린다', async () => {
    const { calls } = serve(json(serverList([serverDocument()])))
    renderAt('/docs')

    expect(await screen.findByText('transfer.pdf')).toBeInTheDocument()
    expect(calls()[0].url).toMatch(/\/cases\/documents$/)
  })

  it('불러오지 못하면 그렇다고 말하고 다시 불러올 수 있다', async () => {
    serve(status(500), json(serverList([serverDocument()])))
    renderAt('/docs')

    fireEvent.click(await screen.findByRole('button', { name: '다시 불러오기' }))

    expect(await screen.findByText('transfer.pdf')).toBeInTheDocument()
  })

  /** Case 가 없으면 서버가 404 를 준다. 서류가 없는 것과 같다 */
  it('Case 가 없으면 빈 서류함으로 둔다', async () => {
    serve(status(404))
    renderAt('/docs')

    expect(await screen.findByText('아직 모인 서류가 없어요')).toBeInTheDocument()
  })

  /** 깨진 목록을 빈 서류함으로 그리면 사장님은 올린 서류가 사라진 줄 안다 */
  it('받은 목록을 읽지 못하면 빈 서류함이 아니라 불러오지 못한 것으로 둔다', async () => {
    serve(json({ documents: 'none' }))
    renderAt('/docs')

    expect(await screen.findByText('서류함을 불러오지 못했어요')).toBeInTheDocument()
    expect(screen.queryByText('아직 모인 서류가 없어요')).not.toBeInTheDocument()
  })

  /** 파일 한 장을 그대로 보내고, 서버가 돌려준 목록으로 바꾼다 */
  it('고른 파일을 올리고 서버가 돌려준 목록을 그린다', async () => {
    const { calls } = serve(json(serverList([])), json(serverList([serverDocument({ filename: 'scan.pdf' })])))
    renderAt('/docs')
    await screen.findByText('아직 모인 서류가 없어요')

    pick(new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }))

    expect(await screen.findByText('scan.pdf')).toBeInTheDocument()
    const sent = calls()[1]
    expect(sent.method).toBe('POST')
    expect(sent.body).toBeInstanceOf(FormData)
    expect((sent.body as FormData).get('file')).toBeInstanceOf(File)
  })

  it.each([
    [502, '서류를 읽지 못했어요.'],
    [422, '이 파일은 올릴 수 없어요.'],
    [500, '서류를 올리지 못했어요.'],
  ])('올리기가 %s 이면 알맞게 안내하고 목록은 그대로 둔다', async (code, title) => {
    serve(json(serverList([serverDocument()])), status(code))
    renderAt('/docs')
    await screen.findByText('transfer.pdf')

    pick(new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }))

    expect(await screen.findByText(title)).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
  })

  /** 안전 검사가 막은 서류는 다시 올려도 같은 판정이다. 다시 올리라 하지 않고 판정에 맞게 알린다 */
  it.each([
    ['AGENT_SAFETY_REFUSE', '이 파일은 자동으로 읽지 않았어요.'],
    ['AGENT_SAFETY_CRISIS_SUPPORT', '지금 많이 힘드시다면, 혼자 견디지 않으셔도 돼요.'],
  ])('올리기가 안전 검사(%s)에 막히면 그 판정에 맞게 안내한다', async (code, title) => {
    const blocked = () => new Response(JSON.stringify({ detail: { code, message: '서버 문구' } }), { status: 422 })
    serve(json(serverList([serverDocument()])), blocked)
    renderAt('/docs')
    await screen.findByText('transfer.pdf')

    pick(new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }))

    expect(await screen.findByText(title)).toBeInTheDocument()
    expect(screen.queryByText('이 파일은 올릴 수 없어요.')).not.toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    if (code === 'AGENT_SAFETY_CRISIS_SUPPORT') {
      expect(screen.getByRole('link', { name: '상담전화 109' })).toHaveAttribute('href', 'tel:109')
    }
  })

  /** 서버는 끊긴 뒤에도 읽기를 마치고 저장해 둔다. 같은 파일을 다시 올리면 된다고 알린다 */
  it('올리기를 오래 기다리다 끊기면 다시 올리라고 알린다', async () => {
    vi.useFakeTimers()
    serve(json(serverList([])), hanging)
    renderAt('/docs')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    pick(new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }))
    // 다른 요청의 제한 시간(15초)이 지나도 서류는 아직 읽는 중이다
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
    })
    expect(screen.getByRole('status')).toHaveTextContent('서류를 읽는 중')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPLOAD_TIMEOUT_MS - REQUEST_TIMEOUT_MS)
    })

    expect(screen.getByText('읽는 데 시간이 오래 걸려 기다림이 끊겼어요.')).toBeInTheDocument()
  })

  /** 올리기는 수십 초 걸린다. 그사이 다른 서류를 뺐다고 "올리는 중"이 사라지면, 다시 고른 파일이 말없이 버려진다 */
  it('올리는 중에 다른 서류를 빼도 올리는 중 표시와 잠금을 지우지 않는다', async () => {
    serve(json(serverList([serverDocument()])), hanging, json(serverList([])))
    renderAt('/docs')
    await screen.findByText('transfer.pdf')

    pick(new File(['%PDF'], 'scan.pdf', { type: 'application/pdf' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('서류를 읽는 중'))
    fireEvent.click(screen.getByRole('button', { name: '이체확인증 빼기' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: '이 서류를 뺄까요?' })).getByRole('button', { name: '빼기' }))
    await waitFor(() => expect(screen.queryByText('transfer.pdf')).not.toBeInTheDocument())

    expect(screen.getByRole('status')).toHaveTextContent('서류를 읽는 중')
    expect(uploadButton()).toBeDisabled()
  })

  it('빼기를 확인하면 DELETE 를 보내고 서버가 돌려준 목록을 그린다', async () => {
    const { calls } = serve(json(serverList([serverDocument()])), json(serverList([])))
    renderAt('/docs')
    await screen.findByText('transfer.pdf')

    fireEvent.click(screen.getByRole('button', { name: '이체확인증 빼기' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: '이 서류를 뺄까요?' })).getByRole('button', { name: '빼기' }))

    expect(await screen.findByText('아직 모인 서류가 없어요')).toBeInTheDocument()
    expect(calls()[1]).toMatchObject({ url: expect.stringMatching(/\/cases\/documents\/doc-1$/), method: 'DELETE' })
  })

  /** 빼기가 실패했는데 목록에서 지우면, 서버에는 남은 서류를 사장님은 뺀 줄 안다 */
  it('빼기가 실패하면 목록을 그대로 두고 알린다', async () => {
    serve(json(serverList([serverDocument()])), status(500))
    renderAt('/docs')
    await screen.findByText('transfer.pdf')

    fireEvent.click(screen.getByRole('button', { name: '이체확인증 빼기' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: '이 서류를 뺄까요?' })).getByRole('button', { name: '빼기' }))

    expect(await screen.findByText('바꾼 내용을 저장하지 못했어요.')).toBeInTheDocument()
    expect(screen.getByText('transfer.pdf')).toBeInTheDocument()
  })

  it('확인한 종류와 값을 보낸다', async () => {
    const { calls } = serve(
      json(serverList([serverDocument({ needs_confirmation: true })])),
      json(serverList([serverDocument()])),
    )
    renderAt('/docs')

    fireEvent.click(await screen.findByRole('button', { name: '이체확인증 확인하기' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: '서류 확인하기' })).getByRole('button', { name: '맞아요, 확인했어요' }))

    await vi.waitFor(() => expect(calls()).toHaveLength(2))
    expect(calls()[1]).toMatchObject({ url: expect.stringMatching(/\/cases\/documents\/doc-1\/confirm$/), method: 'POST' })
    expect(JSON.parse(calls()[1].body as string)).toEqual({ kind: 'TRANSFER', confirmed_fields: { amount: '3,300,000원' } })
  })
})

/** 화면 테스트가 쓰는 서류들. Mock(`mocks/documents.ts`)은 시연용이라 바뀌므로 테스트가 따로 들고 있는다 */
const STATEMENT = serverDocument({
  document_id: 'doc-statement',
  filename: 'statement.pdf',
  kind: 'CONSTRUCTION_STATEMENT',
  kind_label: '철거공사내역서',
})
const RECEIPT = serverDocument({
  document_id: 'doc-receipt',
  filename: 'IMG_0420.jpg',
  kind: 'CLOSURE_RECEIPT',
  kind_label: '폐업신고 접수증',
  needs_confirmation: true,
  fields: [{ name: 'date', label: '날짜', value: '2026-10-31', page: 1 }],
})
const UNKNOWN = serverDocument({
  document_id: 'doc-unknown',
  filename: 'scan.pdf',
  kind: 'UNKNOWN',
  kind_label: '종류 확인 필요',
  needs_confirmation: true,
  fields: [],
})

/** 서버가 이 서류들을 주는 서류함을 띄우고 그려질 때까지 기다린다. 뒤이은 요청의 답도 차례로 준다 */
async function renderDocs(documents: DocumentResponse[], ...after: Answer[]) {
  const server = serve(json(serverList(documents)), ...after)
  renderAt('/docs')
  await screen.findByText(documents[0].filename)
  return server
}

describe('DocsPage — 서류 줄과 확인', () => {
  it('올린 서류를 종류 이름과 상태 배지로 늘어놓는다', async () => {
    await renderDocs([STATEMENT, RECEIPT])

    const row = screen.getByText('statement.pdf').closest('li')
    expect(row).toHaveTextContent('철거공사내역서')
    expect(row).toHaveTextContent('보관 중')
    // 서버가 확신하지 못한 서류는 확인하러 가는 버튼이 배지 자리에 온다. 확인한 서류에는 없다
    expect(screen.getByRole('button', { name: '폐업신고 접수증 확인하기' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '철거공사내역서 확인하기' })).not.toBeInTheDocument()
  })

  /** 고친 값이 다음 점검에 쓰인다. 확인한 뒤에도 "확인하기"가 남으면 점검이 끝나지 않는 줄 안다 */
  it('확인 시트에서 서버가 꺼낸 값을 보여주고, 확인하면 확인하기가 사라진다', async () => {
    await renderDocs([RECEIPT], json(serverList([{ ...RECEIPT, needs_confirmation: false }])))

    fireEvent.click(screen.getByRole('button', { name: '폐업신고 접수증 확인하기' }))
    const ask = screen.getByRole('dialog', { name: '서류 확인하기' })
    const date = within(ask).getByLabelText('날짜')
    expect(date).toHaveValue('2026-10-31')

    fireEvent.change(date, { target: { value: '2026-11-01' } })
    fireEvent.click(within(ask).getByRole('button', { name: '맞아요, 확인했어요' }))

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: '폐업신고 접수증 확인하기' })).not.toBeInTheDocument(),
    )
    expect(screen.getByText('IMG_0420.jpg').closest('li')).toHaveTextContent('보관 중')
  })

  /** 종류를 모르는 채로 확인하면 점검이 그 서류를 어디에도 넣지 못한다 */
  it('종류를 모르는 서류는 종류를 골라야 확인할 수 있다', async () => {
    const { calls } = await renderDocs(
      [UNKNOWN],
      json(serverList([{ ...UNKNOWN, kind: 'TRANSFER', kind_label: '이체확인증', needs_confirmation: false }])),
    )

    fireEvent.click(screen.getByRole('button', { name: '종류 확인 필요 확인하기' }))
    const ask = screen.getByRole('dialog', { name: '서류 확인하기' })
    const submit = within(ask).getByRole('button', { name: '맞아요, 확인했어요' })
    expect(submit).toBeDisabled()

    fireEvent.change(within(ask).getByLabelText('서류 종류'), { target: { value: 'TRANSFER' } })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)

    await waitFor(() => expect(screen.getByText('scan.pdf').closest('li')).toHaveTextContent('이체확인증'))
    expect(JSON.parse(calls()[1].body as string)).toMatchObject({ kind: 'TRANSFER' })
  })

  /** 빈 값으로 보내면 서버가 그것을 사장님이 확인한 값으로 남긴다 */
  it('값을 비우면 확인할 수 없다', async () => {
    await renderDocs([RECEIPT])

    fireEvent.click(screen.getByRole('button', { name: '폐업신고 접수증 확인하기' }))
    const ask = screen.getByRole('dialog', { name: '서류 확인하기' })
    fireEvent.change(within(ask).getByLabelText('날짜'), { target: { value: '  ' } })

    expect(within(ask).getByRole('button', { name: '맞아요, 확인했어요' })).toBeDisabled()
  })

  /** 무엇이 빠졌는지는 서버 문구로만 말한다. FE가 필요한 서류 목록을 들고 있지 않는다 */
  it('점검에서 빠진 서류가 나오면 서버 문구 그대로 알린다', async () => {
    serve(json(serverList([STATEMENT], issuesCheck)))
    renderAt('/docs')

    expect(await screen.findByText('정산 점검 목록에서 빠진 서류: 이체확인증')).toBeInTheDocument()
  })

  it('시트에서 파일을 고르면 시트를 닫고, 읽는 동안 기다리라고 알리며 더 올리지 못하게 한다', async () => {
    await renderDocs([STATEMENT], hanging)

    pick(new File(['%PDF'], '이체확인증.pdf', { type: 'application/pdf' }))

    await waitFor(() => expect(sheet()).not.toBeInTheDocument())
    expect(screen.getByRole('status')).toHaveTextContent('서류를 읽는 중')
    // 한 장을 읽는 동안 또 올리면 결과가 서로를 덮는다
    expect(uploadButton()).toBeDisabled()
  })

  /** 서버가 20MB 넘는 파일을 거절한다. 수십 초 올린 뒤에 거절당하지 않게 고르는 순간 막는다 */
  it('너무 큰 파일은 올리지 않고 바로 알린다', async () => {
    const { calls } = await renderDocs([STATEMENT])
    const big = new File(['x'], '큰사진.jpg', { type: 'image/jpeg' })
    Object.defineProperty(big, 'size', { value: MAX_UPLOAD_BYTES + 1 })

    pick(big, '앨범에서 고르기')

    expect(screen.getByText('파일이 너무 커요.')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(calls()).toHaveLength(1)
  })

  /** 서버에서 지운 서류는 되돌릴 수 없다. 줄 끝 휴지통을 잘못 눌러도 바로 사라지면 안 된다 */
  it('빼기 전에 한 번 묻고, 그대로 두면 남기고 보내지 않는다', async () => {
    const { calls } = await renderDocs([STATEMENT, RECEIPT])

    fireEvent.click(screen.getByRole('button', { name: '철거공사내역서 빼기' }))
    const ask = screen.getByRole('dialog', { name: '이 서류를 뺄까요?' })
    expect(ask).toHaveTextContent('철거공사내역서 · statement.pdf')

    fireEvent.click(within(ask).getByRole('button', { name: '그대로 두기' }))

    await waitFor(() => expect(screen.queryByRole('dialog', { name: '이 서류를 뺄까요?' })).not.toBeInTheDocument())
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(calls()).toHaveLength(1)
  })
})

/** Mock 은 Preview 에서 화면을 보려고 둔다. 서버를 부르지 않고 예시 서류가 그려지는지만 본다(화면당 하나) */
describe('DocsPage — Mock', () => {
  it('?mock= 이면 서버를 부르지 않고 예시 서류를 그린다', () => {
    const { fetchMock } = serve(json(serverList([])))
    renderAt('/docs?mock=docs')

    expect(screen.getAllByRole('listitem').length).toBeGreaterThan(0)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

/**
 * 확인 시트가 서버로 보낼 값. 서버는 받은 값만 사장님이 확인한 값으로 저장해서(#159),
 * 화면에 안 보이는 칸을 빼고 보내면 그 칸이 점검에서 "값 없음"이 된다.
 */
describe('ConfirmSheet', () => {
  it('서버의 종류 선택 목록과 확인된 값의 필드 이름으로 보여 주고 원래 코드로 보낸다', async () => {
    const document = serverDocument({
      kind_label: '서버 이체서류', needs_confirmation: true,
      fields: [{ name: 'amount', label: '서버 송금액', value: '1원', page: 1 }],
      confirmed_fields: { amount: '2원' },
    })
    const { calls } = serve(json({
      ...serverList([document]), document_kinds: [{ kind: 'TRANSFER', label: '서버 이체서류' }],
    }))
    renderAt('/docs')
    fireEvent.click(await screen.findByRole('button', { name: '서버 이체서류 확인하기' }))
    const ask = screen.getByRole('dialog', { name: '서류 확인하기' })
    expect(within(ask).getAllByRole('option').map((option) => option.textContent)).toEqual(['종류를 골라 주세요', '서버 이체서류'])
    expect(within(ask).getByLabelText('서버 송금액')).toHaveValue('2원')
    fireEvent.click(within(ask).getByRole('button', { name: '맞아요, 확인했어요' }))
    await waitFor(() => expect(calls()).toHaveLength(2))
    expect(JSON.parse(calls()[1].body as string)).toEqual({ kind: 'TRANSFER', confirmed_fields: { amount: '2원' } })
  })

  it('화면에 안 보이는 칸도 원래 값 그대로 같이 보낸다', () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmSheet
        documentKinds={[{ kind: 'TRANSFER', label: '이체확인증' }]}
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
        documentKinds={[{ kind: 'CLOSURE_RECEIPT', label: '폐업신고 접수증' }]}
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
  it('서류가 있으면 점검하러 가고, 통과했으면 제출 파일을 보러 간다', async () => {
    await renderDocs([STATEMENT])
    expect(screen.getByRole('button', { name: '정산 서류 점검하기' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '정산 제출 파일 보기' })).not.toBeInTheDocument()

    cleanup()
    serve(json(serverList([STATEMENT], completeCheck)))
    renderAt('/docs')
    expect(await screen.findByRole('button', { name: '정산 제출 파일 보기' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '정산 서류 점검하기' })).not.toBeInTheDocument()
  })
})
