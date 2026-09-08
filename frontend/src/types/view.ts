/**
 * 화면이 필요한 데이터 모양 (FE 소유).
 *
 * 서버 계약(`types/api.ts`)과 변환 어댑터는 데이터 스키마가 확정된 뒤 별도로 추가한다.
 * 컴포넌트는 이 타입만 받는다 — 그래야 서버 응답 형태가 바뀌어도 어댑터만 고치면 된다.
 */

/** fact 하나의 확인 상태 */
export type FactStatus =
  /** 값이 확정됨 */
  | 'CONFIRMED'
  /** 지금 사용자가 확인하고 있는 항목 */
  | 'IN_PROGRESS'
  /** 아직 확인되지 않음 */
  | 'UNKNOWN'

/** Case를 이루는 사실 하나 */
export interface Fact {
  key: string
  label: string
  /** CONFIRMED일 때만 존재한다. 없으면 화면에서 미확인으로 표시한다 */
  value?: string
  status: FactStatus
}

/** 지금 진행을 막고 있는 것 */
export interface Blocker {
  title: string
  description?: string
}

/** 지금 먼저 할 일 — 화면에서 유일하게 강하게 강조하는 요소 */
export interface NextAction {
  /** 몇 번째 할 일인지. 서버가 센다 */
  seq: number
  title: string
  /** 왜 이걸 먼저 해야 하는지 */
  reason: string
  /** "이렇게 물어보시면 됩니다" — 사용자가 상대에게 물을 질문 */
  questions?: string[]
}

/**
 * ② 현재 Case 화면이 필요한 전체 데이터.
 *
 * 예외 상태를 `null` 조합으로 표현한다. 프론트가 조건을 판단하지 않고
 * 서버가 준 형태에 따라 화면을 고른다.
 *
 * | blocker | nextAction | 화면 |
 * | --- | --- | --- |
 * | O | O | 정상 |
 * | null | O | 막고 있는 것 없음 |
 * | * | null | 정보가 부족해 다음 할 일을 정할 수 없음 |
 */
export interface CurrentCaseView {
  /** 확인된 것과 미확인을 모두 담는다. 서버가 정한 순서를 그대로 쓴다 */
  facts: Fact[]
  blocker: Blocker | null
  nextAction: NextAction | null
}
