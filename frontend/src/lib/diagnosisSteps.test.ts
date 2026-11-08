import { describe, expect, it } from 'vitest'

import { EMPTY_DIAGNOSIS } from '../stores/useDiagnosisStore'
import type { DiagnosisAnswers } from '../types/view'
import { diagnosisSteps, reachableStep } from './diagnosisSteps'

const answers = (patch: Partial<DiagnosisAnswers>): DiagnosisAnswers => ({ ...EMPTY_DIAGNOSIS, ...patch })

/** 앞 질문을 다 답한 상태. 주소 테스트에서 "여기까지 왔다"를 만든다 */
const ANSWERED_CAFE = answers({
  business: 'PERSONAL_CAFE',
  situations: [],
  hadEmployees: false,
  insurances: [],
  closure: 'UNDECIDED',
})

/**
 * 질문이 빠지면 서버에 꼭 필요한 값(프랜차이즈 여부, 월세 여부)을 못 받고,
 * 묻지 말아야 할 질문이 나오면 서로 어긋난 답("직원 있음" + "둔 적 없음")이 간다.
 */
describe('diagnosisSteps', () => {
  it('해당하는 게 없는 개인 카페는 기본 질문만 묻는다', () => {
    expect(diagnosisSteps(answers({ business: 'PERSONAL_CAFE', situations: [] }))).toEqual([
      'biz',
      'situ',
      'hadStaff',
      'insurance',
      'date',
    ])
  })

  /** 카페는 첫 질문 보기에 이미 개인·프랜차이즈가 나뉘어 있다 */
  it('다른 음식점이면 업종 바로 뒤에 프랜차이즈 여부를 묻는다', () => {
    expect(diagnosisSteps(answers({ business: 'RESTAURANT' })).slice(0, 3)).toEqual(['biz', 'franchise', 'situ'])
  })

  it('빌린 가게면 해당 항목 뒤에 월세와 원상복구 조항을 묻는다', () => {
    expect(diagnosisSteps(answers({ situations: ['LEASE'] })).slice(1, 4)).toEqual(['situ', 'rent', 'restore'])
  })

  it('직원이 있으면 직원 수를 묻고, 예전 직원은 묻지 않는다', () => {
    const steps = diagnosisSteps(answers({ situations: ['STAFF'] }))

    expect(steps).toContain('staff')
    expect(steps).not.toContain('hadStaff')
  })
})

/**
 * 주소는 사장님이 직접 열 수 있다. 앞 답 없이 뒤 질문이 열리면 빈 답을 보내게 된다.
 */
describe('reachableStep', () => {
  it('앞 질문에 답하지 않았으면 그 질문으로 돌려보낸다', () => {
    expect(reachableStep('date', EMPTY_DIAGNOSIS)).toBe('biz')
  })

  it('지금 묻지 않는 질문을 열면 답하지 않은 첫 질문으로 보낸다', () => {
    expect(reachableStep('rent', answers({ business: 'PERSONAL_CAFE', situations: [] }))).toBe('hadStaff')
  })

  it('앞 질문을 다 답했으면 연 질문을 그대로 보여준다', () => {
    expect(reachableStep('insurance', ANSWERED_CAFE)).toBe('insurance')
  })

  it('주소에 질문이 없고 다 답했으면 마지막 질문을 보여준다', () => {
    expect(reachableStep(null, ANSWERED_CAFE)).toBe('date')
  })

  /** 직원이 있다고 했는데 0명이면 직원 수에 답하지 않은 것이다 */
  it('직원이 있다고 골랐으면 1명 이상이어야 다음 질문으로 갈 수 있다', () => {
    const staffed = answers({ business: 'PERSONAL_CAFE', situations: ['STAFF'] })

    expect(reachableStep('insurance', staffed)).toBe('staff')
    expect(reachableStep('insurance', { ...staffed, partTimeCount: 1 })).toBe('insurance')
  })
})
