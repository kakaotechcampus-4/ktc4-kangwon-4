import { factLabelOf, FRANCHISE_OPTIONS, LEASE_OPTIONS } from '../lib/caseOptions'
import type {
  CaseCreateRequest,
  CaseResponse,
  CasesEnvelope,
  DemolitionRequired,
  NextActionResponse,
  RestorationScope,
} from '../types/api'
import type { CaseDraft, CurrentCaseView, Fact, JudgmentView, NextAction } from '../types/view'

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
 * 화면에 그대로 띄울 수 있는 글자인지.
 *
 * 타입에 `string` 으로 적혀 있어도 실제로 오는 JSON 은 그 약속을 지키지 않을 수 있다.
 * 글자가 아닌 것이 글자 자리에 들어가면 React 가 객체를 받아 화면이 통째로 죽는다.
 *
 * 비어 있는 것과 모양이 다른 것을 같이 본다 — 둘 다 "그릴 것이 없다" 는 뜻이고,
 * 화면이 할 수 있는 일도 같다.
 */
function isReadableText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

/**
 * 다음 할 일을 화면 모양으로. 받을 수 없는 모양이면 `null`.
 *
 * **제목만 필수다.** 이유와 물어볼 말은 없어도 카드가 성립하고, 없으면 그 자리를 아예
 * 그리지 않는다. 반면 제목이 없으면 띄울 것이 없다.
 *
 * 물어볼 말은 하나라도 글자가 아니면 **통째로 버린다.** 성한 것만 골라 그리면 사장님이
 * 그게 물어볼 말의 전부인 줄 알고, 빠뜨린 채로 임대인을 만난다.
 */
function toNextAction(value: unknown): NextAction | null {
  if (value === null || typeof value !== 'object') return null

  const { title, reason, questions_to_ask } = value as Partial<NextActionResponse>
  if (!isReadableText(title)) return null

  return {
    title,
    reason: isReadableText(reason) ? reason : '',
    questions:
      Array.isArray(questions_to_ask) && questions_to_ask.every(isReadableText)
        ? questions_to_ask
        : undefined,
  }
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

    // 검증할 것이 없다. 어긋난 항목은 응답에 안 실려 온다(#66).
    //
    // `blocker` 가 딸려 와도 보지 않는다 — 그건 충돌이 나기 전의 판단이라, 지금 할 일로
    // 그리면 사장님이 이미 어긋난 전제 위에서 움직이게 된다. `PENDING`·`FAILED` 와 같은 규칙이다
    case 'CONFLICT':
      return { status: 'CONFLICT' }

    case 'DONE': {
      // 막힌 것과 할 일 중 하나라도 받을 수 없으면 그릴 것이 없다. 칸을 빠뜨린 응답·
      // 빈 문자열·모양이 다른 응답이 모두 여기 걸린다 — 통과시키면 제목 없는 할 일 카드가
      // 뜨고 그 밑의 "결과 알려주기" 는 멀쩡히 눌린다
      const nextAction = toNextAction(next_action)
      if (!isReadableText(blocker) || nextAction === null) return { status: 'UNRECOGNIZED' }

      return { status: 'DONE', blocker: { title: blocker }, nextAction }
    }

    case 'NEEDS_MORE_INFO':
      // 물어볼 것이 없는데 "물어볼 게 있다" 고 할 수는 없다.
      //
      // 목록인지만 보면 모자라다. 글자가 아닌 것이 담겨 있어도 화면이 그릴 수 없어서,
      // 카드가 목록을 펼치다 React 에 객체를 넘기고 거기서 앱이 내려간다. 바깥 그릇만
      // 보고 안에 든 것을 안 보면 `next_action` 에서 막은 것과 같은 구멍이 남는다
      if (
        !Array.isArray(questions_for_user) ||
        questions_for_user.length === 0 ||
        !questions_for_user.every(isReadableText)
      ) {
        return { status: 'UNRECOGNIZED' }
      }
      return { status: 'NEEDS_MORE_INFO', questions: questions_for_user }

    default:
      // `null` 이거나 우리가 모르는 값. 서버가 상태를 늘렸다는 뜻이다
      return { status: 'UNRECOGNIZED' }
  }
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
