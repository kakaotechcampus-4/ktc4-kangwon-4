import { describe, expect, it } from 'vitest'

import { DOCUMENT_KINDS, toDocumentsView } from './documents'

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
  it('가게 이름은 서류에서 추측하지 않고 서버가 저장한 값만 옮긴다', () => {
    expect(toDocumentsView({ store_name: '확인한 가게', documents: [serverDocument()], check: null })?.storeName).toBe('확인한 가게')
  })

  it('예전 서버가 가게 이름 키를 보내지 않아도 서류는 보여 주고 추출한 상호로 대신하지 않는다', () => {
    const view = toDocumentsView({
      documents: [serverDocument({ fields: [{ name: 'business_name', value: '서류에서 읽은 상호', page: 1 }] })],
      check: null,
    })
    expect(view?.documents).toHaveLength(1)
    expect(view?.documents[0].fields).toEqual([{ name: 'business_name', label: '상호', value: '서류에서 읽은 상호' }])
    expect(view?.storeName).toBeNull()
  })

  it.each([123, true, false, {}, [], undefined])('가게 이름 키의 잘못된 값은 누락과 구분해 거절한다: %j', (storeName) => {
    expect(toDocumentsView({ store_name: storeName, documents: [serverDocument()], check: null })).toBeNull()
  })

  it('서버가 정한 종류 이름과 확인 필요 여부를 그대로 옮긴다', () => {
    expect(toDocumentsView({ store_name: null, documents: [serverDocument()], check: null })).toEqual({
      storeName: null,
      documentKinds: DOCUMENT_KINDS,
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

  it('새 서버의 종류 목록과 필드 이름을 확인된 값에도 유지한다', () => {
    const kinds = [{ kind: 'TRANSFER', label: '서버 이체서류' }]
    const view = toDocumentsView({
      document_kinds: kinds,
      documents: [serverDocument({
        fields: [{ name: 'amount', label: '서버 송금액', value: '1원', page: 1 }],
        confirmed_fields: { amount: '2원' },
      })], check: null,
    })
    expect(view?.documentKinds).toEqual(kinds)
    expect(view?.documents[0].fields).toEqual([{ name: 'amount', label: '서버 송금액', value: '2원' }])
    expect(toDocumentsView({ document_kinds: [], documents: [], check: null })?.documentKinds).toEqual([])
  })

  it.each([null, undefined, 1, true, {}, [], '', ' '])('명시된 잘못된 label은 예전 사전으로 덮지 않는다: %j', (label) => {
    expect(toDocumentsView({ documents: [serverDocument({ fields: [{ name: 'amount', label, value: '1원' }] })] })).toBeNull()
  })

  it.each([null, undefined, 1, {}, 'none', [null], [{ kind: 'TRANSFER', label: '' }],
    [{ kind: 1, label: '이체서류' }], [{ kind: 'TRANSFER', label: undefined }],
    [{ kind: 'TRANSFER', label: '첫째' }, { kind: 'TRANSFER', label: '둘째' }],
  ])('명시된 잘못된 종류 목록은 예전 사전으로 덮지 않는다: %j', (documentKinds) => {
    expect(toDocumentsView({ document_kinds: documentKinds, documents: [], check: null })).toBeNull()
  })

  /** 사장님이 고친 값이 맞는 값이다. 처음 읽은 값을 다시 보여주면 고친 것이 사라진 줄 안다 */
  it('사장님이 확인한 값이 있으면 그것을 쓴다', () => {
    const view = toDocumentsView({
      store_name: null,
      documents: [serverDocument({ confirmed_fields: { amount: '3,000,000원', sender: '김리본' } })],
      check: null,
    })

    expect(view?.documents[0].fields).toEqual([
      { name: 'amount', label: '금액', value: '3,000,000원' },
      { name: 'sender', label: '보낸 사람', value: '김리본' },
    ])
  })

  /**
   * 서버가 값 이름을 주기로 했다(#159). 주면 그것을 쓴다. 모르는 칸은 이름을 비워 화면에서 숨기되
   * 버리지 않는다 — 확인할 때 그 값을 빼고 보내면 서버가 "값 없음"으로 저장한다
   */
  it('서버가 준 값 이름을 먼저 쓰고, 모르는 칸은 이름 없이 남긴다', () => {
    const view = toDocumentsView({
      store_name: null,
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

    expect(view?.documents[0].fields).toEqual([
      { name: 'amount', label: '이체 금액', value: '1원' },
      { name: 'bank_code', label: null, value: '088' },
    ])
  })

  /** 깨진 한 장만 빼면 사장님은 그 서류를 다시 올리고, 점검의 "빠진 서류"와도 어긋난다 */
  it('한 장이라도 모양이 깨지면 통째로 읽지 못한 것으로 둔다', () => {
    expect(toDocumentsView({ store_name: null, documents: [serverDocument(), serverDocument({ kind_label: '' })], check: null })).toBeNull()
    expect(toDocumentsView({ store_name: null, documents: 'none' })).toBeNull()
    expect(toDocumentsView(null)).toBeNull()
  })

  it('점검 결과의 단계와 서버 문구를 옮긴다', () => {
    const view = toDocumentsView({
      store_name: null,
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
    expect(toDocumentsView({ store_name: null, documents: [], check: { status: 'OK', steps: [], issues: [] } })).toBeNull()
  })
})
