import type { LeaseStatus } from '../types/view'

/**
 * Case 생성에서 고르는 선택지.
 *
 * 화면과 어댑터가 같은 목록을 봐야 해서 한곳에 모은다. 값이 바뀌거나 칸이 갈릴 때
 * 고칠 자리가 여기 하나면 된다 — `lease_status`는 실제로 갈릴 가능성이 남아 있다.
 *
 * 문구가 서버 값과 1:1이 아닌 것에 주의한다. 사장님은 "무상임차"라는 말을 쓰지 않는다.
 */

interface Option<T> {
  value: T
  /** 고를 때 읽는 문구. 질문에 답하는 말투다 */
  label: string
  /** 고르기 전에 읽을 한 줄. 용어를 모르는 사용자가 잘못 고르는 것을 막는다 */
  hint?: string
  /**
   * 고른 뒤 "내 가게 상황" 목록에 표시할 문구.
   *
   * `label`을 그대로 쓸 수 없다. "월세를 내고 있어요"는 질문에 답하는 말투라
   * 사실을 나열하는 목록에서는 어색하다. 같은 값의 두 표기를 한곳에 둬서,
   * 값이 바뀌어도 고칠 자리가 하나이게 한다.
   */
  factLabel: string
}

export const LEASE_OPTIONS: Option<LeaseStatus>[] = [
  { value: 'LEASED_PAID', label: '월세를 내고 있어요', factLabel: '임차 (월세)' },
  {
    value: 'LEASED_FREE',
    label: '임대료는 안 내요',
    hint: '가족 가게이거나 무상으로 빌린 경우',
    factLabel: '임차 (무상)',
  },
  { value: 'OWNED', label: '제 건물이에요', factLabel: '자가' },
]

export const FRANCHISE_OPTIONS: Option<boolean>[] = [
  { value: true, label: '프랜차이즈예요', factLabel: '프랜차이즈' },
  { value: false, label: '아니에요', factLabel: '비프랜차이즈' },
]

/**
 * 고른 값을 사실 목록에 표시할 문구로 바꾼다.
 *
 * 목록에 없는 값이 오면 `null`이다 — 서버가 우리가 모르는 값을 보냈다는 뜻이라,
 * 지어내 보여주지 않고 미확인으로 둔다.
 */
export function factLabelOf<T>(options: Option<T>[], value: T): string | null {
  return options.find((option) => option.value === value)?.factLabel ?? null
}

/**
 * 서버가 Case의 칸 하나를 **이름으로 가리킬 때** 쓰는 말을 화면 말로 바꾼다.
 *
 * 값이 아니라 칸 이름을 옮기는 것이라 위 선택지 목록과 쓰임이 다르다. 서버는 여러
 * 자리에서 칸을 이름으로 지목하는데(판단 실패의 `requested_field_paths`, 변경 내역의
 * `field`, 충돌 항목의 `field`) 전부 같은 어휘를 쓴다. 그래서 사전은 하나면 된다.
 *
 * 순서는 서버 쪽 `CaseFieldKey`를 그대로 따른다. 나란히 놓고 보면 빠진 칸이 눈에 띈다.
 */
export const FIELD_LABEL = {
  business_type: '업종',
  franchise_status: '프랜차이즈',
  employee_count: '직원 수',
  lease_status: '점포 형태',
  restoration_status: '원상복구 진행 상황',
  restoration_scope: '원상복구 범위',
  restoration_scope_detail: '원상복구 범위 설명',
  demolition_required: '철거 필요 여부',
  planned_closure_date: '폐업 예정일',
} as const

/**
 * 칸 이름을 화면 문구로. 모르는 이름이면 `null`.
 *
 * **서버가 준 이름을 그대로 화면에 내보내지 않는다.** `restoration_scope_detail` 같은
 * 영어 칸 이름이 사장님에게 뜨면 읽을 수 없는 글자가 되고, 우리가 모르는 이름이라는
 * 사실도 묻힌다.
 *
 * `in`이 아니라 `Object.hasOwn`이다. `'toString'`처럼 모든 객체가 물려받는 이름이
 * 들어와도 아는 칸으로 통과하지 않는다 — 들어오는 값이 서버 JSON이라 걸러야 한다.
 */
export function fieldLabelOf(field: string): string | null {
  return Object.hasOwn(FIELD_LABEL, field) ? FIELD_LABEL[field as keyof typeof FIELD_LABEL] : null
}
