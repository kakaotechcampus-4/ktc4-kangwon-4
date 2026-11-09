import { describe, expect, it } from 'vitest'

import type { CaseResultsEntryResponse, CaseResultsSubmitResponse } from '../types/api'
import {
  toAnswerInput,
  toChanges,
  toConflicts,
  toDecisionRequest,
  toResultsEntry,
  toResultSteps,
  toSubmitOutcome,
  toValueLabel,
} from './results'

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

const CONFLICT_ITEMS = toConflicts([
  { id: 4, field: 'lease_status', stored_value: 'OWNED', proposed_value: 'LEASED_PAID' },
  { id: 7, field: 'demolition_required', stored_value: 'NOT_REQUIRED', proposed_value: 'REQUIRED' },
])!

/**
 * 고른 쪽이 뒤집혀 나가면 사장님이 버린 값이 Case에 저장된다. 되돌릴 수 있는 자리는
 * 이 화면뿐이라(`rollback` 없음) 여기서 틀리면 고칠 길이 없다.
 */
describe('toDecisionRequest', () => {
  it('충돌마다 서버 번호와 고른 쪽을 서버 말로 싣는다', () => {
    expect(toDecisionRequest(CONFLICT_ITEMS, { 'conflict-4': 'INCOMING', 'conflict-7': 'STORED' })).toEqual({
      decisions: [
        { conflict_reference_id: 4, side: 'PROPOSED' },
        { conflict_reference_id: 7, side: 'STORED' },
      ],
    })
  })

  /** 서버는 남은 충돌을 전부 받아야 한다. 반쪽 요청은 422로 돌아온다 */
  it('하나라도 고르지 않았으면 만들지 않는다', () => {
    expect(toDecisionRequest(CONFLICT_ITEMS, { 'conflict-4': 'INCOMING' })).toBeNull()
  })
})

/** 들어올 때 받는 응답. 칸은 모두 비워 두고 테스트마다 필요한 것만 채운다 */
function entry(overrides: Partial<CaseResultsEntryResponse>): CaseResultsEntryResponse {
  return {
    judgment_status: 'DONE',
    result_input_kind: 'TEXT',
    action_done_kind: null,
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
  it('서버가 선택형 입력을 지정하면 그대로 화면에 전달한다', () => {
    expect(toResultsEntry(entry({ case_history_id: 12, next_action: NEXT_ACTION, result_input_kind: 'RESTORATION_ANSWER' })))
      .toMatchObject({ kind: 'READY', inputKind: 'RESTORATION_ANSWER' })
  })

  it.each([undefined, 'OTHER'])('입력 종류 %s 는 추측해서 표시하지 않는다', (kind) => {
    const body = { ...entry({ case_history_id: 12, next_action: NEXT_ACTION }), result_input_kind: kind }
    expect(toResultsEntry(body as CaseResultsEntryResponse)).toEqual({ kind: 'UNRECOGNIZED' })
  })

  it('판단이 끝났으면 폼을 열 할 일과 판단 번호를 담는다', () => {
    expect(toResultsEntry(entry({ case_history_id: 12, next_action: NEXT_ACTION }))).toEqual({
      kind: 'READY',
      nextAction: { title: '임대인에게 원상복구 범위 묻기', reason: '', questions: [] },
      historyId: 12,
      inputKind: 'TEXT',
      doneKind: null,
    })
  })

  /** 버튼 문구는 서버가 준 할 일 종류로 고른다. 종류가 없거나 모르는 값이면 지어내지 않는다 */
  it('[했어요] 할 일이면 버튼 종류를 담고, 종류를 모르면 읽지 못했다고 본다', () => {
    const body = { case_history_id: 12, next_action: NEXT_ACTION, result_input_kind: 'ACTION_DONE' as const }
    expect(toResultsEntry(entry({ ...body, action_done_kind: 'SUBMISSION' }))).toMatchObject({
      kind: 'READY', inputKind: 'ACTION_DONE', doneKind: 'SUBMISSION',
    })
    expect(toResultsEntry(entry({ ...body, action_done_kind: null }))).toEqual({ kind: 'UNRECOGNIZED' })
    expect(toResultsEntry(entry({ ...body, action_done_kind: 'MAYBE' as never }))).toEqual({ kind: 'UNRECOGNIZED' })
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

  it('되물은 것이 있으면 답을 받을 질문과 판단 번호를 담는다', () => {
    expect(
      toResultsEntry(
        entry({ judgment_status: 'NEEDS_MORE_INFO', case_history_id: 12, questions_for_user: ['직원이 몇 명인가요?'] }),
      ),
    ).toEqual({ kind: 'ANSWER', questions: ['직원이 몇 명인가요?'], historyId: 12, inputKind: 'TEXT' })
  })

  it('원상복구 진행 상태 질문이면 버튼으로 받는다고 담는다', () => {
    expect(
      toResultsEntry(entry({
        judgment_status: 'NEEDS_MORE_INFO', case_history_id: 12, result_input_kind: 'RESTORATION_STATUS',
        questions_for_user: ['원상복구 작업이 어디까지 진행됐는지 알려주세요.'],
      })),
    ).toEqual({
      kind: 'ANSWER', questions: ['원상복구 작업이 어디까지 진행됐는지 알려주세요.'], historyId: 12,
      inputKind: 'RESTORATION_STATUS',
    })
  })

  it('되물은 질문에 [했어요] 같은 다른 입력 방식이 오면 알 수 없는 응답으로 둔다', () => {
    expect(
      toResultsEntry(entry({
        judgment_status: 'NEEDS_MORE_INFO', case_history_id: 12, result_input_kind: 'ACTION_DONE',
        questions_for_user: ['직원이 몇 명인가요?'],
      })),
    ).toEqual({ kind: 'UNRECOGNIZED' })
  })

  it.each(['PENDING', 'FAILED'] as const)('%s 면 다른 화면으로 보낸다', (status) => {
    expect(toResultsEntry(entry({ judgment_status: status, case_history_id: 12 }))).toEqual({
      kind: 'ELSEWHERE',
    })
  })

  /** 등록된 절차를 다 마쳐 받을 결과가 없다(#315). 할 일이 비어 와도 읽지 못한 것이 아니라 홈이 안내할 상태다 */
  it('등록된 절차를 다 마쳤으면 홈으로 보낸다', () => {
    expect(toResultsEntry(entry({ judgment_status: 'PROCEDURES_COMPLETED', case_history_id: 40 }))).toEqual({
      kind: 'ELSEWHERE',
    })
  })

  it('더 알려주셔야 풀리는 실패면 무엇이 필요한지와 판단 번호를 담는다', () => {
    expect(
      toResultsEntry(
        entry({
          judgment_status: 'FAILED',
          case_history_id: 12,
          recovery_action_code: 'RESUBMIT_INPUT',
          requested_field_paths: ['restoration_scope'],
        }),
      ),
    ).toEqual({
      kind: 'RESUBMIT',
      notice: { kind: 'NEEDS_DETAIL', fields: ['원상복구 범위'], partial: false },
      historyId: 12,
    })
  })

  /** 번호가 없으면 다 적고 보낸 뒤에야 막힌다 */
  it('더 알려주셔야 하는 실패인데 판단 번호가 없으면 알 수 없는 응답으로 둔다', () => {
    expect(
      toResultsEntry(entry({ judgment_status: 'FAILED', recovery_action_code: 'RESUBMIT_INPUT' })),
    ).toEqual({ kind: 'UNRECOGNIZED' })
  })

  it('NONE 실패는 이전 질문 없이 새 글을 받고 판단 번호가 없으면 열지 않는다', () => {
    const failed = entry({ judgment_status: 'FAILED', recovery_action_code: 'NONE',
      requested_field_paths: ['restoration_scope'], questions_for_user: ['예전 질문'],
      result_input_kind: 'RESTORATION_ANSWER' })
    expect(toResultsEntry({ ...failed, case_history_id: 12 })).toEqual({ kind: 'NEW_INPUT', historyId: 12 })
    expect(toResultsEntry(failed)).toEqual({ kind: 'UNRECOGNIZED' })
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
    [
      '되묻는다면서 판단 번호가 없다',
      entry({ judgment_status: 'NEEDS_MORE_INFO', questions_for_user: ['직원이 몇 명인가요?'] }),
    ],
    ['되묻는다면서 질문이 없다', entry({ judgment_status: 'NEEDS_MORE_INFO', case_history_id: 12 })],
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
    new_tasks: null,
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
  /** 다음 할 일이 없는 것이 정상이다(#315). 반영 결과는 다음 할 일을 꼭 그려서 그쪽으로 보내지 않는다 */
  it('등록된 절차를 다 마쳤으면 할 일이 비어 있어도 마친 것으로 둔다', () => {
    expect(
      toSubmitOutcome(judged({ result: 'PROCEDURES_COMPLETED', changes: [], blocker: null, next_action: null })),
    ).toEqual({ kind: 'FINISHED' })
  })

  it('반영됐으면 바뀐 내용과 새 할 일을 싣고 재계획으로 보낸다', () => {
    expect(toSubmitOutcome(judged(REPLANNED))).toEqual({
      kind: 'REPLAN',
      view: {
        changes: [
          { key: 'demolition_required', label: '철거 필요 여부', previousValue: null, newValue: '필요함' },
        ],
        blocker: { title: '철거 전에 지원 조건을 확인해야 합니다.' },
        nextAction: { title: '임대인에게 원상복구 범위 묻기', reason: '', questions: [] },
        newTasks: [],
      },
    })
  })

  /** 시안 "할 일 3개가 새로 생겼어요"(#182). 로드맵 순서 그대로 둔다 */
  it('새로 생긴 할 일을 서버가 준 순서대로 싣는다', () => {
    const outcome = toSubmitOutcome(
      judged({
        ...REPLANNED,
        new_tasks: [
          { task_id: 'support_application', title: '소상공인24 사전 신청' },
          { task_id: 'before_photo', title: '철거 전 사진' },
        ],
      }),
    )

    expect(outcome).toMatchObject({
      kind: 'REPLAN',
      view: {
        newTasks: [
          { id: 'support_application', title: '소상공인24 사전 신청' },
          { id: 'before_photo', title: '철거 전 사진' },
        ],
      },
    })
  })

  /** 그사이 알려 준 심사 결과로 할 일이 늘었을 수 있다. 바뀐 게 없어도 오는 대로 싣는다(현석님 #182) */
  it('바뀐 것이 없어도 새로 생긴 할 일은 싣는다', () => {
    const outcome = toSubmitOutcome(
      judged({ ...REPLANNED, result: 'NO_CHANGE', changes: [], new_tasks: [{ task_id: 'support_application', title: '소상공인24 사전 신청' }] }),
    )

    expect(outcome).toMatchObject({ kind: 'REPLAN', view: { newTasks: [{ id: 'support_application' }] } })
  })

  /** 덤인 칸 하나 때문에 멀쩡한 반영 결과를 못 보여주면 더 큰 손해다 */
  it('새로 생긴 할 일을 읽지 못해도 반영 결과는 보여주고, 빈 줄만 뺀다', () => {
    const broken = toSubmitOutcome(judged({ ...REPLANNED, new_tasks: 'three' as unknown as null }))
    expect(broken).toMatchObject({ kind: 'REPLAN', view: { newTasks: [] } })

    const partly = toSubmitOutcome(
      judged({ ...REPLANNED, new_tasks: [{ task_id: '', title: '이름 없음' }, { task_id: 'before_photo', title: '철거 전 사진' }] }),
    )
    expect(partly).toMatchObject({ kind: 'REPLAN', view: { newTasks: [{ id: 'before_photo', title: '철거 전 사진' }] } })
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

/**
 * 재판단 때 AI는 직전에 무엇을 물었는지 모른다. 질문이 빠지면 "2명이요"가 무엇의 답인지
 * 알 수 없어, 사장님이 답했는데도 같은 질문을 또 받게 된다.
 */
describe('toAnswerInput', () => {
  it('질문과 답을 짝으로 적는다', () => {
    expect(toAnswerInput([{ question: '직원이 몇 명인가요?', answer: '2명이요' }])).toBe(
      '[리본이 물어본 것] 직원이 몇 명인가요?\n[사장님 답] 2명이요',
    )
  })

  it('질문이 여러 개면 빈 줄로 나눈다', () => {
    expect(
      toAnswerInput([
        { question: '직원이 몇 명인가요?', answer: '2명이요' },
        { question: '프랜차이즈 가게인가요?', answer: '아니요' },
      ]),
    ).toBe(
      '[리본이 물어본 것] 직원이 몇 명인가요?\n[사장님 답] 2명이요\n\n' +
        '[리본이 물어본 것] 프랜차이즈 가게인가요?\n[사장님 답] 아니요',
    )
  })

  /** 답이 없는 질문까지 보내면 AI가 "모른다"는 답으로 읽을 수 있다 */
  it('답을 적지 않은 질문은 빼고, 앞뒤 빈칸은 지운다', () => {
    expect(
      toAnswerInput([
        { question: '직원이 몇 명인가요?', answer: '  2명이요 ' },
        { question: '프랜차이즈 가게인가요?', answer: '   ' },
      ]),
    ).toBe('[리본이 물어본 것] 직원이 몇 명인가요?\n[사장님 답] 2명이요')
  })
})

/**
 * 충돌 확인에서 보낸 것은 글을 정리하는 판단이 아니다. 문구는 달라도 기다리는 사건은 같아서,
 * 줄이 끝나는 때까지 달라지면 같은 기다림이 다른 속도로 보인다.
 */
describe('toResultSteps', () => {
  it('충돌 결정은 둘째 줄 문구만 다르고 끝나는 때는 같다', () => {
    for (const stage of ['SENDING', 'WAITING', 'DONE'] as const) {
      const result = toResultSteps(stage)
      const decision = toResultSteps(stage, 'DECISION')

      expect(decision.map((step) => step.status)).toEqual(result.map((step) => step.status))
      expect(decision[1].label).toBe('고르신 내용을 반영하고 있어요')
      expect([decision[0].label, decision[2].label]).toEqual([result[0].label, result[2].label])
    }
  })
})
