/**
 * 화면이 필요한 데이터 모양 (FE 소유).
 *
 * 서버 계약(`types/api.ts`)과 변환 어댑터는 데이터 스키마가 확정된 뒤 별도로 추가한다.
 * 컴포넌트는 이 타입만 받는다 — 그래야 서버 응답 형태가 바뀌어도 어댑터만 고치면 된다.
 */

// 폐업 사유·보증금 결과는 서버 값을 그대로 고르는 보기라, 같은 값을 여기 한 벌 더 적지 않는다
import type { ClosureReason, DepositReturnResult, ResultInputKind } from './api'

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
   * 서버가 안 보내면 빈 글자다. 비면 문단 자체를 그리지 않으므로 빈 자리가 남지 않는다.
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
 * 판단이 실패했을 때 화면이 **무엇을 설명할지**.
 *
 * 서버 코드(`recovery_action_code`)를 그대로 쓰지 않고 다시 이름 붙인다. 서버 값은
 * "서버가 분류한 복구 행동"이고 여기 이름은 "화면이 띄울 안내 종류"라, **지금은 둘이
 * 1:1이지만 같은 것이 아니다.** 코드가 늘거나 한 코드를 두 화면으로 나눌 때 갈린다.
 *
 * **안내 종류로 이름 붙이고 사용자가 할 행동으로 붙이지 않는다.** 이번 작업에서 새로
 * 만드는 행동이 없기 때문이다 — 누를 것은 기존 "상태 다시 확인" 하나뿐이고, 그것도
 * 저장된 상태를 다시 읽을 뿐 판단을 다시 돌리지 않는다.
 */
export type FailureNotice =
  /**
   * 서버가 **다시 해볼 수 있는 것으로 분류한** 실패.
   *
   * **원인이 일시적이라는 뜻이 아니다.** 판단이 결과를 내놓기도 전에 끊기면 원인을
   * 가리지 않고 전부 이쪽으로 저장된다. "잠시 후 다시" 라고 말하면 안 되는 이유다.
   */
  | { kind: 'RETRY_AVAILABLE' }
  /**
   * 판단을 이어가려면 Case 의 어떤 칸을 더 알아야 한다.
   *
   * `fields` 는 이미 화면 문구로 바뀐 것이다. 비어 있으면 **어느 칸인지 말할 수 없다**는
   * 뜻이고(서버가 안 보냈거나 우리가 모르는 이름만 왔다), 그때는 항목을 특정하지 않는다.
   *
   * `partial` 은 **일부만 알아봤다**는 뜻이다. 아는 것만 적고 그것이 전부인 척하면
   * 사장님이 나머지를 영영 모른 채로 남는다.
   */
  | { kind: 'NEEDS_DETAIL'; fields: string[]; partial: boolean }
  /** 사장님 쪽에서 할 수 있는 것이 없고 서비스가 들여다봐야 한다 */
  | { kind: 'SERVICE_SIDE' }
  /** 서버가 **할 수 있는 복구 행동이 없다고 말했다.** 모르는 것과 다르다 */
  | { kind: 'NO_RECOVERY' }
  /**
   * 코드가 안 왔거나 우리가 모르는 값이다.
   *
   * `NO_RECOVERY` 와 반드시 나눈다. 저쪽은 **서버가 없다고 말한 것**이고 이쪽은
   * **우리가 못 알아들은 것**이라, 뭉개면 계약이 어긋난 사실이 화면 뒤로 숨는다.
   */
  | { kind: 'UNKNOWN_CAUSE' }

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
  /**
   * 사용자가 한 말이 기록과 어긋나 어느 쪽이 맞는지 확인해야 한다.
   *
   * 담는 값이 없다. 서버가 `judgment_status` 만 보내고 **어긋난 항목은 싣지 않기로**
   * 했다 — 그 목록은 충돌 확인 API 를 만들 때 함께 내려준다(#66).
   */
  | { status: 'CONFLICT' }
  /**
   * 판단을 마치지 못했다. 사용자 탓이 아니다.
   *
   * **왜 실패했는지까지 담는다.** 전에는 상태만 들고 있어서 네 가지 실패가 한 문구로
   * 나왔는데, 그중 "정보가 더 있어야 한다"까지 "저희가 다시 해보겠습니다"로 읽혀
   * 사장님이 기다리면 되는 줄 알게 된다.
   */
  | { status: 'FAILED'; notice: FailureNotice }
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
  /**
   * 폐업 정리를 모두 마쳤는지. 서버가 `case_status` 를 `COMPLETED` 로 바꿨을 때만 `true` 다(#167).
   *
   * 판단(`judgment`)과는 다른 축이다. 완료돼도 마지막 판단 기록은 남아 있고, 완료를 풀면(부가세 체크를
   * 풀면) 그 판단이 다시 지금 할 일이 된다.
   */
  completed: boolean
  /** 저장해 둔 통합 폐업 신고 정보. 저장 전이면 `null`. 신고 화면을 이 값으로 채워 연다 */
  closureReport: ClosureReportView | null
  /** 기록해 둔 보증금 결과. 기록 전이면 `null`. 보증금 화면을 이 값으로 골라 둔 채 연다 */
  depositReturn: DepositReturnResult | null
}

/** 통합 폐업 신고에 적을 값(#168). 서버가 폐업일·사유·도로명 주소를 한 번에 저장한다 */
export interface ClosureReportView {
  /** `YYYY-MM-DD`. 날짜 고르기 칸에 그대로 넣는다 */
  closureDate: string
  closureReason: ClosureReason
  roadAddress: string
  /** 상세 주소는 비워도 된다(단독 건물 등) */
  addressDetail: string | null
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
 * ③ 결과 입력 화면에 들어왔을 때 할 일.
 *
 * 결과는 **가장 최근 판단에 대해서만** 보낼 수 있다. 그래서 들어올 때 지금 판단이 어디까지
 * 왔는지 서버에 먼저 묻고, 결과를 받을 수 있는 상태일 때만 폼을 연다.
 */
export type ResultsEntry =
  /** 결과를 받을 수 있다. `historyId` 는 이 결과가 어느 판단에 대한 것인지 가리킨다 */
  | { kind: 'READY'; nextAction: NextAction; historyId: number; inputKind: ResultInputKind }
  /** 확인을 기다리는 충돌이 있다. 그것부터 풀어야 해서 ④로 보낸다 */
  | { kind: 'CONFIRM'; view: ConfirmView }
  /**
   * 리본이 되물은 것이 있다. 할 일의 결과 대신 이 질문들의 답을 받는다.
   *
   * 답도 결과와 같은 길(`POST /cases/results`)로 보내므로 `historyId` 가 필요하다.
   */
  | { kind: 'ANSWER'; questions: string[]; historyId: number }
  /**
   * 판단이 실패했는데, 사장님이 더 알려주시면 풀린다(`NEEDS_DETAIL`). 무엇이 더 필요한지
   * 보여주고 글을 다시 받는다.
   */
  | { kind: 'RESUBMIT'; notice: Extract<FailureNotice, { kind: 'NEEDS_DETAIL' }>; historyId: number }
  /**
   * 지금은 결과를 받을 때가 아니다 — 판단 중이거나, 더 적어도 풀리지 않는 실패다.
   *
   * 둘 다 `/case` 가 이미 안내하는 상태라 그쪽으로 보낸다. 여기서 같은 안내를 한 번 더
   * 만들면 두 화면의 문구가 따로 놀게 된다.
   */
  | { kind: 'ELSEWHERE' }
  /** 서버가 모르는 상태를 보냈거나, 상태와 내용의 조합이 계약과 어긋난다 */
  | { kind: 'UNRECOGNIZED' }

/**
 * 결과를 보낸 뒤 ③ 화면이 머무는 상태.
 *
 * 서버 응답 중 **화면을 옮기지 않는 것들**만 여기 온다. `UPDATED`·`NO_CHANGE`는
 * ⑤로, `CONFLICT`는 ④로 가므로 이 목록에 없다.
 *
 * 서버의 `result` 값을 그대로 쓰지 않고 화면 상태로 다시 이름 붙인 것은, 보내기 실패나
 * 오래 걸림처럼 **서버 응답이 아닌 상태**가 섞이기 때문이다. 변환은 어댑터가 맡는다.
 *
 * **어떤 상태에서도 적은 글은 지우지 않는다.** 다시 보내든 고쳐 보내든 사장님이 같은 말을
 * 처음부터 다시 적게 하면 안 된다.
 */
export type SubmitState =
  /** 아직 보내지 않음 */
  | { kind: 'IDLE' }
  /**
   * 보내고 기다리는 중.
   *
   * `accepted` 는 서버가 접수 번호를 돌려줬는지다. 처리 단계 줄의 첫 줄("보냈어요")이 이것으로만
   * 끝난다 — 서버가 처리 단계를 내려주지 않아서, 화면이 확실히 아는 사건은 접수와 결과뿐이다.
   */
  | { kind: 'PENDING'; accepted: boolean }
  /** 입력만으로는 상태를 확정할 수 없어 되묻는다 */
  | { kind: 'NEEDS_MORE_INFO'; questions: string[] }
  /**
   * 보낸 결과를 판단하지 못했다. 이유는 `/case` 와 같은 `FailureNotice` 로 담는다 —
   * 서버가 같은 복구 코드를 보내므로 이름도 같아야 두 화면이 같은 실패를 같은 종류로 다룬다.
   */
  | { kind: 'FAILED'; notice: FailureNotice }
  /**
   * 보내기 자체가 실패했다 — 네트워크가 끊겼거나 서버가 답하지 못했다.
   *
   * `FAILED` 와 나눈다. 저쪽은 서버가 받아서 판단까지 해 본 것이고, 여기는 **받았는지조차
   * 모르는 것**이다. 그래서 여기서만 같은 글을 그대로 다시 보내라고 할 수 있다.
   */
  | { kind: 'SEND_FAILED' }
  /**
   * 서버가 이 글을 받지 않았다(422) — 너무 길거나(2,000자) 받을 수 없는 모양이다.
   *
   * `SEND_FAILED` 와 나눈다. 저쪽은 같은 글을 다시 보내면 될 수 있지만, 여기는 같은 글을 보내면 또
   * 거절된다. 그래서 [다시 보내기]를 달지 않고 고쳐서 보내게 한다. 왜 거절됐는지는 화면이 몰라 단정하지 않는다.
   */
  | { kind: 'SEND_REJECTED' }
  /**
   * 그사이 상황이 바뀌었다 — 이미 접수된 결과가 있거나, 새 판단이 나왔거나, 확인을
   * 기다리는 충돌이 생겼다. 이 화면이 아는 판단이 낡았으니 `/case` 로 돌려보낸다.
   *
   * **원인을 단정하지 않는다.** 서버는 셋을 같은 409 로 준다. 응답이 늦어 "보내지 못함" 으로
   * 보였던 제 제출이 이미 접수된 경우도 여기 온다 — "다른 곳에서 보냈다" 고 하면 틀린다.
   */
  | { kind: 'STALE' }
  /**
   * 접수는 됐는데 상한까지 판단 결과를 받지 못했다. 끝나면 `/case` 에서 보인다.
   *
   * 판단 중이라고 단정하지 않는다. 상태 조회가 계속 실패해도 여기 온다 — 사장님이 할 일은
   * 어느 쪽이든 `/case` 에서 확인하는 것이라 나누지 않는다.
   */
  | { kind: 'WAITED_TOO_LONG' }
  /** 서버가 모르는 결과를 보냈거나, 결과와 내용의 조합이 계약과 어긋난다 */
  | { kind: 'UNRECOGNIZED' }

/** ④에서 사용자가 고른 쪽 */
export type ConflictSide = 'STORED' | 'INCOMING'

/** 기존 기록과 새 입력이 어긋난 항목 하나 */
export interface ConflictItem {
  key: string
  /**
   * 서버가 이 충돌에 붙인 번호.
   *
   * 고른 쪽을 보낼 때 어느 항목에 대한 답인지 이 번호로 가리킨다. `key` 로 대신하지 않는다 —
   * `key` 는 화면이 고른 것을 기억하는 열쇠고, 서버 번호와 섞으면 화면 열쇠를 바꿀 때
   * 보내는 값까지 같이 바뀐다.
   */
  referenceId: number
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
  /** null = 바뀐 뒤 미확인이 됐다. 서버가 칸을 비울 수도 있다 */
  newValue: string | null
}

/**
 * ⑤ 재계획 결과 화면이 필요한 데이터.
 *
 * `changes`가 빈 배열이면 "바뀐 것이 없음"이다. 별도 플래그를 두지 않는다 —
 * 서버가 상태 이름을 정하고 프론트가 그 이름을 해석하는 층을 만들지 않기 위해서다.
 * `blocker`의 `null` 의미는 `CurrentCaseView`와 같다.
 *
 * `nextAction`은 꼭 있다. 다음 할 일이 없는 반영 응답은 어댑터가 읽지 못한 응답으로 돌려서
 * 이 화면까지 오지 않는다(`toSubmitOutcome`). 폐업을 다 마쳐 할 일이 없어지는 날이 오면
 * 그때는 이 화면이 아니라 완료 화면으로 보낸다.
 *
 * `newTasks` 는 이번 판단으로 새로 해야 할 일이 된 로드맵 할 일이다(로드맵 순서). 비교할 수 없거나 없으면
 * 빈 목록이다 — 사장님에게는 둘 다 "새로 생긴 것 없음"이다.
 */
export interface ReplanView {
  changes: FactChange[]
  blocker: Blocker | null
  nextAction: NextAction
  newTasks: { id: string; title: string }[]
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

/** 점포 형태. 서버 `lease_status`와 같은 값이다. AI 쪽도 같은 값을 쓴다 */
export type LeaseStatus =
  /** 임차 — 임대료를 낸다 */
  | 'LEASED_PAID'
  /** 임차 — 임대료를 내지 않는다 (무상임차) */
  | 'LEASED_FREE'
  /** 자가 */
  | 'OWNED'

/** 상황 진단 첫 질문 "어떤 가게를 정리하시나요?"의 보기 */
export type DiagnosisBusiness = 'PERSONAL_CAFE' | 'FRANCHISE_CAFE' | 'RESTAURANT'

/** "가게에 해당하는 것을 모두 골라주세요"의 보기 */
export type DiagnosisSituation = 'LEASE' | 'STAFF' | 'LOAN' | 'CONTRACT'

/** "가입했던 적이 있는 보험을 모두 골라주세요"의 보기 (4대보험) */
export type DiagnosisInsurance = 'PENSION' | 'HEALTH' | 'EMPLOYMENT' | 'INDUSTRIAL_ACCIDENT'

/** "원상복구 조항이 있나요?"의 보기. 서버 `restoration_clause`와 같은 세 값이다 */
export type DiagnosisRestorationClause = 'EXISTS' | 'NOT_EXISTS' | 'UNKNOWN'

/** "언제 문을 닫으실 생각이세요?"의 보기 */
export type DiagnosisClosure = 'THIS_MONTH' | 'NEXT_MONTH' | 'UNDECIDED'

/**
 * 상황 진단에서 사장님이 고른 답. 보낼 값이 아니라 **고른 보기 그대로**다.
 *
 * 서버 칸으로 바꾸는 일은 보낼 때 어댑터가 한 번만 한다. 여기서 미리 바꿔 두면
 * "개인 카페"와 "프랜차이즈 카페"가 같은 `CAFE`가 되어, 뒤로 돌아왔을 때 무엇을
 * 골랐는지 화면에 다시 표시할 수 없다.
 *
 * 아직 답하지 않은 질문은 `null`이다. 여럿 고르는 질문도 마찬가지로, 빈 배열은
 * "해당하는 게 없어요"를 고른 것이고 `null`은 아직 그 질문에 오지 않은 것이다.
 *
 * 조건에 따라 나오는 질문(월세·원상복구·직원 수 등)의 답은, 앞 답을 바꿔 그 질문이
 * 빠져도 지우지 않는다. 다시 켜면 그대로 남아 있게 하고, 보낼 때 조건을 다시 본다.
 */
export interface DiagnosisAnswers {
  business: DiagnosisBusiness | null
  /** 다른 음식점일 때만 묻는다. 카페는 첫 질문에서 이미 정해진다 */
  franchise: boolean | null
  situations: DiagnosisSituation[] | null
  /** 빌린 가게일 때만 묻는다. `true`면 월세를 낸다 */
  paysRent: boolean | null
  /** 빌린 가게일 때만 묻는다 */
  restorationClause: DiagnosisRestorationClause | null
  /** 직원이 있을 때만 묻는다. 정직원 + 아르바이트가 보낼 직원 수가 된다 */
  fullTimeCount: number
  partTimeCount: number
  /** 지금 직원이 없을 때만 묻는다 */
  hadEmployees: boolean | null
  /**
   * 고른 보험. 빈 목록은 "가입한 적 없어요", `UNKNOWN`은 "잘 모르겠어요"다.
   * 둘을 나누는 것은 서버에서 뜻이 달라서다 — 없음은 보험 할 일을 빼고, 모름은 확인 필요로 남긴다
   */
  insurances: DiagnosisInsurance[] | 'UNKNOWN' | null
  closure: DiagnosisClosure | null
}

/** 기록을 남긴 쪽. 서버 `actor`와 같은 값이다 */
export type LogActor = 'OWNER' | 'RIBBON'

/**
 * 기록 탭의 한 줄 (시안 M08).
 *
 * 문구는 서버가 주지 않고 사건 코드(`event`)만 준다. 화면이 코드를 문구로 바꾼다
 * (`adapters/logs.ts`).
 */
export interface LogEntry {
  key: string
  actor: LogActor
  text: string
  /** 덧붙이는 한 줄. 정한 할 일 제목, 사장님이 알려 준 심사 결과, 마친 할 일 이름 등. 없으면 그리지 않는다 */
  detail?: string
  /** 체크 기록(`CHECKLIST_*`)이면 어떤 할 일인지. 로드맵 이름을 붙이는 데 쓴다(`withTaskTitles`) */
  taskId?: string
  /** `10.17` 처럼 월.일. 서버가 준 날짜 글자를 그대로 잘라 쓴다 */
  date: string
}

/** 서류에서 꺼낸 값 하나. 이름은 화면 말로 바꿔 둔다 */
export interface DocumentFieldView {
  /** 서버 칸 이름(`amount` 등). 확인해서 다시 보낼 때 이 이름으로 보낸다 */
  name: string
  /**
   * 화면 말. 모르는 칸이면 `null` 이고 화면에 보여주지 않는다 — 영어 칸 이름을 띄울 수 없다.
   * 그래도 확인할 때는 원래 값 그대로 같이 보낸다
   */
  label: string | null
  value: string
}

/**
 * 서류함의 서류 한 장.
 *
 * 종류 이름(`kindLabel`)과 확인이 필요한지(`needsConfirmation`)는 서버가 정해 준 그대로다.
 * 화면이 파일 이름이나 값을 보고 다시 가리지 않는다.
 */
export interface DocumentView {
  id: string
  filename: string
  /** 서버 종류 코드(`TRANSFER` 등). 사장님이 종류를 고쳐 보낼 때 쓴다 */
  kind: string
  kindLabel: string
  needsConfirmation: boolean
  /** 사장님이 확인했으면 확인한 값, 아니면 서버가 꺼낸 값 */
  fields: DocumentFieldView[]
}

/** 정산 서류 점검 결과 */
export type DocumentCheckStatus = 'COMPLETE' | 'ISSUES' | 'ERROR'

export interface DocumentCheckView {
  status: DocumentCheckStatus
  steps: { name: string; status: 'WAITING' | 'RUNNING' | 'DONE' | 'NEEDS_CONFIRMATION' | 'ERROR' }[]
  /** 서버가 쓴 문구 그대로("정산 점검 목록에서 빠진 서류: 이체확인증") */
  issues: string[]
}

/** 서류함 화면 데이터. 서류를 더하거나 빼면 서버가 지난 점검을 지워 `check` 가 `null` 이 된다 */
export interface DocumentsView {
  documents: DocumentView[]
  check: DocumentCheckView | null
}

/** 로드맵 할 일의 상태. 서버(AI 로드맵 `TaskStatus`)와 같은 값이다 */
export type RoadmapTaskStatus = 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED' | 'NOT_APPLICABLE' | 'NEEDS_CONFIRMATION'

/**
 * 로드맵 할 일의 종류. 서버와 같은 값이다.
 *
 *   CHECKLIST       사장님이 체크하는 항목(체크 저장 `PUT /cases/checklists/{task_id}`)
 *   PROCEDURE       공식 절차. 결과를 알려주면 판단이 상태를 바꾼다
 *   DOCUMENT_CHECK  서류 점검
 *   CASE_FACT       가게 정보로 정해지는 것(폐업 날짜, 철거비 심사 결과 등)
 */
export type RoadmapTaskKind = 'CHECKLIST' | 'PROCEDURE' | 'DOCUMENT_CHECK' | 'CASE_FACT'

export interface RoadmapTaskView {
  /** 서버 할 일 번호(`dispose_stock` 등) */
  id: string
  title: string
  kind: RoadmapTaskKind
  status: RoadmapTaskStatus
  /** 검수한 설명. 일부 할 일에만 있다(#144) */
  guidance?: string
}

export interface RoadmapStageView {
  stage: number
  title: string
  tasks: RoadmapTaskView[]
}

/**
 * 로드맵 화면 데이터 (시안 M03).
 *
 * 현재 단계는 서버가 정한다(현종님 로드맵 조회 API 계획). 화면이 할 일 상태를 보고 짐작하지 않는다.
 * 미지원 업종(프랜차이즈 카페·다른 음식점)이면 `supported` 가 `false` 이고 단계가 비어 있다.
 */
export interface RoadmapView {
  supported: boolean
  /** 미지원일 때 서버가 쓴 안내 문구 */
  unsupportedReason: string | null
  /** 지금 단계 번호(1~5). 서버가 안 주면 `null` 이고 어느 단계도 강조하지 않는다 */
  currentStage: number | null
  stages: RoadmapStageView[]
}
