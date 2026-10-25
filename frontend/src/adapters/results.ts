import { factLabelOf, fieldLabelOf, FRANCHISE_OPTIONS, LEASE_OPTIONS } from '../lib/caseOptions'
import type {
  CaseResultsEntryResponse,
  CaseResultsSubmitResponse,
  LeaseStatus,
  RestorationStatus,
} from '../types/api'
import type {
  ConfirmView,
  ConflictItem,
  FactChange,
  ResultsEntry,
  SubmitOutcome,
} from '../types/view'
import {
  DEMOLITION_LABEL,
  isReadableText,
  RESTORATION_SCOPE_LABEL,
  toDateLabel,
  toFailureNotice,
  toNextAction,
  toQuestionsForUser,
} from './case'

/**
 * 결과 제출 흐름(`/cases/results`)의 서버 응답을 화면 모양으로 바꾼다.
 *
 * `/case` 의 어댑터(`case.ts`)와 파일을 나눈 것은 받는 응답이 달라서다. 같은 칸을 같은
 * 말로 부르는 사전과 검사 함수는 `case.ts` 의 것을 그대로 가져다 쓴다.
 */

/**
 * 서버가 준 값을 우리가 알아볼 수 없을 때 띄우는 말.
 *
 * 영어 원문(`"PARTIAL_DONE"` 같은)을 그대로 내보내지 않는다. 사장님이 읽을 수 없고,
 * 우리가 모르는 값이라는 사실도 묻힌다. "미확인"과도 다르다 — 저쪽은 **서버가 모른다고
 * 한 것**이고, 이쪽은 **서버는 말했는데 우리가 못 알아들은 것**이다.
 */
const NEEDS_CHECK = '확인 필요'

/** 칸 이름을 모를 때. 줄을 빼면 바뀐 것이 그게 전부인 줄 알게 되어 줄은 남긴다 */
const UNKNOWN_FIELD = '기타 항목'

/** 원상복구 진행 상황. `/case` 의 사실 목록에는 안 나오고 바뀐 내용·충돌에만 나온다 */
const RESTORATION_STATUS_LABEL: Record<RestorationStatus, string | null> = {
  UNKNOWN: null,
  NOT_STARTED: '진행 전',
  IN_PROGRESS: '진행 중',
  COMPLETED: '완료',
  NOT_REQUIRED: '필요 없음',
}

/** 사전에서 찾는다. `Object.hasOwn` 인 이유는 `fieldLabelOf` 와 같다 */
function lookup(table: Record<string, string | null>, raw: string): string | null {
  return Object.hasOwn(table, raw) ? table[raw] : NEEDS_CHECK
}

/**
 * 칸 하나의 값을 화면 말로. `null` 이면 미확인이다.
 *
 * **값이 서버 쪽 표기 그대로 글자로 온다.** BE 가 원래 값을 파이썬 `str()` 로 적어서
 * 선택값은 `"FULL"`, 예/아니오는 `"True"`, 숫자는 `"3"`, 날짜는 `"2026-10-04"` 다.
 * 그래서 칸마다 읽는 법이 다르고, 칸 이름을 같이 받는다.
 *
 * `"UNKNOWN"` 은 **칸 종류와 상관없이** 미확인으로 본다. 충돌 항목은 빈칸을 못 받는
 * 자리라 BE 가 업종 같은 자유 글 칸에도 `"UNKNOWN"` 을 적는다.
 */
export function toValueLabel(field: string, raw: unknown): string | null {
  if (raw === null || raw === undefined || raw === '' || raw === 'UNKNOWN') return null
  if (typeof raw !== 'string') return NEEDS_CHECK

  switch (field) {
    case 'business_type':
    case 'restoration_scope_detail':
      return raw

    case 'franchise_status':
      if (raw === 'True') return factLabelOf(FRANCHISE_OPTIONS, true)
      if (raw === 'False') return factLabelOf(FRANCHISE_OPTIONS, false)
      return NEEDS_CHECK

    case 'lease_status':
      return factLabelOf(LEASE_OPTIONS, raw as LeaseStatus) ?? NEEDS_CHECK

    case 'employee_count':
      return /^\d+$/.test(raw) ? `${raw}명` : NEEDS_CHECK

    case 'planned_closure_date':
      return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? toDateLabel(raw) : NEEDS_CHECK

    case 'restoration_status':
      return lookup(RESTORATION_STATUS_LABEL, raw)

    case 'restoration_scope':
      return lookup(RESTORATION_SCOPE_LABEL, raw)

    case 'demolition_required':
      return lookup(DEMOLITION_LABEL, raw)

    default:
      // 칸을 모르면 값을 어떻게 읽을지도 모른다. 글자가 멀쩡해 보여도 내보내지 않는다
      return NEEDS_CHECK
  }
}

/** 서버 JSON 의 한 줄을 객체로 읽는다. 객체가 아니면 `null` */
function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

/**
 * 판단이 바꾼 칸 목록. 받을 수 없는 모양이면 `null`.
 *
 * 한 줄이라도 깨져 있으면 **통째로 버린다.** 성한 줄만 골라 그리면 사장님이 그게 바뀐
 * 것의 전부인 줄 안다 — 물어볼 말(`toNextAction`)을 다루는 규칙과 같다.
 *
 * 빈 목록은 받는다. "바뀐 것이 없음"(`NO_CHANGE`)이 그 모양이다.
 */
export function toChanges(value: unknown): FactChange[] | null {
  if (!Array.isArray(value)) return null

  const changes: FactChange[] = []
  for (const item of value) {
    const row = asRecord(item)
    if (row === null || !isReadableText(row.field)) return null

    changes.push({
      key: row.field,
      label: fieldLabelOf(row.field) ?? UNKNOWN_FIELD,
      previousValue: toValueLabel(row.field, row.stored_value),
      newValue: toValueLabel(row.field, row.new_value),
    })
  }
  return changes
}

/**
 * 확인을 기다리는 충돌 목록. 받을 수 없는 모양이면 `null`.
 *
 * **비어 있어도 `null` 이다.** 충돌이라면서 고를 것이 없으면 ④가 빈 화면에 확인 버튼만
 * 남는다. 한 줄이라도 깨져 있으면 통째로 버리는 것은 `toChanges` 와 같다 — 하나를
 * 빼고 보여주면 그 항목은 확인 없이 남는다.
 *
 * 화면 열쇠(`key`)는 서버 번호로 만든다. 같은 칸에 충돌이 둘 걸려도 고른 것이 섞이지 않는다.
 */
export function toConflicts(value: unknown): ConflictItem[] | null {
  if (!Array.isArray(value) || value.length === 0) return null

  const conflicts: ConflictItem[] = []
  for (const item of value) {
    const row = asRecord(item)
    if (row === null || !Number.isInteger(row.id) || !isReadableText(row.field)) return null

    conflicts.push({
      key: `conflict-${row.id}`,
      referenceId: row.id as number,
      label: fieldLabelOf(row.field) ?? UNKNOWN_FIELD,
      // ④는 두 값을 나란히 놓고 고르는 화면이라 빈 쪽도 글자로 보여야 한다
      storedValue: toValueLabel(row.field, row.stored_value) ?? '미확인',
      incomingValue: toValueLabel(row.field, row.proposed_value) ?? '미확인',
    })
  }
  return conflicts
}

/** 충돌 확인 화면 데이터. 사장님이 한 말이나 충돌 목록 중 하나라도 없으면 `null` */
function toConfirmView(rawInput: unknown, conflicts: unknown): ConfirmView | null {
  const items = toConflicts(conflicts)
  if (!isReadableText(rawInput) || items === null) return null
  return { rawInput, conflicts: items }
}

/**
 * `GET /cases/results` 를 ③ 화면이 할 일로.
 *
 * 상태마다 같이 와야 하는 값이 정해져 있다. 빠진 응답은 **다른 상태로 바꿔 보여주지
 * 않고** `UNRECOGNIZED` 로 둔다. `toJudgmentView` 와 같은 규칙이다.
 */
export function toResultsEntry(body: CaseResultsEntryResponse): ResultsEntry {
  switch (body.judgment_status) {
    case 'DONE': {
      // 번호가 없으면 결과를 보낼 수 없고, 할 일이 없으면 무엇에 대한 결과인지 보여줄 수 없다
      const nextAction = toNextAction(body.next_action)
      if (!Number.isInteger(body.case_history_id) || nextAction === null) return { kind: 'UNRECOGNIZED' }
      return { kind: 'READY', nextAction, historyId: body.case_history_id as number }
    }

    case 'CONFLICT': {
      const view = toConfirmView(body.raw_input, body.conflicts)
      return view === null ? { kind: 'UNRECOGNIZED' } : { kind: 'CONFIRM', view }
    }

    case 'PENDING':
    case 'NEEDS_MORE_INFO':
    case 'FAILED':
      return { kind: 'ELSEWHERE' }

    default:
      return { kind: 'UNRECOGNIZED' }
  }
}

const UNRECOGNIZED: SubmitOutcome = { kind: 'STAY', state: { kind: 'UNRECOGNIZED' } }

/**
 * 보낸 결과의 판단(`GET /cases/results/status`)을 ③ 화면이 할 일로.
 *
 * 받는 것은 `waitForResult` 가 기다려 얻은 **`PENDING` 이 아닌 응답**이다. 그래도 `PENDING`
 * 이 오면 알 수 없는 응답으로 둔다 — 여기서 다시 기다리게 만들면 기다리는 자리가 둘이 된다.
 *
 * 상태마다 같이 와야 하는 값이 빠진 응답은 **다른 상태로 바꿔 보여주지 않고**
 * `UNRECOGNIZED` 로 둔다. `toJudgmentView` 와 같은 규칙이다. 본문이 `null` 이어도 같다.
 */
export function toSubmitOutcome(body: CaseResultsSubmitResponse | null): SubmitOutcome {
  if (body === null || typeof body !== 'object') return UNRECOGNIZED

  switch (body.result) {
    case 'UPDATED':
    case 'NO_CHANGE': {
      // 바뀐 내용·막힌 것·할 일 중 하나라도 받을 수 없으면 ⑤가 빈 칸을 그린다
      const changes = toChanges(body.changes)
      const nextAction = toNextAction(body.next_action)
      if (changes === null || !isReadableText(body.blocker) || nextAction === null) return UNRECOGNIZED

      return { kind: 'REPLAN', view: { changes, blocker: { title: body.blocker }, nextAction } }
    }

    case 'NEEDS_MORE_INFO': {
      const questions = toQuestionsForUser(body.questions_for_user)
      if (questions === null) return UNRECOGNIZED
      return { kind: 'STAY', state: { kind: 'NEEDS_MORE_INFO', questions } }
    }

    case 'CONFLICT': {
      // 사장님이 한 말은 서버가 돌려준 것을 쓴다. 화면이 들고 있던 글과 다르면 서버가
      // 판단한 쪽이 맞다 — 그 글을 보고 충돌을 찾았다
      const view = toConfirmView(body.raw_input, body.conflicts)
      return view === null ? UNRECOGNIZED : { kind: 'CONFIRM', view }
    }

    case 'FAILED':
      return { kind: 'STAY', state: { kind: 'FAILED', notice: toFailureNotice(body) } }

    default:
      return UNRECOGNIZED
  }
}
