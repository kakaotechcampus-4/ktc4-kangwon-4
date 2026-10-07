import { describe, expect, it } from 'vitest'

import type { CasesEnvelope, CaseResponse } from '../types/api'
import type { CaseDraft } from '../types/view'
import { toCaseCreateRequest, toCurrentCaseView, toFacts } from './case'

/** `GET /cases` 가 주는 Case 한 건. 필요한 칸만 바꿔 가며 쓴다 */
const SERVER_CASE: CaseResponse = {
  id: 1,
  member_id: 42,
  business_type: '카페',
  franchise_status: false,
  employee_count: 2,
  lease_status: 'LEASED_PAID',
  restoration_status: 'UNKNOWN',
  restoration_scope: 'UNKNOWN',
  restoration_scope_detail: null,
  demolition_required: 'UNKNOWN',
  planned_closure_date: '2026-12-31',
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

  /**
   * 상태와 내용이 어긋난 응답을 **다른 상태로 바꿔 보여주지 않는다.**
   *
   * `DONE` 인데 할 일이 비어 있는 것을 "정보 부족"으로 그리면, 서버가 틀린 것을 사장님이
   * 덜 적어낸 탓으로 읽는다. 서버가 지금은 이 조합들을 500 으로 막지만 그쪽이 바뀔 수 있다.
   */
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

    /** BE 가 `CONFLICT` 추가를 건의해 둔 상태다. 그쪽이 먼저 배포되면 바로 겪는다 */
    it('우리가 모르는 판단 상태도 알 수 없는 것으로 둔다', () => {
      const view = toCurrentCaseView(
        envelopeOf({ judgment_status: 'CONFLICT' as never }),
        SERVER_CASE,
      )

      expect(view.judgment.status).toBe('UNRECOGNIZED')
    })
  })
})

const FILLED_DRAFT: CaseDraft = {
  businessType: '카페',
  franchiseStatus: false,
  leaseStatus: 'LEASED_PAID',
  employeeCount: '',
  plannedClosureDate: '',
}

/**
 * 폼이 들고 있는 값과 서버가 받는 모양이 다르다. 여기서 잘못 바꾸면 서버가 422로 막거나,
 * 더 나쁘게는 "모른다"가 "없다"로 저장된다.
 */
describe('toCaseCreateRequest', () => {
  it('폼 값을 서버 필드 이름으로 바꾼다', () => {
    expect(toCaseCreateRequest({ ...FILLED_DRAFT, employeeCount: '2' })).toMatchObject({
      business_type: '카페',
      franchise_status: false,
      lease_status: 'LEASED_PAID',
      employee_count: 2,
    })
  })

  /** 빈 문자열을 그대로 보내면 서버에서 "모른다"와 "없다"가 같아진다 */
  it('비워둔 선택 항목은 null 로 보낸다', () => {
    expect(toCaseCreateRequest(FILLED_DRAFT)).toMatchObject({
      employee_count: null,
      planned_closure_date: null,
    })
  })

  it('업종 앞뒤 공백은 떼고 보낸다', () => {
    expect(toCaseCreateRequest({ ...FILLED_DRAFT, businessType: '  카페  ' })).toMatchObject({
      business_type: '카페',
    })
  })

  /**
   * `Number()` 가 `NaN` 을 내면 JSON 으로 바뀌며 `null` 이 된다. 잘못 적은 값이 조용히
   * "모른다"로 저장되는데, 사장님은 자기가 적은 숫자가 사라진 것을 모른다.
   */
  it('직원 수가 숫자가 아니면 보내지 않는다', () => {
    expect(toCaseCreateRequest({ ...FILLED_DRAFT, employeeCount: '두 명' })).toBeNull()
    expect(toCaseCreateRequest({ ...FILLED_DRAFT, employeeCount: '1.5' })).toBeNull()
    expect(toCaseCreateRequest({ ...FILLED_DRAFT, employeeCount: '-3' })).toBeNull()
  })

  /** 폼이 이미 막고 있지만, 보내는 쪽에서 한 번 더 걸러야 잘못된 요청이 서버까지 안 간다 */
  it('필수 항목이 비어 있으면 보내지 않는다', () => {
    expect(toCaseCreateRequest({ ...FILLED_DRAFT, businessType: '   ' })).toBeNull()
    expect(toCaseCreateRequest({ ...FILLED_DRAFT, franchiseStatus: null })).toBeNull()
    expect(toCaseCreateRequest({ ...FILLED_DRAFT, leaseStatus: null })).toBeNull()
  })
})
