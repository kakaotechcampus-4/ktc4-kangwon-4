import type { DiagnosisAnswers, DiagnosisBusiness } from '../types/view'

/**
 * 상황 진단 질문 하나의 이름. 주소의 `?step=` 값으로 그대로 쓴다.
 *
 * - `biz`       어떤 가게 (시안)
 * - `franchise` 프랜차이즈 여부 — 다른 음식점일 때만
 * - `situ`      해당하는 것 모두 (시안)
 * - `rent`      월세 여부 — 빌린 가게일 때만
 * - `restore`   원상복구 조항 — 빌린 가게일 때만 (시안)
 * - `staff`     직원 수 — 직원이 있을 때만 (시안)
 * - `hadStaff`  예전 직원 — 지금 직원이 없을 때만
 * - `insurance` 가게 이름으로 가입했던 4대보험
 * - `date`      폐업 시기 (시안)
 */
export type DiagnosisStep =
  | 'biz'
  | 'franchise'
  | 'situ'
  | 'rent'
  | 'restore'
  | 'staff'
  | 'hadStaff'
  | 'insurance'
  | 'date'

/**
 * 지금 진단을 받는 업종. 나머지 업종은 첫 질문에 보이기만 하고 "준비 중"으로 막는다(#310).
 *
 * 고를 수 있게 두면 Case가 만들어진 뒤 첫 판단이 바로 실패하고, 사장님은 다시 알려 줘도 풀리지 않는
 * 실패 화면을 만난다. 업종을 열 때는 여기에 더한다 — 프랜차이즈 질문(`franchise`)은 그때를 위해 남겨 둔다.
 */
const OPEN_BUSINESSES: readonly DiagnosisBusiness[] = ['PERSONAL_CAFE']

export function isOpenBusiness(business: DiagnosisBusiness | null): boolean {
  return business !== null && OPEN_BUSINESSES.includes(business)
}

/**
 * 지금 답으로 물어야 할 질문들을 순서대로.
 *
 * 앞 답에 따라 뒤 질문이 생기고 빠진다. 아직 "해당하는 것"을 고르기 전에는 아무것도
 * 고르지 않은 것으로 보고 센다 — 그래서 그 질문을 지나면 전체 수가 늘 수 있다.
 *
 * 질문을 묻는 조건이지 판단이 아니다. 어떤 할 일이 필요한지는 서버가 정한다(FE 규칙 1).
 * 여기서는 "빌린 가게가 아니면 월세를 묻지 않는다"처럼 답할 수 없는 질문만 거른다.
 */
export function diagnosisSteps(answers: DiagnosisAnswers): DiagnosisStep[] {
  const situations = answers.situations ?? []
  const leased = situations.includes('LEASE')
  const hasStaff = situations.includes('STAFF')

  const steps: (DiagnosisStep | false)[] = [
    'biz',
    answers.business === 'RESTAURANT' && 'franchise',
    'situ',
    leased && 'rent',
    leased && 'restore',
    hasStaff && 'staff',
    // 지금 직원이 있으면 묻지 않는다. "있다"인데 "둔 적 없다"고 답하면 서버 판단이 멈춘다
    !hasStaff && 'hadStaff',
    'insurance',
    'date',
  ]

  return steps.filter((step) => step !== false)
}

/**
 * 그 질문에 답했는지. 답해야 다음으로 넘어갈 수 있다.
 *
 * 직원 수는 0명에서 시작하므로 "답했다"를 1명 이상으로 본다. 직원이 있다고 골랐는데
 * 0명으로 넘어가면 앞 답과 어긋난다.
 */
export function isStepAnswered(step: DiagnosisStep, answers: DiagnosisAnswers): boolean {
  switch (step) {
    // 막힌 업종을 골라 둔 답이 브라우저에 남아 있어도 답하지 않은 것으로 본다. 첫 질문에서 다시 고른다
    case 'biz':
      return isOpenBusiness(answers.business)
    case 'franchise':
      return answers.franchise !== null
    case 'situ':
      return answers.situations !== null
    case 'rent':
      return answers.paysRent !== null
    case 'restore':
      return answers.restorationClause !== null
    case 'staff':
      return answers.fullTimeCount + answers.partTimeCount > 0
    case 'hadStaff':
      return answers.hadEmployees !== null
    case 'insurance':
      return answers.insurances !== null
    case 'date':
      return answers.closure !== null
  }
}

/**
 * 주소로 열려는 질문을 실제로 보여줄 질문으로 바꾼다.
 *
 * 주소는 사장님이 직접 고치거나 북마크로 열 수 있다. 앞 질문에 답하지 않았는데
 * 뒤 질문을 보여주면 빈 답으로 보내게 되고, 지금 답으로는 묻지 않는 질문(빌린 가게가
 * 아닌데 월세)을 보여주면 보낼 때 버려질 답을 받게 된다. 그래서:
 *
 * - 앞에 답하지 않은 질문이 있으면 그 질문으로
 * - 지금 묻지 않는 질문이거나 주소에 질문이 없으면, 답하지 않은 첫 질문으로
 * - 다 답했으면 마지막 질문으로
 */
export function reachableStep(requested: string | null, answers: DiagnosisAnswers): DiagnosisStep {
  const steps = diagnosisSteps(answers)
  const target = steps.findIndex((step) => step === requested)
  const firstOpen = steps.findIndex((step) => !isStepAnswered(step, answers))

  if (target !== -1 && (firstOpen === -1 || target <= firstOpen)) return steps[target]
  return steps[firstOpen === -1 ? steps.length - 1 : firstOpen]
}
