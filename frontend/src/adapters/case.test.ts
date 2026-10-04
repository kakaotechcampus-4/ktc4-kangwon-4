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

describe('toCurrentCaseView', () => {
  it('가게 정보는 판단 상태와 무관하게 담는다', () => {
    const view = toCurrentCaseView(envelopeOf({ judgment_status: 'PENDING' }), SERVER_CASE)

    expect(view.judgment.status).toBe('PENDING')
    expect(view.facts).toHaveLength(7)
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
