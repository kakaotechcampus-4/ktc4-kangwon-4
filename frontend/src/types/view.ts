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
  /**
   * 몇 번째 할 일인지.
   *
   * `GET /cases` 응답에 없어서 선택이다. 없으면 "N번째" 표기를 아예 그리지 않는다 —
   * 1로 지어내면 사장님이 실제 순서를 아는 것처럼 읽는다.
   */
  seq?: number
  title: string
  /**
   * 왜 이걸 먼저 해야 하는지.
   *
   * 서버가 제목만 보내는 동안에는 비어 있다. 비면 문단 자체를 그리지 않는다.
   */
  reason: string
  /**
   * "이렇게 물어보시면 됩니다" — 사용자가 **상대에게** 물을 질문.
   *
   * 서비스가 사용자에게 되묻는 `questions_for_user` 와 다른 것이다. 둘 다 "질문"이라
   * 섞이기 쉬워, 이쪽은 Next Action 안에만 둔다.
   */
  questions?: string[]
}

/**
 * Agent 가 이 Case 를 어디까지 판단했는지, 그리고 그 결과.
 *
 * 상태와 결과를 한 덩어리로 묶는다. `DONE` 안에 `blocker` 와 `nextAction` 을 필수로 두면
 * **"판단은 끝났다는데 내용이 없는" 상태를 타입으로 표현할 수 없다.** 서버가 그런 조합을
 * 보내면 어댑터가 `UNRECOGNIZED` 로 떨어뜨릴 수밖에 없고, 화면에 빈 칸이 생기지 않는다.
 *
 * 조회 상태(`CaseQuery`)와는 다른 축이다 — 서버를 잘 불렀어도 판단은 아직 안 끝날 수 있다.
 */
export type JudgmentView =
  /** 판단 중. 잠시 뒤 다시 물어봐야 한다 */
  | { status: 'PENDING' }
  | { status: 'DONE'; blocker: Blocker; nextAction: NextAction }
  /** 다음 할 일을 정하려면 사용자에게 먼저 물어볼 것이 있다 */
  | { status: 'NEEDS_MORE_INFO'; questions: string[] }
  /** 판단을 마치지 못했다. 사용자 탓이 아니다 */
  | { status: 'FAILED' }
  /** 서버가 모르는 값을 보냈거나, 상태와 내용의 조합이 계약과 어긋난다 */
  | { status: 'UNRECOGNIZED' }

/**
 * ② 현재 Case 화면이 필요한 전체 데이터.
 *
 * **가게 정보와 판단을 나눠 둔다.** 전에는 `nextAction` 하나가 `null` 인지로 화면을
 * 골랐는데, 그러면 "판단 중"·"물어볼 게 있음"·"판단 실패"가 전부 "정보가 부족합니다"
 * 하나로 뭉개진다. 사장님 입장에서는 기다려야 하는 상황과 답해야 하는 상황이 다르다.
 *
 * 가게 정보는 판단 상태와 무관하게 늘 보여준다. 판단이 안 끝났어도 사장님이 적어낸
 * 내용은 그대로 남아 있다는 것을 알 수 있어야 한다.
 */
export interface CurrentCaseView {
  /** 확인된 것과 미확인을 모두 담는다. 서버가 정한 순서를 그대로 쓴다 */
  facts: Fact[]
  judgment: JudgmentView
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
 * `CASE_NOT_FOUND`는 여기 없다. 404라서 화면 상태가 아니라 통신 층에서 다룰 것이다.
 * TODO(API): fetch를 붙일 때 그 경로를 어디서 받을지 정한다.
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

/**
 * 점포 형태. 서버 `lease_status`와 같은 값이다.
 *
 * TODO(계약): AI 쪽은 같은 이름으로 계약 단계(`ACTIVE` · `TERMINATION_NOTIFIED` …)를
 * 담고 있어 뜻이 다르다. 칸이 둘로 갈릴 수 있고 PM 판단을 기다리는 중이다.
 */
export type LeaseStatus =
  /** 임차 — 임대료를 낸다 */
  | 'LEASED_PAID'
  /** 임차 — 임대료를 내지 않는다 (무상임차) */
  | 'LEASED_FREE'
  /** 자가 */
  | 'OWNED'

/**
 * Case 생성 폼이 들고 있는 값.
 *
 * 아직 아무것도 고르지 않은 상태를 `null`로 둔다. `false`나 빈 문자열을 기본값으로
 * 두면 "아니오를 골랐다"와 "아직 안 골랐다"가 같아져서 제출을 막을 근거가 사라진다.
 *
 * 직원 수와 폐업 예정일이 문자열인 것은 입력 중간 상태 때문이다. 숫자로 들고 있으면
 * 사용자가 지우는 순간 값을 뭘로 둘지 애매해진다. 숫자 변환은 보낼 때 한 번만 한다.
 */
export interface CaseDraft {
  businessType: string
  franchiseStatus: boolean | null
  leaseStatus: LeaseStatus | null
  /** 선택 항목. 비어 있으면 모른다는 뜻이고 서버에는 `null`로 간다 */
  employeeCount: string
  /** 선택 항목. `YYYY-MM-DD` */
  plannedClosureDate: string
}
