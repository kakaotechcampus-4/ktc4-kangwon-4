import { describe, expect, it } from 'vitest'

import { toDocumentsView } from './documents'

const serverDocument = (overrides: Record<string, unknown> = {}) => ({
  document_id: '0b9f…-1',
  filename: 'transfer.pdf',
  kind: 'TRANSFER',
  kind_label: '이체확인증',
  needs_confirmation: false,
  fields: [{ name: 'amount', value: '3,300,000원', page: 1 }],
  confirmed_fields: null,
  ...overrides,
})

/**
 * 서류함은 정산에 낼 서류를 모으는 곳이다. 여기서 틀리면 올린 서류가 사라진 것처럼 보이거나,
 * 사장님이 확인한 값 대신 처음 읽은 값이 다시 뜬다.
 */
describe('toDocumentsView', () => {
  it('서버가 정한 종류 이름과 확인 필요 여부를 그대로 옮긴다', () => {
    expect(toDocumentsView({ documents: [serverDocument()], check: null })).toEqual({
      documents: [
        {
          id: '0b9f…-1',
          filename: 'transfer.pdf',
          kind: 'TRANSFER',
          kindLabel: '이체확인증',
          needsConfirmation: false,
          fields: [{ name: 'amount', label: '금액', value: '3,300,000원' }],
        },
      ],
      check: null,
    })
  })

  /** 사장님이 고친 값이 맞는 값이다. 처음 읽은 값을 다시 보여주면 고친 것이 사라진 줄 안다 */
  it('사장님이 확인한 값이 있으면 그것을 쓴다', () => {
    const view = toDocumentsView({
      documents: [serverDocument({ confirmed_fields: { amount: '3,000,000원', sender: '김리본' } })],
      check: null,
    })

    expect(view?.documents[0].fields).toEqual([
      { name: 'amount', label: '금액', value: '3,000,000원' },
      { name: 'sender', label: '보낸 사람', value: '김리본' },
    ])
  })

  /** 서버가 값 이름을 주기로 했다(#159). 주면 그것을, 우리가 모르는 칸이면 영어로 띄우지 않는다 */
  it('서버가 준 값 이름을 먼저 쓰고, 모르는 칸은 보여주지 않는다', () => {
    const view = toDocumentsView({
      documents: [
        serverDocument({
          fields: [
            { name: 'amount', label: '이체 금액', value: '1원', page: 1 },
            { name: 'bank_code', value: '088', page: 1 },
          ],
        }),
      ],
      check: null,
    })

    expect(view?.documents[0].fields).toEqual([{ name: 'amount', label: '이체 금액', value: '1원' }])
  })

  /** 깨진 한 장만 빼면 사장님은 그 서류를 다시 올리고, 점검의 "빠진 서류"와도 어긋난다 */
  it('한 장이라도 모양이 깨지면 통째로 읽지 못한 것으로 둔다', () => {
    expect(toDocumentsView({ documents: [serverDocument(), serverDocument({ kind_label: '' })], check: null })).toBeNull()
    expect(toDocumentsView({ documents: 'none' })).toBeNull()
    expect(toDocumentsView(null)).toBeNull()
  })

  it('점검 결과의 단계와 서버 문구를 옮긴다', () => {
    const view = toDocumentsView({
      documents: [],
      check: {
        status: 'ISSUES',
        steps: [{ name: '빠진 서류 찾기', status: 'NEEDS_CONFIRMATION' }],
        issues: [{ code: 'MISSING_TRANSFER', document_ids: [], message: '정산 점검 목록에서 빠진 서류: 이체확인증' }],
        checked_at: '2026-11-03T21:00:00+09:00',
      },
    })

    expect(view?.check).toEqual({
      status: 'ISSUES',
      steps: [{ name: '빠진 서류 찾기', status: 'NEEDS_CONFIRMATION' }],
      issues: ['정산 점검 목록에서 빠진 서류: 이체확인증'],
    })
  })

  /** 모르는 점검 상태를 "완료"나 "없음"으로 읽으면 제출 파일 버튼이 잘못 열린다 */
  it('모르는 점검 상태면 읽지 못한 것으로 둔다', () => {
    expect(toDocumentsView({ documents: [], check: { status: 'OK', steps: [], issues: [] } })).toBeNull()
  })
})
