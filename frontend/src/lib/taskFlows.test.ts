import { describe, expect, it } from 'vitest'

import { taskFlowOf } from './taskFlows'

/**
 * 할 일마다 여는 장면. 여기서 틀리면 사진을 올려야 하는 할 일이 체크만 하고 끝나거나,
 * 판단이 정해야 할 공식 절차를 사장님이 체크로 "완료"해 버린다.
 */
describe('taskFlowOf', () => {
  it('서류가 필요한 할 일은 첨부, 철거비 심사는 고르기로 연다', () => {
    expect(taskFlowOf({ id: 'before_photo', kind: 'CHECKLIST' })).toBe('ATTACH')
    expect(taskFlowOf({ id: 'closure_certificate', kind: 'CHECKLIST' })).toBe('ATTACH')
    expect(taskFlowOf({ id: 'support_approval', kind: 'CASE_FACT' })).toBe('SUPPORT_RESULT')
  })

  /** 공식 절차는 끝났는지를 판단이 정한다. 체크로 열면 사장님이 대신 완료하게 된다 */
  it('공식 절차는 체크가 아니라 결과 알려주기로 연다', () => {
    expect(taskFlowOf({ id: 'restoration', kind: 'PROCEDURE' })).toBe('REPORT_RESULT')
    expect(taskFlowOf({ id: 'employee_payments', kind: 'PROCEDURE' })).toBe('REPORT_RESULT')
  })

  /** 서버가 할 일을 늘려도 화면이 막히지 않게 종류로 고른다 */
  it('표에 없는 할 일은 종류로 고른다', () => {
    expect(taskFlowOf({ id: 'new_checklist', kind: 'CHECKLIST' })).toBe('CHECK')
    expect(taskFlowOf({ id: 'document_check', kind: 'DOCUMENT_CHECK' })).toBe('DOCUMENT_CHECK')
    expect(taskFlowOf({ id: 'closure_date', kind: 'CASE_FACT' })).toBe('INFO')
  })
})
