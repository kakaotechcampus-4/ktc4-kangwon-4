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
 * | O | O | Next Action + Blocker |
 * | null | O | Next Action + 막힌 것 없음 |
 * | O | null | 정보 부족 + Blocker |
 * | null | null | 정보 부족만 |
 *
 * "막힌 것 없음"은 다음 할 일이 있을 때만 의미 있는 정보다. 할 일을 정하지 못한 상태에서
 * 막힌 게 없다고 하면 긍정 신호로 오해된다.
 *
 * TODO(BE 확인): `nextAction: null`이 실제로 어떤 서버 상태인지 확정되지 않았다.
 * `GET /cases/{caseId}`의 `latestDecision`이 `null`로 올 수 있는지, 있다면 어떤 상황인지.
 *
 * `POST /cases`와 `GET /cases/{caseId}`는 판단을 함께 반환하고, `/results`의
 * `NEEDS_MORE_INFO`는 Case를 바꾸지 않아 이전 판단이 그대로 유효하다. 그러면 남는 건
 * `REPLAN_FAILED`(오류) 쪽인데, 그건 정보 부족이 아니라 재시도 안내가 맞다.
 *
 * 지금 화면은 "정보 부족"으로 안내한다. 오류 상태에 이 문구를 쓰면 서버 실패를
 * 사용자 탓으로 돌리게 되므로, 계약이 확정되면 화면 소속과 문구를 다시 정한다.
 */
export interface CurrentCaseView {
  /** 확인된 것과 미확인을 모두 담는다. 서버가 정한 순서를 그대로 쓴다 */
  facts: Fact[]
  blocker: Blocker | null
  nextAction: NextAction | null
}

/**
 * ③ 결과 입력 화면이 필요한 데이터.
 *
 * 무엇에 대한 결과인지 상기시키려고 직전 Next Action을 함께 보여준다.
 * 사용자는 며칠 뒤에 들어올 수도 있어서, 자기가 무슨 일을 하러 갔는지 잊는다.
 */
export interface ResultInputView {
  nextAction: NextAction
}

/**
 * 결과를 보낸 뒤 ③ 화면이 머무는 상태.
 *
 * 서버 응답 중 **화면을 옮기지 않는 것들**만 여기 온다. `UPDATED`·`NO_CHANGE`는
 * ⑤로, `CONFLICT`는 ④로 가므로 이 목록에 없다.
 *
 * 서버의 `result` 값을 그대로 쓰지 않고 화면 상태로 다시 이름 붙인 것은,
 * `PENDING`처럼 서버에 없는 상태가 섞이기 때문이다. 변환은 어댑터가 맡는다.
 */
export type SubmitState =
  /** 아직 보내지 않음 */
  | { kind: 'IDLE' }
  /** 보내고 기다리는 중 */
  | { kind: 'PENDING' }
  /** 입력만으로는 상태를 확정할 수 없어 되묻는다 */
  | { kind: 'NEEDS_MORE_INFO'; questions: string[] }
  /** 지금 상태에서 있을 수 없는 변화라 정정을 요청한다 */
  | { kind: 'INVALID_TRANSITION'; message: string }
  /** 재계획에 실패했다. 사용자 탓이 아니므로 문구를 구분한다 */
  | { kind: 'FAILED'; message: string }

/** ④에서 사용자가 고른 쪽 */
export type ConflictSide = 'STORED' | 'INCOMING'

/** 기존 기록과 새 입력이 어긋난 항목 하나 */
export interface ConflictItem {
  key: string
  label: string
  storedValue: string
  incomingValue: string
}

/**
 * ④ 충돌 확인 화면이 필요한 데이터.
 *
 * 사용자가 방금 한 말(`rawInput`)을 함께 보여준다. 어느 문장 때문에 이 화면이
 * 떴는지 모르면 무엇을 고르는지도 알 수 없다.
 */
export interface ConfirmView {
  rawInput: string
  conflicts: ConflictItem[]
}

/** ⑤에서 보여줄 변경 한 건 */
export interface FactChange {
  key: string
  label: string
  /** null = 이전에는 미확인이었다. 빈 문자열로 대신하지 않는다 */
  previousValue: string | null
  newValue: string
}

/**
 * ⑤ 재계획 결과 화면이 필요한 데이터.
 *
 * `changes`가 빈 배열이면 "바뀐 것이 없음"이다. 별도 플래그를 두지 않는다 —
 * 서버가 상태 이름을 정하고 프론트가 그 이름을 해석하는 층을 만들지 않기 위해서다.
 * `blocker`·`nextAction`의 `null` 의미는 `CurrentCaseView`와 같다.
 */
export interface ReplanView {
  changes: FactChange[]
  blocker: Blocker | null
  nextAction: NextAction | null
}

/**
 * 결과를 보낸 뒤 ③ 화면이 할 일.
 *
 * 응답 종류에 따라 화면을 옮기거나 그 자리에 머문다. 어디로 갈지는 화면이 정하고,
 * 서버 응답을 이 모양으로 바꾸는 것은 어댑터가 맡는다.
 */
export type SubmitOutcome =
  /** 반영됐다. ⑤로 이동 (`UPDATED` · `NO_CHANGE`) */
  | { kind: 'REPLAN'; view: ReplanView }
  /** 기존 기록과 어긋난다. ④로 이동 (`CONFLICT`) */
  | { kind: 'CONFIRM'; view: ConfirmView }
  /** 화면에 머문다 */
  | { kind: 'STAY'; state: SubmitState }
