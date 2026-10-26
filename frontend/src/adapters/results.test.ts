import { describe, expect, it } from 'vitest'

import type { CaseResultsEntryResponse, CaseResultsSubmitResponse } from '../types/api'
import { toChanges, toConflicts, toResultsEntry, toSubmitOutcome, toValueLabel } from './results'

/**
 * 서버가 값을 파이썬 표기 그대로 보낸다(`"True"`, `"FULL"`). 여기가 틀리면 사장님 화면에
 * 영어가 뜨거나, 프랜차이즈 여부처럼 뒤집히면 안 되는 값이 뒤집힌다.
 */
describe('toValueLabel', () => {
  it.each([
    ['franchise_status', 'True', '프랜차이즈'],
    ['franchise_status', 'False', '비프랜차이즈'],
    ['lease_status', 'LEASED_FREE', '임차 (무상)'],
    ['employee_count', '3', '3명'],
    ['employee_count', '0', '0명'],
    ['planned_closure_date', '2026-10-04', '2026.10.04'],
    ['restoration_status', 'IN_PROGRESS', '진행 중'],
    ['restoration_scope', 'FULL', '전체'],
    ['demolition_required', 'REQUIRED', '필요함'],
    ['business_type', '카페', '카페'],
    ['restoration_scope_detail', '간판과 바닥만', '간판과 바닥만'],
  ])('%s 의 %s 를 %s 로 바꾼다', (field, raw, label) => {
    expect(toValueLabel(field, raw)).toBe(label)
  })

  /**
   * 충돌 항목은 빈칸을 못 받는 자리라 BE 가 자유 글 칸에도 `"UNKNOWN"` 을 적는다.
   * 업종 칸에 "UNKNOWN" 이 그대로 뜨면 사장님은 그게 자기 업종으로 기록된 줄 안다.
   */
  it.each([
    ['demolition_required', 'UNKNOWN'],
    ['business_type', 'UNKNOWN'],
    ['employee_count', null],
    ['planned_closure_date', ''],
  ])('%s 의 %s 는 미확인이다', (field, raw) => {
    expect(toValueLabel(field, raw)).toBeNull()
  })

  /** 모르는 값을 원문 그대로 내보내지도, 미확인으로 숨기지도 않는다 */
  it.each([
    ['franchise_status', 'true'],
    ['lease_status', 'RENTED'],
    ['employee_count', '세 명'],
    ['planned_closure_date', '10월 4일'],
    ['restoration_scope', 'PARTIAL_DONE'],
    ['restoration_scope', 'toString'],
    ['demolition_required', 3],
    ['unknown_field', '카페'],
  ])('%s 의 %s 는 확인 필요로 둔다', (field, raw) => {
    expect(toValueLabel(field, raw)).toBe('확인 필요')
  })
})

describe('toChanges', () => {
  it('칸 이름과 앞뒤 값을 화면 말로 바꾼다', () => {
    expect(
      toChanges([{ field: 'demolition_required', stored_value: null, new_value: 'REQUIRED' }]),
    ).toEqual([
      { key: 'demolition_required', label: '철거 필요 여부', previousValue: null, newValue: '필요함' },
    ])
  })

  /** 바뀐 것이 없다는 응답(`NO_CHANGE`)이 이 모양이다 */
  it('빈 목록은 바뀐 것이 없다는 뜻으로 받는다', () => {
    expect(toChanges([])).toEqual([])
  })

  /** 줄을 빼면 사장님이 남은 것이 바뀐 것의 전부인 줄 안다 */
  it('모르는 칸도 줄은 남기고 이름만 기타 항목으로 둔다', () => {
    expect(toChanges([{ field: 'shop_size', stored_value: null, new_value: '20' }])).toEqual([
      { key: 'shop_size', label: '기타 항목', previousValue: null, newValue: '확인 필요' },
    ])
  })

  it.each([
    ['목록이 아니다', { field: 'employee_count' }],
    ['목록이 없다', null],
    ['한 줄이 객체가 아니다', [{ field: 'employee_count', stored_value: '2', new_value: '3' }, 'x']],
    ['칸 이름이 없다', [{ stored_value: '2', new_value: '3' }]],
  ])('%s 면 통째로 버린다', (_, value) => {
    expect(toChanges(value)).toBeNull()
  })
})

describe('toConflicts', () => {
  it('서버 번호를 싣고 두 값을 화면 말로 바꾼다', () => {
    expect(
      toConflicts([
        { id: 7, field: 'demolition_required', stored_value: 'NOT_REQUIRED', proposed_value: 'REQUIRED' },
      ]),
    ).toEqual([
      {
        key: 'conflict-7',
        referenceId: 7,
        label: '철거 필요 여부',
        storedValue: '필요 없음',
        incomingValue: '필요함',
      },
    ])
  })

  /** 고르는 화면이라 빈 쪽도 글자가 있어야 한다. 빈 버튼은 누를 수 있는지조차 알 수 없다 */
  it('기록이 비어 있으면 미확인이라고 적는다', () => {
    const [item] = toConflicts([
      { id: 1, field: 'business_type', stored_value: 'UNKNOWN', proposed_value: '카페' },
    ])!

    expect(item.storedValue).toBe('미확인')
    expect(item.incomingValue).toBe('카페')
  })

  /** 칸 이름으로 열쇠를 만들면 같은 칸의 두 충돌에서 고른 것이 섞인다 */
  it('같은 칸의 충돌 둘도 열쇠가 겹치지 않는다', () => {
    const items = toConflicts([
      { id: 1, field: 'lease_status', stored_value: 'OWNED', proposed_value: 'LEASED_PAID' },
      { id: 2, field: 'lease_status', stored_value: 'OWNED', proposed_value: 'LEASED_FREE' },
    ])!

    expect(items.map((item) => item.key)).toEqual(['conflict-1', 'conflict-2'])
  })

  it.each([
    ['빈 목록이다', []],
    ['목록이 없다', null],
    ['번호가 없다', [{ field: 'lease_status', stored_value: 'OWNED', proposed_value: 'LEASED_PAID' }]],
    ['번호가 글자다', [{ id: '1', field: 'lease_status', stored_value: 'OWNED', proposed_value: 'LEASED_PAID' }]],
    ['칸 이름이 없다', [{ id: 1, stored_value: 'OWNED', proposed_value: 'LEASED_PAID' }]],
  ])('%s 면 통째로 버린다', (_, value) => {
    expect(toConflicts(value)).toBeNull()
  })
})

/** 들어올 때 받는 응답. 칸은 모두 비워 두고 테스트마다 필요한 것만 채운다 */
function entry(overrides: Partial<CaseResultsEntryResponse>): CaseResultsEntryResponse {
  return {
    judgment_status: 'DONE',
    case_history_id: null,
    raw_input: null,
    conflicts: null,
    next_action: null,
    questions_for_user: null,
    recovery_action_code: null,
    requested_field_paths: null,
    ...overrides,
  }
}

const NEXT_ACTION = { title: '임대인에게 원상복구 범위 묻기', reason: '', questions_to_ask: [] }

describe('toResultsEntry', () => {
  it('판단이 끝났으면 폼을 열 할 일과 판단 번호를 담는다', () => {
    expect(toResultsEntry(entry({ case_history_id: 12, next_action: NEXT_ACTION }))).toEqual({
      kind: 'READY',
      nextAction: { title: '임대인에게 원상복구 범위 묻기', reason: '', questions: [] },
      historyId: 12,
    })
  })

  it('충돌이 있으면 사장님이 한 말과 충돌 목록을 담는다', () => {
    const result = toResultsEntry(
      entry({
        judgment_status: 'CONFLICT',
        raw_input: '철거해야 한대요',
        conflicts: [{ id: 3, field: 'demolition_required', stored_value: 'NOT_REQUIRED', proposed_value: 'REQUIRED' }],
      }),
    )

    expect(result).toMatchObject({ kind: 'CONFIRM', view: { rawInput: '철거해야 한대요' } })
  })

  /** `/case` 가 이미 안내하는 상태들이다 */
  it('본문이 비어 있으면 알 수 없는 응답으로 둔다', () => {
    expect(toResultsEntry(null)).toEqual({ kind: 'UNRECOGNIZED' })
  })

  it.each(['PENDING', 'NEEDS_MORE_INFO', 'FAILED'] as const)('%s 면 다른 화면으로 보낸다', (status) => {
    expect(toResultsEntry(entry({ judgment_status: status, case_history_id: 12 }))).toEqual({
      kind: 'ELSEWHERE',
    })
  })

  /**
   * 번호 없이 폼을 열면 사장님이 다 적고 보낸 뒤에야 막힌다.
   * 할 일 없이 열면 무엇에 대한 결과를 적는지 모른다.
   */
  it.each([
    ['판단 번호가 없다', entry({ next_action: NEXT_ACTION })],
    ['할 일이 없다', entry({ case_history_id: 12 })],
    ['할 일에 제목이 없다', entry({ case_history_id: 12, next_action: { ...NEXT_ACTION, title: '' } })],
    ['충돌인데 목록이 없다', entry({ judgment_status: 'CONFLICT', raw_input: '철거해야 한대요' })],
    [
      '충돌인데 사장님이 한 말이 없다',
      entry({
        judgment_status: 'CONFLICT',
        conflicts: [{ id: 3, field: 'demolition_required', stored_value: 'NOT_REQUIRED', proposed_value: 'REQUIRED' }],
      }),
    ],
    ['모르는 상태다', entry({ judgment_status: 'ARCHIVED' as never, case_history_id: 12 })],
  ])('%s 면 알 수 없는 응답으로 둔다', (_, body) => {
    expect(toResultsEntry(body)).toEqual({ kind: 'UNRECOGNIZED' })
  })
})

/** 판단 결과 응답. 칸은 모두 비워 두고 테스트마다 필요한 것만 채운다 */
function judged(overrides: Partial<CaseResultsSubmitResponse>): CaseResultsSubmitResponse {
  return {
    result: 'UPDATED',
    changes: null,
    blocker: null,
    next_action: null,
    questions_for_user: null,
    raw_input: null,
    conflicts: null,
    recovery_action_code: null,
    requested_field_paths: null,
    ...overrides,
  }
}

const REPLANNED = {
  changes: [{ field: 'demolition_required', stored_value: null, new_value: 'REQUIRED' }],
  blocker: '철거 전에 지원 조건을 확인해야 합니다.',
  next_action: NEXT_ACTION,
}

const CONFLICTS = [
  { id: 3, field: 'demolition_required', stored_value: 'NOT_REQUIRED', proposed_value: 'REQUIRED' },
]

const UNRECOGNIZED = { kind: 'STAY', state: { kind: 'UNRECOGNIZED' } }

describe('toSubmitOutcome', () => {
  it('반영됐으면 바뀐 내용과 새 할 일을 싣고 재계획으로 보낸다', () => {
    expect(toSubmitOutcome(judged(REPLANNED))).toEqual({
      kind: 'REPLAN',
      view: {
        changes: [
          { key: 'demolition_required', label: '철거 필요 여부', previousValue: null, newValue: '필요함' },
        ],
        blocker: { title: '철거 전에 지원 조건을 확인해야 합니다.' },
        nextAction: { title: '임대인에게 원상복구 범위 묻기', reason: '', questions: [] },
      },
    })
  })

  it('바뀐 것이 없어도 재계획으로 보내고 변경 목록은 비운다', () => {
    expect(toSubmitOutcome(judged({ ...REPLANNED, result: 'NO_CHANGE', changes: [] }))).toMatchObject({
      kind: 'REPLAN',
      view: { changes: [] },
    })
  })

  it('되물을 것이 있으면 화면에 머물러 질문을 보여준다', () => {
    expect(
      toSubmitOutcome(judged({ result: 'NEEDS_MORE_INFO', questions_for_user: ['매장 전체인가요?'] })),
    ).toEqual({ kind: 'STAY', state: { kind: 'NEEDS_MORE_INFO', questions: ['매장 전체인가요?'] } })
  })

  /** 서버는 그 글을 보고 충돌을 찾았다. 화면이 들고 있던 글이 아니라 그것을 보여준다 */
  it('충돌이면 서버가 돌려준 글과 충돌 목록을 싣는다', () => {
    expect(
      toSubmitOutcome(judged({ result: 'CONFLICT', raw_input: '철거해야 한대요', conflicts: CONFLICTS })),
    ).toMatchObject({
      kind: 'CONFIRM',
      view: { rawInput: '철거해야 한대요', conflicts: [{ referenceId: 3 }] },
    })
  })

  /** 실패 이유를 읽는 규칙은 `/case` 와 같다. 칸 이름도 화면 말로 바뀌어 온다 */
  it('판단에 실패하면 화면에 머물러 이유를 담는다', () => {
    expect(
      toSubmitOutcome(
        judged({
          result: 'FAILED',
          recovery_action_code: 'RESUBMIT_INPUT',
          requested_field_paths: ['restoration_scope'],
        }),
      ),
    ).toEqual({
      kind: 'STAY',
      state: { kind: 'FAILED', notice: { kind: 'NEEDS_DETAIL', fields: ['원상복구 범위'], partial: false } },
    })
  })

  /**
   * 빠진 값을 다른 상태로 바꿔 보여주지 않는다. 할 일이 빈 반영을 "정보 부족"으로 그리면
   * 서버가 틀린 것을 사장님이 덜 적은 탓으로 읽는다.
   */
  it.each([
    ['반영인데 바뀐 내용이 없다', judged({ ...REPLANNED, changes: null })],
    ['반영인데 바뀐 내용 한 줄이 깨졌다', judged({ ...REPLANNED, changes: [{ stored_value: null }] as never })],
    ['반영인데 막힌 것이 없다', judged({ ...REPLANNED, blocker: '' })],
    ['반영인데 할 일이 없다', judged({ ...REPLANNED, next_action: null })],
    ['되묻는다면서 질문이 없다', judged({ result: 'NEEDS_MORE_INFO', questions_for_user: [] })],
    ['질문에 글자가 아닌 것이 섞였다', judged({ result: 'NEEDS_MORE_INFO', questions_for_user: [3] as never })],
    ['충돌인데 목록이 없다', judged({ result: 'CONFLICT', raw_input: '철거해야 한대요' })],
    ['충돌인데 사장님이 한 말이 없다', judged({ result: 'CONFLICT', conflicts: CONFLICTS })],
    // 기다리는 것은 `waitForResult` 가 맡는다. 여기서 또 기다리게 하면 자리가 둘이 된다.
    // 다른 칸을 채워 둔다 — 비어 있으면 판단 중을 반영으로 잘못 읽어도 여기서 안 잡힌다
    ['아직 판단 중이다', judged({ ...REPLANNED, result: 'PENDING' })],
    ['모르는 결과다', judged({ result: 'REJECTED' as never })],
  ])('%s 면 알 수 없는 응답으로 둔다', (_, body) => {
    expect(toSubmitOutcome(body)).toEqual(UNRECOGNIZED)
  })

  it('본문이 비어 있어도 알 수 없는 응답으로 둔다', () => {
    expect(toSubmitOutcome(null)).toEqual(UNRECOGNIZED)
  })
})
