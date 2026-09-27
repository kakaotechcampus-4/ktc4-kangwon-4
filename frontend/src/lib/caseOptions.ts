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
  label: string
  /** 고르기 전에 읽을 한 줄. 용어를 모르는 사용자가 잘못 고르는 것을 막는다 */
  hint?: string
}

export const LEASE_OPTIONS: Option<LeaseStatus>[] = [
  { value: 'LEASED_PAID', label: '월세를 내고 있어요' },
  { value: 'LEASED_FREE', label: '임대료는 안 내요', hint: '가족 가게이거나 무상으로 빌린 경우' },
  { value: 'OWNED', label: '제 건물이에요' },
]

export const FRANCHISE_OPTIONS: Option<boolean>[] = [
  { value: true, label: '프랜차이즈예요' },
  { value: false, label: '아니에요' },
]
