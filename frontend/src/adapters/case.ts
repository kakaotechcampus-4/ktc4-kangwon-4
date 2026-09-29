import { factLabelOf, FRANCHISE_OPTIONS, LEASE_OPTIONS } from '../lib/caseOptions'
import type {
  CaseCreateRequest,
  CaseResponse,
  DemolitionRequired,
  RestorationScope,
} from '../types/api'
import type { CaseDraft, CurrentCaseView, Fact } from '../types/view'

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
 * 현재 Case 화면이 필요한 전체 데이터.
 *
 * TODO(API): `blocker`와 `next_action`이 아직 응답에 없다(BE #39). 그동안은 둘 다 `null`이라
 * 화면이 "다음 할 일을 정할 수 없습니다"를 보여주는데, 그게 지금으로서는 사실이다.
 */
export function toCurrentCaseView(serverCase: CaseResponse): CurrentCaseView {
  return { facts: toFacts(serverCase), blocker: null, nextAction: null }
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
  if (parsedEmployeeCount !== null && !Number.isInteger(parsedEmployeeCount)) return null

  return {
    business_type: businessType,
    franchise_status: draft.franchiseStatus,
    employee_count: parsedEmployeeCount,
    lease_status: draft.leaseStatus,
    planned_closure_date: draft.plannedClosureDate || null,
  }
}
