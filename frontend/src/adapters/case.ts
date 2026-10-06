import { factLabelOf, FRANCHISE_OPTIONS, LEASE_OPTIONS } from '../lib/caseOptions'
import type {
  CaseCreateRequest,
  CaseResponse,
  CasesEnvelope,
  DemolitionRequired,
  RestorationScope,
} from '../types/api'
import type { CaseDraft, CurrentCaseView, Fact, JudgmentView } from '../types/view'

/**
 * 서버 모양과 화면 모양 사이를 잇는다.
 *
 * 화면은 서버 필드 이름을 모르고, 서버는 화면 문구를 모른다. 그 사이를 여기 한곳에
 * 모아두면 서버 응답이 바뀔 때 고칠 자리가 하나다 — 흩어져 있으면 화면을 다 뒤져야 한다.
 *
 * 여기서 하는 것은 **표시**지 판단이 아니다. `LEASED_PAID`를 "임차 (월세)"로 바꾸는 것은
 * 숫자를 `1,500,000원`으로 바꾸는 것과 같은 층이다. 무엇이 막혀 있고 무엇을 먼저 할지는
 * 서버가 정한다 (`frontend/CLAUDE.md` 규칙 1·7).
 */

const RESTORATION_SCOPE_LABEL: Record<RestorationScope, string | null> = {
  UNKNOWN: null,
  PARTIAL: '일부',
  FULL: '전체',
  NOT_REQUIRED: '필요 없음',
}

const DEMOLITION_LABEL: Record<DemolitionRequired, string | null> = {
  UNKNOWN: null,
  REQUIRED: '필요함',
  NOT_REQUIRED: '필요 없음',
}

/**
 * 값이 없으면 미확인으로 둔다. 빈 문자열로 채우거나 목록에서 빼지 않는다 —
 * 모르는 것은 모른다고 보여주는 것이 이 제품의 약속이다.
 *
 * `undefined`까지 받는 것은 표에서 못 찾은 경우 때문이다. 서버가 우리가 모르는 값을
 * 보내면 조회 결과가 `undefined`인데, 그것을 확인된 값으로 취급하면 화면에 빈 줄이
 * "확인됨"으로 뜨고 "확인 N · 미확인 M" 숫자까지 틀어진다.
 */
/**
 * `2026-10-04` 를 `2026.10.04` 로.
 *
 * `Date` 로 바꾸지 않는다. `new Date('2026-10-04')` 는 UTC 자정이라, 한국보다 느린
 * 시간대에서 읽으면 하루 앞 날짜가 나온다. 사장님이 적어 넣은 글자를 그대로 쓰면
 * 그런 일이 없다 — 여기서 하는 것은 계산이 아니라 표기다.
 *
 * 값이 없는 길이 셋이다 — `null`, 칸 자체가 안 온 `undefined`, 빈 문자열. 셋 다 모른다는
 * 뜻이라 같게 둔다. `toFact` 가 그 뒤를 미확인으로 처리한다.
 */
function toDateLabel(value: string | null | undefined): string | null {
  return value ? value.replaceAll('-', '.') : null
}

function toFact(key: string, label: string, value: string | null | undefined): Fact {
  if (value === null || value === undefined) return { key, label, status: 'UNKNOWN' }
  return { key, label, value, status: 'CONFIRMED' }
}

/**
 * "내 가게 상황"에 나열할 항목.
 *
 * 사용자가 답할 수 있는 것만 담는다. `restoration_status`처럼 진행 단계를 나타내는 값은
 * 목록에 넣지 않는다 — "아직 확인 안 된 것"이 사용자에게 할 일로 읽히기 때문이다.
 */
export function toFacts(serverCase: CaseResponse): Fact[] {
  return [
    toFact('business_type', '업종', serverCase.business_type),
    toFact('franchise', '프랜차이즈', factLabelOf(FRANCHISE_OPTIONS, serverCase.franchise_status)),
    toFact(
      'employee_count',
      '직원 수',
      serverCase.employee_count === null ? null : `${serverCase.employee_count}명`,
    ),
    toFact('lease_status', '점포 형태', factLabelOf(LEASE_OPTIONS, serverCase.lease_status)),
    toFact('planned_closure_date', '폐업 예정일', toDateLabel(serverCase.planned_closure_date)),
    toFact(
      'restoration_scope',
      '원상복구 범위',
      RESTORATION_SCOPE_LABEL[serverCase.restoration_scope],
    ),
    toFact(
      'demolition_required',
      '철거 필요 여부',
      DEMOLITION_LABEL[serverCase.demolition_required],
    ),
  ]
}

/**
 * 판단 상태와 그 내용을 화면 모양으로.
 *
 * 상태마다 같이 와야 하는 값이 정해져 있다. 그 약속이 깨진 응답은 **다른 상태로 바꿔
 * 보여주지 않고** `UNRECOGNIZED` 로 둔다 — 예를 들어 `DONE` 인데 할 일이 비어 있는 것을
 * "정보 부족"으로 그리면, 서버가 틀린 것을 사장님이 덜 적어낸 탓으로 읽는다.
 *
 * 서버가 이 조합들을 500 으로 막고 있지만 여기서도 본다. 막는 쪽이 바뀌어도 화면은
 * 빈 칸을 그리지 않아야 한다.
 */
function toJudgmentView(envelope: CasesEnvelope): JudgmentView {
  const { judgment_status, blocker, next_action, questions_for_user } = envelope

  switch (judgment_status) {
    case 'PENDING':
      return { status: 'PENDING' }

    case 'FAILED':
      return { status: 'FAILED' }

    case 'DONE':
      // 둘 중 하나라도 비면 화면에 그릴 것이 없다. `null` 만 보지 않는 것은, 칸을 통째로
      // 빠뜨린 응답과 빈 문자열이 같은 결과를 내기 때문이다 — 제목 없는 할 일 카드가 뜨고
      // 그 밑의 "결과 알려주기" 는 멀쩡히 눌린다
      if (!blocker || !next_action) return { status: 'UNRECOGNIZED' }
      return {
        status: 'DONE',
        blocker: { title: blocker },
        nextAction: toNextAction(next_action),
      }

    case 'NEEDS_MORE_INFO':
      // 물어볼 것이 없는데 "물어볼 게 있다" 고 할 수는 없다. 칸이 아예 없으면
      // `.length` 에서 터지고, 그 오류는 조회 실패로 읽혀 "불러오지 못했어요" 가 뜬다
      if (!questions_for_user || questions_for_user.length === 0) {
        return { status: 'UNRECOGNIZED' }
      }
      return { status: 'NEEDS_MORE_INFO', questions: questions_for_user }

    default:
      // `null` 이거나 우리가 모르는 값. 서버가 상태를 늘렸다는 뜻이다
      return { status: 'UNRECOGNIZED' }
  }
}

/**
 * 서버는 다음 할 일의 **제목만** 보낸다.
 *
 * 이유(`reason`)와 상대에게 물어볼 말(`questions_to_ask`)은 DB 에 들어 있는데 응답에
 * 실리지 않는다(BE #44 에서 내려주기로 함). 그때까지 제목만으로 화면이 성립해야 해서
 * 나머지는 비워 둔다 — 카드가 빈 문단을 그리지 않는 것은 `NextActionCard` 가 맡는다.
 *
 * 순번(`seq`)도 응답에 없다. 1 로 채우지 않는다. 지어낸 순서는 사장님이 실제 순서로 읽는다.
 */
function toNextAction(title: string) {
  return { title, reason: '' }
}

/** 현재 Case 화면이 필요한 전체 데이터 */
export function toCurrentCaseView(envelope: CasesEnvelope, serverCase: CaseResponse): CurrentCaseView {
  return { facts: toFacts(serverCase), judgment: toJudgmentView(envelope) }
}

/**
 * 생성 폼의 값을 요청 모양으로 바꾼다.
 *
 * 필수 항목이 비어 있으면 `null`을 돌려준다. 폼이 이미 막고 있지만, 보내는 쪽에서 한 번 더
 * 걸러야 잘못된 요청이 서버까지 가지 않는다. 예외를 던지지 않는 것은 화면이 멈추는 것보다
 * 조용히 막고 버튼을 잠그는 편이 낫기 때문이다.
 *
 * 선택 항목은 빈 문자열이 아니라 `null`로 보낸다. 빈 문자열을 보내면 "모른다"와 "없다"가
 * 서버에서 같아진다.
 */
export function toCaseCreateRequest(draft: CaseDraft): CaseCreateRequest | null {
  const businessType = draft.businessType.trim()
  const employeeCount = draft.employeeCount.trim()

  if (businessType.length === 0) return null
  if (draft.franchiseStatus === null) return null
  if (draft.leaseStatus === null) return null

  // 비운 것은 "모른다"라 그대로 보내지만, 숫자가 아닌 값은 보내지 않는다.
  // `Number()`가 `NaN`을 내면 JSON으로 바뀌며 `null`이 되어, 잘못 적은 값이 "모른다"로 저장된다
  const parsedEmployeeCount = employeeCount.length === 0 ? null : Number(employeeCount)
  if (parsedEmployeeCount !== null && (!Number.isInteger(parsedEmployeeCount) || parsedEmployeeCount < 0))
    return null

  return {
    business_type: businessType,
    franchise_status: draft.franchiseStatus,
    employee_count: parsedEmployeeCount,
    lease_status: draft.leaseStatus,
    planned_closure_date: draft.plannedClosureDate || null,
  }
}
