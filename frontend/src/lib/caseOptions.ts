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
