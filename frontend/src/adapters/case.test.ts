import { describe, expect, it } from 'vitest'

import type { CasesEnvelope, CaseResponse } from '../types/api'
import { EMPTY_DIAGNOSIS } from '../stores/useDiagnosisStore'
import type { DiagnosisAnswers } from '../types/view'
import { toCaseCreateRequest, toCurrentCaseView, toFacts } from './case'

/** `GET /cases` 가 주는 Case 한 건. 필요한 칸만 바꿔 가며 쓴다 */
const SERVER_CASE: CaseResponse = {
  id: 1,
  member_id: 42,
  store_name: null,
  business_type: '카페',
  franchise_status: false,
  employee_count: 2,
  has_business_loan: false,
  has_service_contracts: false,
  lease_status: 'LEASED_PAID',
  restoration_clause: 'UNKNOWN',
  restoration_status: 'UNKNOWN',
  restoration_scope: 'UNKNOWN',
  restoration_scope_detail: null,
  demolition_required: 'UNKNOWN',
  planned_closure_date: '2026-12-31',
  planned_closure_month: null,
  case_status: 'IN_PROGRESS',
  completed_at: null,
  closure_date: null,
  closure_reason: null,
  road_address: null,
  address_detail: null,
  deposit_return_result: null,
}

function factFor(serverCase: CaseResponse, key: string) {
  const found = toFacts(serverCase).find((fact) => fact.key === key)
  if (found === undefined) throw new Error(`${key} 항목이 없습니다`)
  return found
}

/**
 * 서버 값이 화면 문구로 잘못 바뀌면 사장님이 자기 가게 상황을 잘못 읽는다.
 * 화면은 멀쩡해 보이고 값만 틀려서, 눈으로는 잡기 어려운 종류다.
 */
describe('toFacts', () => {
  it('서버 값을 화면 문구로 바꾼다', () => {
    expect(factFor(SERVER_CASE, 'business_type')).toMatchObject({
      label: '업종',
      value: '카페',
      status: 'CONFIRMED',
    })
    expect(factFor(SERVER_CASE, 'lease_status')).toMatchObject({ value: '임차 (월세)' })
    expect(factFor(SERVER_CASE, 'employee_count')).toMatchObject({ value: '2명' })
  })

  /** 서버는 업종을 `CAFE` 같은 코드로 적는다. 모르는 코드는 원문 대신 미확인으로 둔다 */
  it.each([
    ['CAFE', { value: '카페', status: 'CONFIRMED' }],
    ['RESTAURANT', { value: '다른 음식점', status: 'CONFIRMED' }],
    ['BAKERY', { status: 'UNKNOWN' }],
  ])('업종 %s 를 화면 말로 바꾼다', (raw, expected) => {
    const fact = factFor({ ...SERVER_CASE, business_type: raw }, 'business_type')
    expect(fact).toMatchObject(expected)
    if (expected.status === 'UNKNOWN') expect(fact.value).toBeUndefined()
  })

  /**
   * `false`를 빈 값으로 다루면 비프랜차이즈 사장님의 항목이 통째로 미확인이 된다.
   * 타깃이 비프랜차이즈 카페라 대부분이 여기 걸린다.
   */
  it('프랜차이즈가 아니어도 확인된 값으로 본다', () => {
    expect(factFor(SERVER_CASE, 'franchise')).toMatchObject({
      value: '비프랜차이즈',
      status: 'CONFIRMED',
    })
  })

  /** 모르는 것은 모른다고 보여준다. 빈 값으로 숨기면 "확인할 게 없다"로 읽힌다 */
  it('UNKNOWN 은 값 없이 미확인으로 둔다', () => {
    const fact = factFor(SERVER_CASE, 'demolition_required')

    expect(fact.status).toBe('UNKNOWN')
    expect(fact.value).toBeUndefined()
  })

  it('직원 수를 비워둔 경우도 미확인이다', () => {
    const fact = factFor({ ...SERVER_CASE, employee_count: null }, 'employee_count')

    expect(fact.status).toBe('UNKNOWN')
  })

  it('확인된 값은 그대로 문구가 된다', () => {
    const fact = factFor({ ...SERVER_CASE, restoration_scope: 'FULL' }, 'restoration_scope')

    expect(fact).toMatchObject({ value: '전체', status: 'CONFIRMED' })
  })

  /**
   * 서버가 우리가 모르는 값을 보낼 수 있다 — 선택지가 넷으로 늘어나는 경우가 그렇다.
   * 그때 문구를 지어내면 사장님이 틀린 정보를 읽는다. 미확인으로 두는 편이 정직하다.
   */
  it.each([
    ['lease_status', 'SUBLEASE'],
    ['restoration_scope', 'IN_PROGRESS'],
    ['demolition_required', 'MAYBE'],
  ])('%s 에 모르는 값이 오면 지어내지 않고 미확인으로 둔다', (field, value) => {
    const unknownValue = { ...SERVER_CASE, [field]: value } as unknown as CaseResponse
    const fact = factFor(unknownValue, field === 'lease_status' ? 'lease_status' : field)

    expect(fact.status).toBe('UNKNOWN')
    expect(fact.value).toBeUndefined()
  })

  /**
   * 사장님이 직접 적어 넣은 값인데 지금까지 어디에도 보이지 않았다.
   *
   * `Date` 로 바꾸지 않는 것이 중요하다. `new Date('2026-12-31')` 은 UTC 자정이라
   * 한국보다 느린 시간대에서 읽으면 하루 앞 날짜가 된다.
   */
  it('폐업 예정일을 점으로 구분해 보여준다', () => {
    expect(factFor(SERVER_CASE, 'planned_closure_date').value).toBe('2026.12.31')
  })

  /** 진단에서 "이번 달 안에"·"다음 달"을 고르면 날짜 없이 달만 저장된다. 그걸 미확인으로 보이면 답한 게 사라진 줄 안다 */
  it('날짜 없이 예상 달만 있으면 그 달을 보여준다', () => {
    const fact = factFor(
      { ...SERVER_CASE, planned_closure_date: null, planned_closure_month: '2026-11' },
      'planned_closure_date',
    )

    expect(fact.status).toBe('CONFIRMED')
    expect(fact.value).toBe('2026.11 중')
  })

  it.each([
    ['비어 있으면', null],
    ['칸 자체가 안 오면', undefined],
  ])('폐업 예정일이 %s 미확인으로 둔다', (_name, value) => {
    const fact = factFor(
      { ...SERVER_CASE, planned_closure_date: value as string | null },
      'planned_closure_date',
    )

    expect(fact.status).toBe('UNKNOWN')
    expect(fact.value).toBeUndefined()
  })

  /** 진행 단계는 사용자가 답할 수 있는 것이 아니라 할 일 목록에 섞이면 안 된다 */
  it('원상복구 진행 상태는 목록에 넣지 않는다', () => {
    expect(toFacts(SERVER_CASE).map((fact) => fact.key)).not.toContain('restoration_status')
  })
})

/** 봉투에서 판단만 바꿔 끼운다. 가게 칸은 어느 상태에서나 같은 것이 와야 한다 */
function envelopeOf(judgment: Partial<CasesEnvelope>): CasesEnvelope {
  return {
    case: SERVER_CASE,
    blocker: null,
    next_action: null,
    judgment_status: null,
    questions_for_user: null,
    recovery_action_code: null,
    requested_field_paths: null,
    ...judgment,
  }
}

/**
 * 서버가 칸을 통째로 빠뜨린 응답.
 *
 * 타입에는 `string | null` 로 적혀 있지만 실제로 오는 JSON 은 칸 자체가 없을 수 있다.
 * 어댑터가 있는 이유가 그 어긋남이라, 여기서는 타입을 한 번 벗고 날것으로 넣는다.
 */
function rawEnvelope(body: Record<string, unknown>): CasesEnvelope {
  return body as unknown as CasesEnvelope
}

/** 서버가 보내는 다음 할 일 한 건 */
const NEXT_ACTION = {
  title: '임대인에게 원상복구 범위를 확인하세요.',
  reason: '철거가 필요한지 판단하려면 원상복구 범위를 먼저 알아야 합니다.',
  questions_to_ask: ['어디까지 원래대로 돌려놔야 하나요?', '철거까지 해야 하나요?'],
}

/**
 * 폐업 신고·보증금 화면을 채워 열 값(#168). 서버가 폐업일·사유·도로명 주소를 한 번에 저장하므로,
 * 셋 중 하나라도 없으면 저장된 적 없는 조합이라 빈 칸에서 열어야 한다.
 */
describe('toCurrentCaseView 저장해 둔 폐업 신고·보증금', () => {
  const SAVED = {
    ...SERVER_CASE,
    closure_date: '2026-10-31',
    closure_reason: 'PERSONAL',
    road_address: '서울 마포구 망원로 52 (망원동)',
    address_detail: '1층',
    deposit_return_result: 'PARTIAL',
  } satisfies CaseResponse
  const viewOf = (serverCase: CaseResponse) => toCurrentCaseView(envelopeOf({ judgment_status: 'PENDING' }), serverCase)

  it('저장 전이면 둘 다 비운다', () => {
    const view = viewOf(SERVER_CASE)
    expect(view.closureReport).toBeNull()
    expect(view.depositReturn).toBeNull()
  })

  it('저장해 둔 값을 화면 모양으로 옮긴다', () => {
    const view = viewOf(SAVED)
    expect(view.closureReport).toEqual({
      closureDate: '2026-10-31',
      closureReason: 'PERSONAL',
      roadAddress: '서울 마포구 망원로 52 (망원동)',
      addressDetail: '1층',
    })
    expect(view.depositReturn).toBe('PARTIAL')
  })

  it.each(['closure_date', 'closure_reason', 'road_address'] as const)('%s 가 없으면 신고 정보를 비운다', (field) => {
    expect(viewOf({ ...SAVED, [field]: null }).closureReport).toBeNull()
  })

  it('상세 주소는 비어 있어도 신고 정보로 본다', () => {
    expect(viewOf({ ...SAVED, address_detail: null }).closureReport?.addressDetail).toBeNull()
  })

  it('모르는 값이면 고른 것이 없는 것으로 둔다', () => {
    const view = viewOf({ ...SAVED, closure_reason: 'RETIRED', deposit_return_result: 'MAYBE' } as unknown as CaseResponse)
    expect(view.closureReport).toBeNull()
    expect(view.depositReturn).toBeNull()
  })
})

/**
 * 폐업 완료(#167). 서버가 `case_status` 를 `COMPLETED` 로 바꿨을 때만 완료다. 진행 중인 가게에 완료
 * 화면을 띄우면 [결과 알려주기]가 사라져 사장님이 할 일을 놓친다.
 */
describe('toCurrentCaseView 폐업 완료', () => {
  const viewOf = (serverCase: CaseResponse) => toCurrentCaseView(envelopeOf({ judgment_status: 'DONE' }), serverCase)

  it('완료면 완료로 본다', () => {
    expect(viewOf({ ...SERVER_CASE, case_status: 'COMPLETED', completed_at: '2026-11-04T10:00:00' }).completed).toBe(true)
  })

  it('완료 시각이 비어 와도 상태가 완료면 완료로 본다', () => {
    expect(viewOf({ ...SERVER_CASE, case_status: 'COMPLETED', completed_at: null }).completed).toBe(true)
  })

  it('진행 중이면 완료가 아니다', () => {
    expect(viewOf(SERVER_CASE).completed).toBe(false)
  })

  it('모르는 상태면 완료로 보지 않는다', () => {
    expect(viewOf({ ...SERVER_CASE, case_status: 'CLOSED' } as unknown as CaseResponse).completed).toBe(false)
  })
})

describe('toCurrentCaseView', () => {
  it('가게 정보는 판단 상태와 무관하게 담는다', () => {
    const view = toCurrentCaseView(envelopeOf({ judgment_status: 'PENDING' }), SERVER_CASE)

    expect(view.judgment.status).toBe('PENDING')
    expect(view.facts).toHaveLength(7)
  })

  it('판단이 끝났으면 막힌 것과 할 일을 담는다', () => {
    const view = toCurrentCaseView(
      envelopeOf({
        judgment_status: 'DONE',
        blocker: '원상복구 범위가 아직 확인되지 않았습니다.',
        next_action: NEXT_ACTION,
      }),
      SERVER_CASE,
    )

    if (view.judgment.status !== 'DONE') throw new Error('DONE 이어야 한다')
    expect(view.judgment.blocker.title).toBe('원상복구 범위가 아직 확인되지 않았습니다.')
    expect(view.judgment.nextAction).toEqual({
      title: NEXT_ACTION.title,
      reason: NEXT_ACTION.reason,
      questions: NEXT_ACTION.questions_to_ask,
    })
  })

  /**
   * 순번은 응답에 없다. 1 로 지어내면 사장님이 "지금 1번째구나" 하고 전체 진행도를
   * 짐작하게 된다 — 서버가 세어준 적이 없는 숫자다.
   */
  it('서버에 없는 순번을 지어내지 않는다', () => {
    const view = toCurrentCaseView(
      envelopeOf({ judgment_status: 'DONE', blocker: '막힘', next_action: NEXT_ACTION }),
      SERVER_CASE,
    )

    if (view.judgment.status !== 'DONE') throw new Error('DONE 이어야 한다')
    expect(view.judgment.nextAction.seq).toBeUndefined()
  })

  /**
   * 이유와 물어볼 말은 없어도 카드가 성립한다. 카드가 그 자리를 아예 안 그리므로
   * 빈 문단이나 빈 목록이 남지 않는다.
   */
  it.each([
    // 서버가 실제로 보내는 모양이다 — 이유가 없으면 `null`, 물어볼 말이 없으면 빈 목록(#68)
    [
      '이유가 null 이면',
      { title: '할 일', reason: null, questions_to_ask: [] },
      { reason: '', questions: [] },
    ],
    ['이유 칸이 아예 없으면', { title: '할 일', questions_to_ask: [] }, { reason: '', questions: [] }],
    [
      '이유가 글자가 아니면',
      { title: '할 일', reason: 123, questions_to_ask: [] },
      { reason: '', questions: [] },
    ],
    ['물어볼 말 칸이 없으면', { title: '할 일', reason: '왜' }, { reason: '왜', questions: undefined }],
  ])('%s 빈 채로 둔다', (_name, nextAction, expected) => {
    const view = toCurrentCaseView(
      rawEnvelope({ judgment_status: 'DONE', blocker: '막힘', next_action: nextAction, case: SERVER_CASE }),
      SERVER_CASE,
    )

    if (view.judgment.status !== 'DONE') throw new Error('DONE 이어야 한다')
    expect(view.judgment.nextAction.reason).toBe(expected.reason)
    expect(view.judgment.nextAction.questions).toEqual(expected.questions)
  })

  /**
   * 성한 것만 골라 그리면 사장님이 그게 물어볼 말의 전부인 줄 알고, 빠뜨린 채로
   * 임대인을 만난다. 반쯤 보여주는 것이 안 보여주는 것보다 나쁜 경우다.
   */
  it('물어볼 말에 글자가 아닌 것이 섞이면 통째로 버린다', () => {
    const view = toCurrentCaseView(
      rawEnvelope({
        judgment_status: 'DONE',
        blocker: '막힘',
        next_action: { title: '할 일', reason: '왜', questions_to_ask: ['물어볼 말', { q: '객체' }] },
        case: SERVER_CASE,
      }),
      SERVER_CASE,
    )

    if (view.judgment.status !== 'DONE') throw new Error('DONE 이어야 한다')
    expect(view.judgment.nextAction.questions).toBeUndefined()
  })

  it('되물을 것이 있으면 질문을 그대로 담는다', () => {
    const view = toCurrentCaseView(
      envelopeOf({ judgment_status: 'NEEDS_MORE_INFO', questions_for_user: ['철거까지 하시나요?'] }),
      SERVER_CASE,
    )

    expect(view.judgment).toEqual({
      status: 'NEEDS_MORE_INFO',
      questions: ['철거까지 하시나요?'],
    })
  })

  it('기록과 어긋났으면 확인이 필요한 것으로 둔다', () => {
    const view = toCurrentCaseView(envelopeOf({ judgment_status: 'CONFLICT' }), SERVER_CASE)

    expect(view.judgment).toEqual({ status: 'CONFLICT' })
  })

  /** 다음 할 일이 비어 오는 것이 정상인 상태다(#315). `DONE` 처럼 비었다고 읽지 못한 것으로 두면 홈이 "멈췄어요"가 된다 */
  it('등록된 절차를 다 마쳤으면 할 일이 비어 있어도 마친 것으로 둔다', () => {
    const view = toCurrentCaseView(
      envelopeOf({ judgment_status: 'PROCEDURES_COMPLETED', blocker: null, next_action: null, questions_for_user: null }),
      SERVER_CASE,
    )

    expect(view.judgment).toEqual({ status: 'PROCEDURES_COMPLETED' })
    // 폐업 전체 완료와 다르다. 완료는 `case_status` 가 정한다
    expect(view.completed).toBe(false)
  })

  /**
   * 그 할 일은 **어긋나기 전의 판단**이다. 지금 할 일로 그리면 사장님이 이미 틀어진
   * 전제 위에서 움직이고, 그 결과를 또 보고한다. `PENDING`·`FAILED` 에서 이전 판단을
   * 안 그리는 것과 같은 이유다.
   */
  it('확인이 필요한데 할 일이 딸려 와도 그것을 그리지 않는다', () => {
    const view = toCurrentCaseView(
      envelopeOf({
        judgment_status: 'CONFLICT',
        blocker: '원상복구 범위가 아직 확인되지 않았습니다.',
        next_action: NEXT_ACTION,
      }),
      SERVER_CASE,
    )

    expect(view.judgment).toEqual({ status: 'CONFLICT' })
  })

  /**
   * 상태와 내용이 어긋난 응답을 **다른 상태로 바꿔 보여주지 않는다.**
   *
   * `DONE` 인데 할 일이 비어 있는 것을 "정보 부족"으로 그리면, 서버가 틀린 것을 사장님이
   * 덜 적어낸 탓으로 읽는다. 서버가 지금은 이 조합들을 500 으로 막지만 그쪽이 바뀔 수 있다.
   */
  /**
   * 실패는 하나가 아니다. "다시 해볼 수 있다" 와 "정보가 더 있어야 한다" 를 한 화면으로
   * 뭉개면, 사장님이 알려줘야 끝나는 상황에서도 기다리면 되는 줄 알고 가만히 있게 된다.
   */
  describe('판단 실패', () => {
    /** 실패 안내만 꺼낸다. 다른 상태로 나오면 테스트가 잘못 짜인 것이다 */
    function noticeOf(judgment: Partial<CasesEnvelope>) {
      const view = toCurrentCaseView(
        envelopeOf({ judgment_status: 'FAILED', ...judgment }),
        SERVER_CASE,
      )
      if (view.judgment.status !== 'FAILED') throw new Error('FAILED 여야 한다')

      return view.judgment.notice
    }

    /** 다시 알아야 할 칸까지 들어 있는 안내를 꺼낸다 */
    function detailOf(requested_field_paths: unknown) {
      const notice = noticeOf({
        recovery_action_code: 'RESUBMIT_INPUT',
        requested_field_paths: requested_field_paths as string[],
      })
      if (notice.kind !== 'NEEDS_DETAIL') throw new Error('NEEDS_DETAIL 이어야 한다')

      return notice
    }

    it.each([
      ['RETRY', 'RETRY_AVAILABLE'],
      ['RESUBMIT_INPUT', 'NEEDS_DETAIL'],
      ['CONTACT_SUPPORT', 'SERVICE_SIDE'],
      ['NONE', 'NO_RECOVERY'],
    ])('%s 는 %s 안내로 간다', (code, kind) => {
      expect(noticeOf({ recovery_action_code: code as never }).kind).toBe(kind)
    })

    /**
     * `NONE` 으로 떨어뜨리지 않는다. 그건 서버가 "할 수 있는 것이 없다" 고 **말한** 경우고,
     * 여기는 우리가 그 말을 못 알아들은 경우다. 뭉개면 계약이 어긋난 사실이 화면 뒤로 숨는다.
     */
    it.each([
      ['코드가 비어 있으면', null],
      ['우리가 모르는 코드가 오면', 'RETRY_WITH_MORE_INFO'],
    ])('%s 이유를 모르는 것으로 둔다', (_name, code) => {
      expect(noticeOf({ recovery_action_code: code as never }).kind).toBe('UNKNOWN_CAUSE')
    })

    it('다시 알아야 할 칸을 화면 문구로 바꾼다', () => {
      expect(detailOf(['restoration_scope', 'demolition_required'])).toEqual({
        kind: 'NEEDS_DETAIL',
        fields: ['원상복구 범위', '철거 필요 여부'],
        partial: false,
      })
    })

    /**
     * 모르는 이름을 조용히 빼기만 하면 남은 것이 전부인 줄 알게 되고, 영어 칸 이름을 그대로
     * 띄우면 사장님이 읽을 수 없는 글자를 보게 된다. 빼되 **뺐다는 사실을 남긴다.**
     */
    it('모르는 이름이 섞이면 아는 것만 담고 더 있었다고 알린다', () => {
      expect(detailOf(['restoration_scope', 'closure_subsidy'])).toEqual({
        kind: 'NEEDS_DETAIL',
        fields: ['원상복구 범위'],
        partial: true,
      })
    })

    /**
     * 모양이 깨진 항목 하나 때문에 멀쩡한 항목까지 버리지 않는다. 아는 것은 그대로 알리고,
     * 못 읽은 것이 있었다는 사실만 함께 남긴다.
     */
    it('글자가 아닌 것이 섞여도 아는 칸은 그대로 담는다', () => {
      expect(detailOf(['restoration_scope', 1])).toEqual({
        kind: 'NEEDS_DETAIL',
        fields: ['원상복구 범위'],
        partial: true,
      })
    })

    it('같은 칸이 두 번 와도 한 번만 담는다', () => {
      expect(detailOf(['restoration_scope', 'restoration_scope']).fields).toEqual(['원상복구 범위'])
    })

    /**
     * 하나도 못 알아봤으면 "일부" 가 아니라 아예 말할 수 없는 것이다. `partial` 을 켜면
     * 화면이 **없는 목록을 가리키며** "등" 이라고 말하게 된다.
     */
    it.each([
      ['아는 이름이 하나도 없으면', ['closure_subsidy']],
      ['물려받은 이름이 와도', ['toString']],
      ['목록이 비어 있으면', []],
      ['칸이 비어 있으면', null],
      ['목록이 아니면', '원상복구 범위'],
      ['글자가 아닌 것이 들어 있으면', [1, { field: 'restoration_scope' }]],
    ])('%s 항목을 특정하지 않는다', (_name, paths) => {
      expect(detailOf(paths)).toEqual({ kind: 'NEEDS_DETAIL', fields: [], partial: false })
    })
  })

  describe('계약이 어긋난 응답', () => {
    it.each([
      ['DONE 인데 할 일이 없다', { judgment_status: 'DONE' as const, blocker: '막힘' }],
      [
        'DONE 인데 막힌 것이 없다',
        { judgment_status: 'DONE' as const, next_action: NEXT_ACTION },
      ],
      ['되묻는다면서 질문이 없다', { judgment_status: 'NEEDS_MORE_INFO' as const }],
      [
        '되묻는다면서 질문이 빈 목록이다',
        { judgment_status: 'NEEDS_MORE_INFO' as const, questions_for_user: [] },
      ],
      ['판단 상태가 아예 없다', {}],
    ])('%s 면 알 수 없는 것으로 둔다', (_name, judgment) => {
      const view = toCurrentCaseView(envelopeOf(judgment), SERVER_CASE)

      expect(view.judgment.status).toBe('UNRECOGNIZED')
    })

    /**
     * `null` 만 보면 여기서 뚫린다.
     *
     * 할 일 칸이 없는 채로 `DONE` 이 통과하면 **제목 없는 검은 카드**가 뜨고, 그 밑의
     * "결과 알려주기" 는 멀쩡히 눌린다 — 사장님이 빈 할 일의 결과를 보고하러 간다.
     * 질문 칸이 없으면 `.length` 에서 터지는데, 그 오류는 조회 실패로 읽혀
     * HTTP 는 200 인데 "불러오지 못했어요" 가 뜬다.
     */
    it.each([
      ['할 일 칸이 아예 없다', { judgment_status: 'DONE', blocker: '막힘' }],
      ['할 일이 빈 문자열이다', { judgment_status: 'DONE', blocker: '막힘', next_action: '' }],
      ['막힌 것 칸이 아예 없다', { judgment_status: 'DONE', next_action: '할 일' }],
      ['질문 칸이 아예 없다', { judgment_status: 'NEEDS_MORE_INFO' }],
    ])('%s 면 알 수 없는 것으로 둔다', (_name, body) => {
      const view = toCurrentCaseView(rawEnvelope({ ...body, case: SERVER_CASE }), SERVER_CASE)

      expect(view.judgment.status).toBe('UNRECOGNIZED')
    })

    /**
     * **지금 실제로 벌어지는 중인 일이다.**
     *
     * `next_action` 이 글자에서 묶음으로 바뀌고 있다(#58). BE 가 먼저 배포되면 묶음이
     * 그대로 들어오는데, 막지 않으면 React 가 객체를 글자 자리에 받아 `/case` 가 통째로
     * 죽는다 — 사장님은 흰 화면을 본다. 못 그리는 것과 죽는 것은 다르다.
     */
    it.each([
      ['할 일이 아직 글자로 온다', { next_action: '임대인에게 확인하세요.', blocker: '막힘' }],
      ['할 일에 제목이 없다', { next_action: { reason: '왜' }, blocker: '막힘' }],
      ['할 일의 제목이 글자가 아니다', { next_action: { title: 1 }, blocker: '막힘' }],
      ['막힌 것이 묶음으로 바뀌어 온다', { next_action: NEXT_ACTION, blocker: { description: '막힘' } }],
      ['할 일이 숫자다', { next_action: 1, blocker: '막힘' }],
    ])('%s 면 알 수 없는 것으로 둔다', (_name, body) => {
      const view = toCurrentCaseView(
        rawEnvelope({ judgment_status: 'DONE', ...body, case: SERVER_CASE }),
        SERVER_CASE,
      )

      expect(view.judgment.status).toBe('UNRECOGNIZED')
    })

    /**
     * 질문은 목록이라 두 겹으로 틀어질 수 있다 — 목록이 아니거나, 목록인데 안에 든 것이
     * 글자가 아니거나. 둘 다 카드가 목록을 펼치는 자리에서 앱을 내린다.
     *
     * 문자열은 `.length` 도 있고 비어 있지도 않아서 **예전 검사를 그냥 통과했다.**
     */
    it.each([
      ['목록이 아니라 글자 하나다', '철거까지 하시나요?'],
      ['목록 안에 객체가 들어 있다', [{ question: '철거까지 하시나요?' }]],
      ['목록 안에 빈 글자가 섞여 있다', ['철거까지 하시나요?', '']],
    ])('질문이 %s 면 알 수 없는 것으로 둔다', (_name, questions) => {
      const view = toCurrentCaseView(
        rawEnvelope({
          judgment_status: 'NEEDS_MORE_INFO',
          questions_for_user: questions,
          case: SERVER_CASE,
        }),
        SERVER_CASE,
      )

      expect(view.judgment.status).toBe('UNRECOGNIZED')
    })

    /**
     * `CONFLICT` 가 늘어난 것처럼(#66) 또 늘어날 수 있다. AI 는 이미 `SAFE_FAILURE` 를
     * 따로 내고 있고 BE 가 그것을 `FAILED` 로 접어 보내는 중이라, 접는 것을 그만두면
     * 이 값이 그대로 온다.
     */
    it('우리가 모르는 판단 상태도 알 수 없는 것으로 둔다', () => {
      const view = toCurrentCaseView(
        envelopeOf({ judgment_status: 'SAFE_FAILURE' as never }),
        SERVER_CASE,
      )

      expect(view.judgment.status).toBe('UNRECOGNIZED')
    })
  })
})

/** 꼭 답해야 넘어가는 질문은 미리 채워 둔다. 각 테스트는 보려는 답만 바꾼다 */
const diagnosis = (patch: Partial<DiagnosisAnswers>): DiagnosisAnswers => ({
  ...EMPTY_DIAGNOSIS,
  business: 'PERSONAL_CAFE',
  situations: [],
  restorationClause: 'UNKNOWN',
  hadEmployees: false,
  insurances: [],
  closure: 'UNDECIDED',
  ...patch,
})

/** 한국 시간 2026-11-03 12:00. 예상 달을 보는 테스트만 시각을 따로 준다 */
const NOW = new Date('2026-11-03T03:00:00Z')
const request = (answers: DiagnosisAnswers, now = NOW) => toCaseCreateRequest(answers, now)

/**
 * 시안의 답은 서버 칸과 1:1이 아니다. 여기서 잘못 옮기면 서버가 422로 막거나,
 * 더 나쁘게는 고르지 않은 사실(프랜차이즈·월세·직원)이 그대로 저장되어 다른 할 일이 나온다.
 */
describe('toCaseCreateRequest', () => {
  /** 글자("개인 카페")를 보내면 로드맵이 전부 해당 없음이 된다(#119 현종님 실측) */
  it('업종 보기를 업종 코드와 프랜차이즈 여부로 바꾼다', () => {
    expect(request(diagnosis({ business: 'PERSONAL_CAFE' }))).toMatchObject({
      business_type: 'CAFE',
      franchise_status: false,
    })
    expect(request(diagnosis({ business: 'FRANCHISE_CAFE' }))).toMatchObject({
      business_type: 'CAFE',
      franchise_status: true,
    })
    expect(request(diagnosis({ business: 'RESTAURANT', franchise: true }))).toMatchObject({
      business_type: 'RESTAURANT',
      franchise_status: true,
    })
  })

  /** 서버가 프랜차이즈 여부를 확정값으로만 받는다. 모르는 채로 보내면 판단이 시작되지 않는다 */
  it('다른 음식점인데 프랜차이즈 여부를 모르면 보내지 않는다', () => {
    expect(request(diagnosis({ business: 'RESTAURANT' }))).toBeNull()
  })

  it('빌린 가게면 월세 답으로, 안 골랐으면 자가로 보낸다', () => {
    expect(request(diagnosis({ situations: ['LEASE'], paysRent: true }))?.lease_status).toBe(
      'LEASED_PAID',
    )
    expect(request(diagnosis({ situations: ['LEASE'], paysRent: false }))?.lease_status).toBe(
      'LEASED_FREE',
    )
    expect(request(diagnosis({ situations: [] }))?.lease_status).toBe('OWNED')
    expect(request(diagnosis({ situations: ['LEASE'] }))).toBeNull()
  })

  /** 빌린 가게를 해제하면 월세 질문이 빠진다. 남아 있던 월세 답으로 "빌린 가게"가 되면 안 된다 */
  it('앞 답을 바꿔 빠진 질문의 답은 보내지 않는다', () => {
    expect(request(diagnosis({ situations: [], paysRent: true }))?.lease_status).toBe('OWNED')
    expect(
      request(diagnosis({ situations: [], fullTimeCount: 3, partTimeCount: 1 }))?.employee_count,
    ).toBe(0)
  })

  it('직원을 골랐으면 정직원과 아르바이트를 더해 보낸다', () => {
    expect(
      request(diagnosis({ situations: ['STAFF'], fullTimeCount: 2, partTimeCount: 1 }))
        ?.employee_count,
    ).toBe(3)
  })

  /** 서버는 0~1000명만 받는다. 직원이 있다고 했는데 0명이면 앞 답과 어긋난다 */
  it('직원을 골랐는데 0명이거나 상한을 넘으면 보내지 않는다', () => {
    expect(request(diagnosis({ situations: ['STAFF'] }))).toBeNull()
    expect(request(diagnosis({ situations: ['STAFF'], fullTimeCount: 1001 }))).toBeNull()
  })

  /** 고르지 않은 것은 "모름"이 아니라 "없음"이다. 비워 보내면 서버는 "안 물어봄"으로 저장한다 */
  it('대출·배달앱은 골랐는지로 보낸다', () => {
    expect(request(diagnosis({ situations: ['LOAN', 'CONTRACT'] }))).toMatchObject({
      has_business_loan: true,
      has_service_contracts: true,
    })
    expect(request(diagnosis({ situations: [] }))).toMatchObject({
      has_business_loan: false,
      has_service_contracts: false,
    })
  })

  /** 서버가 이 칸에 `null`을 받지 않는다(422). 자가면 원상복구 할 일이 빠져 값이 쓰이지 않는다 */
  it('원상복구 조항은 빌린 가게면 고른 답, 자가면 모름으로 보낸다', () => {
    expect(
      request(diagnosis({ situations: ['LEASE'], paysRent: true, restorationClause: 'EXISTS' }))
        ?.restoration_clause,
    ).toBe('EXISTS')
    expect(
      request(diagnosis({ situations: [], restorationClause: 'NOT_EXISTS' }))?.restoration_clause,
    ).toBe('UNKNOWN')
    expect(
      request(diagnosis({ situations: ['LEASE'], paysRent: true, restorationClause: null })),
    ).toBeNull()
  })

  /**
   * 지금 직원이 있는데 "둔 적 없음"이 가면 서버가 두 값이 어긋났다고 보고 다시 묻는다.
   * 지금 있으면 비워 두고 서버가 직원 수로 알게 한다
   */
  it('예전 직원 답은 지금 직원이 없을 때만 보낸다', () => {
    expect(request(diagnosis({ hadEmployees: true }))?.had_employees).toBe(true)
    expect(
      request(diagnosis({ situations: ['STAFF'], fullTimeCount: 1, hadEmployees: false }))
        ?.had_employees,
    ).toBeNull()
    expect(request(diagnosis({ hadEmployees: null }))).toBeNull()
  })

  /** 하나라도 비면 서버가 넷을 다 "모름"으로 본다. "가입한 적 없어요"가 "해당 없음"이 되려면 넷 다 false여야 한다 */
  it('보험 네 칸을 늘 같이 채워 보낸다', () => {
    expect(request(diagnosis({ insurances: ['PENSION', 'EMPLOYMENT'] }))).toMatchObject({
      pension_enrolled: true,
      health_insurance_enrolled: false,
      employment_insurance_enrolled: true,
      industrial_accident_insurance_enrolled: false,
    })
    expect(request(diagnosis({ insurances: [] }))).toMatchObject({
      pension_enrolled: false,
      health_insurance_enrolled: false,
      employment_insurance_enrolled: false,
      industrial_accident_insurance_enrolled: false,
    })
    expect(request(diagnosis({ insurances: null }))).toBeNull()
  })

  /**
   * 예상 달을 보내야 로드맵의 "날짜 정하기"가 진행 중이 된다(#153). 날짜는 지어내지 않는다 —
   * "이번 달"을 1일·말일로 바꾸면 서버가 그 날짜로 기한을 계산하고(FE 규칙 7), 둘을 같이 보내면 422다
   */
  it('폐업 시기는 예상 달로 보내고 날짜는 비운다', () => {
    expect(request(diagnosis({ closure: 'THIS_MONTH' }))).toMatchObject({
      planned_closure_month: '2026-11',
      planned_closure_date: null,
    })
    expect(request(diagnosis({ closure: 'NEXT_MONTH' }))?.planned_closure_month).toBe('2026-12')
    expect(request(diagnosis({ closure: 'UNDECIDED' }))?.planned_closure_month).toBeNull()
  })

  it('12월의 다음 달은 다음 해 1월이다', () => {
    const december = new Date('2026-12-15T03:00:00Z')
    expect(request(diagnosis({ closure: 'NEXT_MONTH' }), december)?.planned_closure_month).toBe('2027-01')
  })

  /** 한국 12월 1일 새벽은 UTC로 아직 11월 30일이다. 사장님이 보는 달력은 한국 시간이다 */
  it('이번 달은 한국 시간으로 센다', () => {
    const koreaDecemberFirst = new Date('2026-11-30T15:30:00Z')
    expect(request(diagnosis({ closure: 'THIS_MONTH' }), koreaDecemberFirst)?.planned_closure_month).toBe(
      '2026-12',
    )
  })

  it('업종이나 해당 항목, 폐업 시기에 답하지 않았으면 보내지 않는다', () => {
    expect(request(diagnosis({ business: null }))).toBeNull()
    expect(request(diagnosis({ situations: null }))).toBeNull()
    expect(request(diagnosis({ closure: null }))).toBeNull()
  })
})
