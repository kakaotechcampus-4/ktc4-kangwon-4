/**
 * 서버가 주고받는 데이터 모양 (서버 소유).
 *
 * 필드 이름을 서버 그대로 **snake_case** 로 둔다. 팀이 snake_case 로 합의했고,
 * 화면이 쓰는 이름으로 바꾸는 것은 `adapters/` 가 할 일이다.
 * 여기서 미리 바꿔두면 서버 응답과 이 파일을 나란히 놓고 비교할 수 없게 된다.
 *
 * 확정되지 않은 필드는 넣지 않는다. optional 로 열어두면 응답이 비어 있어도
 * 조용히 넘어가서 계약이 어긋난 것을 못 잡는다 (`frontend/CLAUDE.md` 규칙 9).
 */

/** 점포 형태 */
export type LeaseStatus = 'LEASED_PAID' | 'LEASED_FREE' | 'OWNED'

/** Case 진행 상태 */
export type CaseStatus = 'IN_PROGRESS' | 'COMPLETED'

/** 원상복구 진행 상태 */
export type RestorationStatus = 'UNKNOWN' | 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED' | 'NOT_REQUIRED'

/** 원상복구 범위 */
export type RestorationScope = 'UNKNOWN' | 'PARTIAL' | 'FULL' | 'NOT_REQUIRED'

/** 철거 필요 여부 */
export type DemolitionRequired = 'UNKNOWN' | 'REQUIRED' | 'NOT_REQUIRED'

export interface RestorationAnswer {
  restoration_scope: RestorationScope
  demolition_required: DemolitionRequired
}

/** 지금 할 일에 [했어요]를 눌렀다. [아직 안 했어요]는 보내지 않으므로 true만 있다 */
export interface ActionDone {
  action_done: true
}

/** 원상복구 진행 상태 질문에 버튼으로 고른 답. 모르는 값(UNKNOWN)·해당 없음은 버튼에 없다 */
export interface RestorationStatusAnswer {
  restoration_status: Extract<RestorationStatus, 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED'>
}

/**
 * 결과를 어떻게 받을지 서버가 정한다. 할 일 대부분은 [했어요 / 아직 안 했어요]로 받는다.
 * `RESTORATION_STATUS` 는 되물은 질문(원상복구 진행 상태)에만 온다
 */
export type ResultInputKind = 'TEXT' | 'RESTORATION_ANSWER' | 'ACTION_DONE' | 'RESTORATION_STATUS'

/**
 * [했어요] 버튼의 할 일 종류. 버튼 문구만 고르고, 무엇을 저장할지는 서버가 정한다.
 * 준비 확인 · 신고 제출 · 기관 처리 결과 확인 · 사장님이 직접 하는 일(철거·점포 반환·직원 정산)
 */
export type ActionDoneKind = 'PREPARATION' | 'SUBMISSION' | 'PROCESSING' | 'WORK'

/** 임대차계약서에 원상복구 조항이 있는지. 가입 때 사장님이 답한다 */
export type RestorationClause = 'EXISTS' | 'NOT_EXISTS' | 'UNKNOWN'

/**
 * `POST /cases` 로 보내는 것.
 *
 * 선택 항목은 모르면 `null` 로 보낸다. 빼먹거나 빈 문자열로 보내지 않는다 —
 * "아직 모른다"와 "없다"가 서버에서 같아진다.
 */
export interface CaseCreateRequest {
  /** 가게 이름. 진단에서 묻지 않아 지금은 늘 `null`. 서류 점검이 쓰는 값이다(아래 `CaseResponse`) */
  store_name: string | null
  business_type: string
  franchise_status: boolean
  employee_count: number | null
  has_business_loan: boolean | null
  /** 배달앱·카드단말기 등 해지할 계약 */
  has_service_contracts: boolean | null
  lease_status: LeaseStatus
  /** 계약서의 원상복구 조항. 서버가 `null`을 받지 않아 모르면 `UNKNOWN` */
  restoration_clause: RestorationClause
  /** `YYYY-MM-DD` */
  planned_closure_date: string | null
  /** 날짜를 못 정했을 때의 예상 달 `YYYY-MM`. 날짜와 같이 보내면 422 */
  planned_closure_month: string | null
  /** 지금이 아니라 "있었던 적". 지금 직원이 있으면 서버가 직원 수로 안다 */
  had_employees: boolean | null
  /** 이 사업장의 4대보험 가입 이력. 넷을 같이 보내야 "해당 없음"이 된다 */
  pension_enrolled: boolean | null
  health_insurance_enrolled: boolean | null
  employment_insurance_enrolled: boolean | null
  industrial_accident_insurance_enrolled: boolean | null
}

/**
 * `GET /cases` 안에 담겨 오는 Case. 서버 `CaseGetDetailResponse` 와 같다.
 *
 * 화면이 실제로 읽는 것은 여기까지다 — `adapters/case.ts` 가 이 모양만 보면 된다.
 */
export interface CaseResponse {
  id: number
  member_id: number
  /**
   * 가게 이름. 진단에서는 비워 두고, 서류 점검 직전에 사장님이 확인한 이름을 저장한다(#230).
   * 서류의 "공급받는 자"와 대조하며 신청인 이름과 구분한다.
   */
  store_name: string | null
  business_type: string
  franchise_status: boolean
  employee_count: number | null
  has_business_loan: boolean | null
  has_service_contracts: boolean | null
  lease_status: LeaseStatus
  restoration_clause: RestorationClause
  restoration_status: RestorationStatus
  restoration_scope: RestorationScope
  restoration_scope_detail: string | null
  demolition_required: DemolitionRequired
  /** `YYYY-MM-DD` */
  planned_closure_date: string | null
  /** 폐업 예상 달 `YYYY-MM`. 가입 때 "이번 달"·"다음 달"을 고르면 온다(#153) */
  planned_closure_month: string | null
  /** 부가세 신고를 체크하면 `COMPLETED`, 풀면 다시 `IN_PROGRESS`(#167) */
  case_status: CaseStatus
  /** `COMPLETED` 가 된 시각. 진행 중이면 `null`(#167) */
  completed_at: string | null
  /**
   * 통합 폐업 신고에 적을 값(#168 `PUT /cases/closure-report`). 저장 전에는 모두 `null` 이다.
   * 폐업일은 가입 때의 예상 달과 다른, 신고할 실제 날짜다. `YYYY-MM-DD`
   */
  closure_date: string | null
  closure_reason: ClosureReason | null
  road_address: string | null
  address_detail: string | null
  /** 보증금 돌려받았는지(#168 `PUT /cases/deposit-return`). 기록 전에는 `null` */
  deposit_return_result: DepositReturnResult | null
}

/**
 * `POST /cases` 응답. 조회 모양에 만든·바꾼 시각이 더 온다.
 *
 * 지금은 생성 직후 `/case` 로 옮겨 가며 다시 조회하므로 FE 가 읽는 값이 없다.
 * 그래도 모양은 적어둔다 — 서버가 무엇을 주는지가 이 파일의 일이다.
 *
 * 저장 전 칸(폐업 신고·보증금)은 가입 응답에는 없다. 그래서 조회 모양에서 빼고 시각을 더한다.
 */
export interface CaseCreateResponse
  extends Omit<
    CaseResponse,
    'closure_date' | 'closure_reason' | 'road_address' | 'address_detail' | 'deposit_return_result'
  > {
  created_at: string
  updated_at: string
}

/**
 * Agent 가 이 Case 를 어디까지 판단했는지.
 *
 *   PENDING          판단 중 — 잠시 후 다시 물어봐야 한다
 *   DONE             판단 완료
 *   NEEDS_MORE_INFO  서비스가 사장님에게 되물을 질문이 따로 온다
 *   CONFLICT         말한 내용이 기록과 어긋나 어느 쪽이 맞는지 여쭤봐야 한다
 *   FAILED           판단 실패 — 다시 시도 안내
 *
 * `CONFLICT` 는 사장님이 답해야 끝난다. 나머지 넷과 달리 **기다린다고 저절로 바뀌지
 * 않아서**, 화면이 다시 물어볼 이유도 없다(#66).
 *
 * 다섯이 다가 아닐 수 있다. 모르는 값이 오면 어댑터가 가려내고 화면은 "판단 내용을
 * 불러오지 못했어요" 로 간다 — 다른 상태로 바꿔 보여주지 않는다 (`CLAUDE.md` 규칙 9).
 */
export type JudgmentStatus = 'PENDING' | 'DONE' | 'NEEDS_MORE_INFO' | 'CONFLICT' | 'FAILED'

/**
 * 판단이 실패했을 때 서버가 분류한 **다음에 해볼 만한 것**.
 *
 * 네 값을 `#58` 에서 합의했고 BE·AI 양쪽 스키마가 같은 목록을 쓴다.
 *
 * **`RETRY` 를 "일시적인 문제" 로 읽으면 안 된다.** 판단이 결과를 내놓기도 전에 예외로
 * 끊기면 원인을 가리지 않고 전부 `RETRY` 로 저장된다(`decision_record.py` 의
 * `mark_judgment_failed`). 서버가 "다시 해볼 수는 있다" 고 분류했다는 뜻까지다.
 *
 * `JudgmentStatus` 와 마찬가지로 넷이 다가 아닐 수 있다. 모르는 값은 어댑터가 가려낸다.
 */
export type RecoveryActionCode = 'RETRY' | 'RESUBMIT_INPUT' | 'CONTACT_SUPPORT' | 'NONE'

/**
 * 다음 할 일.
 *
 * 전에는 제목 한 줄이었다. 제목만으로는 "임대인에게 확인하세요" 가 끝이라, 사장님이
 * 정작 **무슨 말을 꺼내야 할지** 모른다. 그래서 이유와 상대에게 물어볼 말까지 묶어
 * 보내기로 했다(#58).
 *
 * `sequence` 와 `evidence_refs` 는 빼기로 했다. 화면에 쓰는 자리가 없다 — 순번은
 * 할 일을 하나만 보여줘서 늘 1 이고, 근거를 펼쳐 보는 화면은 아직 없다.
 */
export interface NextActionResponse {
  title: string
  /** 왜 이걸 먼저 해야 하는지. 없으면 `null` 이다 */
  reason: string | null
  /**
   * 사장님이 **상대에게** 물을 말. 서비스가 사장님에게 되묻는 `questions_for_user` 와 다르다.
   *
   * 없어도 `null` 이 아니라 빈 목록으로 온다(#68).
   */
  questions_to_ask: string[]
}

/**
 * `GET /cases` 응답.
 *
 * Case 가 없으면 `case` 가 `null` 이다. 빈 객체 대신 이 모양을 쓰기로 한 것은,
 * TypeScript 에서 빈 객체가 거의 모든 값과 맞는다고 판단돼 가려낼 수 없기 때문이다.
 *
 * **Case 와 판단은 서로 다른 시점의 정보다.** `POST /cases` 가 저장만 하고 바로 응답한 뒤
 * 판단은 뒤에서 돌기 때문에, Case 는 있는데 판단은 아직 `PENDING` 인 구간이 반드시 생긴다.
 *
 * `blocker` 는 문자열 하나로 둔다. AI 가 주는 설명이 이미 완성된 문장이라, 제목을 따로
 * 만들면 같은 말을 두 번 쓰게 된다(#58).
 */
export interface CasesEnvelope {
  case: CaseResponse | null
  /** 지금 진행을 막고 있는 것. 제목 한 줄 */
  blocker: string | null
  next_action: NextActionResponse | null
  judgment_status: JudgmentStatus | null
  /** 서비스가 사장님에게 되묻는 질문. `next_action` 의 "물어볼 말"과 다른 것이다 */
  questions_for_user: string[] | null
  /** 판단이 실패했을 때만 채워진다. 실패가 아니면 `null` 이다 */
  recovery_action_code: RecoveryActionCode | null
  /** 판단이 실패했을 때만 채워진다. 실패하기 전 마지막으로 보여 준 할 일 제목. 예전 서버는 보내지 않는다 */
  last_next_action_title?: string | null
  /**
   * 판단을 멈추게 한 Case 의 칸 이름들. 실패가 아니면 `null` 이다.
   *
   * **`string[]` 으로 둔다.** AI 쪽은 아홉 칸짜리 닫힌 목록(`CaseFieldKey`)으로 보내지만,
   * BE 가 그 값을 검사 없이 JSON 칸에 담아 `list[str]` 로 돌려준다. 좁은 타입으로 적으면
   * 지켜지지 않는 약속을 타입이 지켜 주는 것처럼 보인다 — 거르는 일은 어댑터가 한다.
   */
  requested_field_paths: string[] | null
}

/**
 * 판단이 바꾼 Case 칸 하나. 재계획 결과의 "방금 반영된 내용" 이 된다.
 *
 * **값이 서버 쪽 표기 그대로 글자로 온다.** BE 가 원래 값을 파이썬 `str()` 로 적어서,
 * 선택값은 `"FULL"`, 예/아니오는 `"True"`, 숫자는 `"3"` 이다. 화면 말로 바꾸는 것은 어댑터가 한다.
 *
 * `null` 은 그 칸이 비어 있었다(또는 비워졌다)는 뜻이다.
 */
export interface FieldChangeResponse {
  /** 칸 이름. `requested_field_paths` 와 같은 어휘다 */
  field: string
  stored_value: string | null
  new_value: string | null
}

/**
 * 기록과 어긋나 사장님 확인을 기다리는 항목 하나.
 *
 * `id` 는 충돌 결정을 보낼 때 어느 항목에 대한 답인지 가리키는 번호다.
 *
 * `stored_value` 는 기록이 비어 있으면 `null` 이 아니라 **글자 `"UNKNOWN"`** 으로 온다.
 * BE 가 빈칸을 못 받는 자리에 적으면서 그렇게 바꾼다.
 */
export interface ConflictItemResponse {
  id: number
  field: string
  stored_value: string | null
  proposed_value: string
}

/**
 * `GET /cases/results` 응답. `/results` 에 들어올 때 부른다.
 *
 * 결과를 보낼 대상(`case_history_id`)과 지금 판단 상태를 함께 준다. 결과는 **가장 최근
 * 판단에 대해서만** 보낼 수 있어서, 이 번호 없이 보내면 서버가 409 로 돌려보낸다.
 *
 * 상태마다 채워지는 칸이 다르다. 안 쓰는 칸은 `null` 로 온다.
 *   DONE             case_history_id · next_action
 *   PENDING          case_history_id
 *   NEEDS_MORE_INFO  case_history_id · questions_for_user
 *   FAILED           case_history_id · recovery_action_code · requested_field_paths
 *   CONFLICT         raw_input · conflicts (번호는 없다 — 충돌을 먼저 풀어야 한다)
 */
export interface CaseResultsEntryResponse {
  judgment_status: JudgmentStatus
  result_input_kind: ResultInputKind
  /** `ACTION_DONE`일 때만 있다 */
  action_done_kind: ActionDoneKind | null
  case_history_id: number | null
  raw_input: string | null
  conflicts: ConflictItemResponse[] | null
  next_action: NextActionResponse | null
  questions_for_user: string[] | null
  recovery_action_code: RecoveryActionCode | null
  requested_field_paths: string[] | null
}

/** `POST /cases/results` 로 보내는 것 */
export type CaseResultsSubmitRequest = { case_history_id: number } & (
  | { raw_input: string; restoration_answer?: never; action_done?: never; restoration_status?: never }
  | { restoration_answer: RestorationAnswer; raw_input?: never; action_done?: never; restoration_status?: never }
  | (ActionDone & { raw_input?: never; restoration_answer?: never; restoration_status?: never })
  | (RestorationStatusAnswer & { raw_input?: never; restoration_answer?: never; action_done?: never })
)

/**
 * 충돌 하나에 고른 쪽. 서버 말로 `PROPOSED` 는 이번에 말씀하신 것, `STORED` 는 지금 기록이다.
 * 화면은 `INCOMING` 이라 부른다(`types/view.ts` `ConflictSide`) — 바꾸는 것은 어댑터가 한다
 */
export type ConflictDecisionSide = 'PROPOSED' | 'STORED'

/**
 * `POST /cases/results/decision` 으로 보내는 것.
 *
 * 남은 충돌을 **전부** 한 번에 보낸다. 하나라도 빠지거나 같은 충돌이 두 번 있으면 422 다.
 * 응답은 결과 제출과 같은 접수 번호(`CaseResultsSubmitAcceptedResponse`)이고, 결과도 같은
 * `GET /cases/results/status` 로 받는다.
 */
export interface CaseConflictsDecisionRequest {
  decisions: { conflict_reference_id: number; side: ConflictDecisionSide }[]
}

/**
 * `POST /cases/results` 응답. **접수 번호만 온다.**
 *
 * 판단은 뒤에서 돌고 몇 분이 걸릴 수 있어서, 결과는 이 번호로 따로 물어봐야 한다.
 */
export interface CaseResultsSubmitAcceptedResponse {
  case_history_id: number
}

/**
 * `POST /cases/retry` 의 응답(#196). 본문 없이 보낸다.
 *
 * 실패한 가입·서류 판단을 **새로 만들지 않고 되돌려** 다시 돌린다. 그래서 번호는 실패했던 그 판단의
 * 번호와 같다. 화면은 이 번호로 기다리지 않고 `GET /cases` 를 다시 불러 `PENDING` 을 본다.
 */
export interface CaseRetryResponse {
  case_history_id: number
}

/**
 * 보낸 결과를 판단한 상태.
 *
 *   PENDING          아직 판단 중 — 잠시 후 다시 물어봐야 한다
 *   UPDATED          Case 가 바뀌었고 다음 할 일을 다시 정했다
 *   NO_CHANGE        바뀐 것은 없고 다음 할 일도 그대로다
 *   NEEDS_MORE_INFO  정하려면 사장님께 더 여쭤봐야 한다
 *   CONFLICT         말씀이 기록과 어긋나 어느 쪽이 맞는지 확인해야 한다
 *   FAILED           판단 실패
 *
 * `JudgmentStatus` 와 마찬가지로 이것이 다가 아닐 수 있다. 모르는 값은 어댑터가 가려낸다.
 */
export type ResultsSubmitResult =
  | 'PENDING'
  | 'UPDATED'
  | 'NO_CHANGE'
  | 'NEEDS_MORE_INFO'
  | 'CONFLICT'
  | 'FAILED'

/**
 * `GET /cases/results/status?case_history_id=` 응답.
 *
 * 상태마다 채워지는 칸이 다르다. 안 쓰는 칸은 `null` 로 온다.
 *   UPDATED · NO_CHANGE  changes · blocker · next_action · new_tasks (NO_CHANGE 는 changes 가 빈 목록)
 *   NEEDS_MORE_INFO      questions_for_user
 *   CONFLICT             raw_input · conflicts
 *   FAILED               recovery_action_code · requested_field_paths
 *
 * `raw_input` 이 돌아오므로 충돌 화면에 보여줄 문장을 FE 가 따로 들고 다니지 않아도 된다.
 */
export interface CaseResultsSubmitResponse {
  result: ResultsSubmitResult
  changes: FieldChangeResponse[] | null
  /** 지금 진행을 막고 있는 것. 제목 한 줄 */
  blocker: string | null
  next_action: NextActionResponse | null
  questions_for_user: string[] | null
  raw_input: string | null
  conflicts: ConflictItemResponse[] | null
  recovery_action_code: RecoveryActionCode | null
  requested_field_paths: string[] | null
  /**
   * 이번 판단으로 해야 할 일이 된 로드맵 할 일(#182, 시안 "할 일 3개가 새로 생겼어요"). 로드맵 순서다.
   * 직전 판단과 비교할 수 없으면 `null`, 새로 생긴 게 없으면 빈 목록. `NO_CHANGE` 에도 온다 —
   * 그사이 알려 준 심사 결과로 할 일이 늘었을 수 있다(현석님 #182)
   */
  new_tasks: NewTaskResponse[] | null
}

/** 새로 생긴 할 일 하나. 번호는 로드맵 할 일 번호(`task_id`)와 같다 */
export interface NewTaskResponse {
  task_id: string
  title: string
}

/** 기록을 남긴 쪽. `OWNER` 사장님, `RIBBON` 리본 */
export type CaseLogActor = 'OWNER' | 'RIBBON'

/**
 * 기록 사건 코드(#143). 문구는 서버가 주지 않고 FE가 코드로 만든다.
 *
 *   사장님  CASE_CREATED · RESULT_SUBMITTED · CONFLICT_DECIDED · DOCUMENT_SUBMITTED(#173)
 *           CHECKLIST_COMPLETED · CHECKLIST_UNCHECKED · SUPPORT_RESULT_REPORTED · DOCUMENT_UPLOADED(#174)
 *   리본    NEXT_ACTION_DECIDED · MORE_INFO_REQUESTED · CONFLICT_FOUND · JUDGMENT_FAILED
 *           DOCUMENTS_CHECKED(#174) · ROADMAP_TASKS_ADDED(#184)
 */
export type CaseLogEvent =
  | 'CASE_CREATED'
  | 'RESULT_SUBMITTED'
  | 'CONFLICT_DECIDED'
  | 'CHECKLIST_COMPLETED'
  | 'CHECKLIST_UNCHECKED'
  | 'SUPPORT_RESULT_REPORTED'
  | 'NEXT_ACTION_DECIDED'
  | 'MORE_INFO_REQUESTED'
  | 'CONFLICT_FOUND'
  | 'JUDGMENT_FAILED'
  | 'ROADMAP_TASKS_ADDED'
  | 'DOCUMENT_UPLOADED'
  | 'DOCUMENTS_CHECKED'
  | 'DOCUMENT_SUBMITTED'

/** 기록 한 줄 */
export interface CaseLogItem {
  actor: CaseLogActor
  event: CaseLogEvent
  /** 한국 시각, 시간대(`+09:00`)가 붙어 온다 */
  occurred_at: string
  /** 체크 기록(`CHECKLIST_*`)일 때 어떤 항목인지. 그 밖에는 `null` */
  task_id: string | null
  /**
   * 문구에 쓸 값. `NEXT_ACTION_DECIDED` 는 정한 할 일 제목, `ROADMAP_TASKS_ADDED` 는 이번 판단으로
   * 새로 생긴 할 일 개수 글자(예: `"3"`, #184), `DOCUMENT_UPLOADED` 는 올린 서류 종류 코드(예: `TRANSFER`, #174),
   * `SUPPORT_RESULT_REPORTED` 는 `APPROVED` / `REJECTED` / `UNKNOWN`.
   * 그 밖에는 `null`
   */
  detail: string | null
}

/** `GET /cases/logs` 응답. 최근 것부터. Case 가 없으면 404 */
export interface CaseLogResponse {
  logs: CaseLogItem[]
}

/** `PUT /cases/checklists/{task_id}` 로 보내는 것. 같은 값을 두 번 보내도 결과는 같다 */
export interface CaseChecklistUpdateRequest {
  completed: boolean
}

/** 체크 저장 응답. 저장된 상태가 그대로 돌아온다. 할 일 상태(완료 등)는 로드맵이 다시 계산한다 */
export interface CaseChecklistResponse {
  task_id: string
  completed: boolean
}

/**
 * `PUT /cases/support-approval` 로 보내는 것. 점포철거비 1차 적격심사 결과를 사장님이 알려 준다.
 * `true` 승인 · `false` 안 됨 · `null` 아직 모름. **키는 꼭 보낸다** — 빠지면 422 다
 */
export interface CaseSupportApprovalRequest {
  approved: boolean | null
}

export interface CaseSupportApprovalResponse {
  approved: boolean | null
}

/** 로드맵 할 일 상태(AI 로드맵 `TaskStatus`). 이것이 다가 아닐 수 있어 모르는 값은 어댑터가 뺀다 */
export type RoadmapTaskStatusCode = 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED' | 'NOT_APPLICABLE' | 'NEEDS_CONFIRMATION'

/** 로드맵 할 일 종류. `CHECKLIST` 체크 항목 · `PROCEDURE` 공식 절차 · `DOCUMENT_CHECK` 서류 점검 · `CASE_FACT` 가게 정보 */
export type RoadmapTaskKindCode = 'CHECKLIST' | 'PROCEDURE' | 'DOCUMENT_CHECK' | 'CASE_FACT'

/**
 * 로드맵 할 일 한 줄. 서버는 이 밖에 절차 번호(`procedure_steps`)·설명 출처(`guidance_source`)도 주지만
 * 화면이 쓰지 않아 옮기지 않는다
 */
export interface RoadmapTaskResponse {
  /** 할 일 번호(`dispose_stock` 등). 체크 저장 `PUT /cases/checklists/{task_id}` 의 그 번호다 */
  task_id: string
  title: string
  kind: RoadmapTaskKindCode
  status: RoadmapTaskStatusCode
  /** 검수한 설명. 없으면 `null` */
  guidance: string | null
}

export interface RoadmapStageResponse {
  /** 단계 번호 1~5 */
  stage: number
  title: string
  tasks: RoadmapTaskResponse[]
}

/**
 * `GET /cases/roadmap` 응답(#178). AI 로드맵(`app/agent/roadmap.py` `Roadmap`)을 그대로 내보낸다.
 * 화면이 쓰는 칸만 옮겼다(Case 번호·스냅샷 번호·`next_action` 등은 쓰지 않는다 — 오늘 할 일은 `GET /cases` 가 맡는다).
 *
 * 미지원 업종이면 `supported` 가 `false` 이고 `unsupported_reason` 에 안내 문구, 단계는 빈 목록이다.
 * `current_stage` 는 해야 할 일이 남은 가장 앞 단계(#179). 폐업 정리를 마쳤거나 미지원이면 `null`.
 * Case 가 없으면 404 다.
 */
export interface RoadmapResponse {
  supported: boolean
  unsupported_reason: string | null
  stages: RoadmapStageResponse[]
  current_stage: number | null
}

/** 폐업 사유. `BUSINESS_SLUMP` 사업 부진 · `PERSONAL` 개인 사정 · `OTHER` 기타 */
export type ClosureReason = 'BUSINESS_SLUMP' | 'PERSONAL' | 'OTHER'

/**
 * `PUT /cases/closure-report` 로 보내는 것(#168). 통합 폐업 신고의 "폐업 정보 · 가게 주소" 두 장을 한 번에.
 *
 * 다시 보내면 덮어쓴다. AI 판단에는 넘어가지 않는다(신고 요약에 보여주는 값). 가입 때 받은 예상일
 * (`planned_closure_date`)과 다른 칸이다 — 이쪽은 신고할 **실제 폐업일**이다.
 */
export interface CaseClosureReportRequest {
  /** `YYYY-MM-DD` */
  closure_date: string
  closure_reason: ClosureReason
  /** 도로명 주소. 1~200자 */
  road_address: string
  /** 상세 주소. 100자까지, 없으면 `null` */
  address_detail: string | null
}

export type CaseClosureReportResponse = CaseClosureReportRequest

/** 보증금을 돌려받았는지. `FULL` 다 받음 · `PARTIAL` 일부 빼고 받음 · `NONE` 아직 못 받음 */
export type DepositReturnResult = 'FULL' | 'PARTIAL' | 'NONE'

/** `PUT /cases/deposit-return` 로 보내는 것과 그 응답(#168) */
export interface CaseDepositReturnRequest {
  result: DepositReturnResult
}

export type CaseDepositReturnResponse = CaseDepositReturnRequest

/** 서류 종류(#128 문서 Tool `DocumentKind`). `UNKNOWN` 은 종류를 모르는 서류 */
export type DocumentKind =
  | 'LEASE'
  | 'BUSINESS_REGISTRATION'
  | 'BUSINESS_LICENSE'
  | 'CONSTRUCTION_STATEMENT'
  | 'TAX_INVOICE'
  | 'BEFORE_PHOTO'
  | 'AFTER_PHOTO'
  | 'TRANSFER'
  | 'CLOSURE_CERTIFICATE'
  | 'BANK_COPY'
  | 'CLOSURE_RECEIPT'
  | 'CARD_SALES'
  | 'CASH_SALES'
  | 'PURCHASE_INVOICE'
  | 'DEPOSIT_STATEMENT'
  | 'UNKNOWN'

/** 서류에서 꺼낸 값 이름(#128 `DocumentFieldName`) */
export type DocumentFieldName =
  | 'business_name'
  | 'supplier'
  | 'buyer'
  | 'sender'
  | 'recipient'
  | 'account_holder'
  | 'amount'
  | 'supply_amount'
  | 'tax_amount'
  | 'date'
  | 'closure_date'
  | 'restoration_clause'

/** 서류 한 장(#159). 종류 이름·확인 필요 여부는 서버가 정해서 준다 */
export interface DocumentResponse {
  document_id: string
  filename: string
  kind: DocumentKind
  kind_label: string
  /** 종류를 모르거나 사진·글자 인식처럼 확신하지 못한 서류. 사장님이 확인해야 점검이 끝난다 */
  needs_confirmation: boolean
  fields: { name: DocumentFieldName; label: string; value: string; page: number }[]
  /** 사장님이 확인한 값. 확인 전이면 `null` */
  confirmed_fields: Partial<Record<DocumentFieldName, string>> | null
}

/**
 * 정산 서류 점검 결과(#159).
 *
 * 서버와 문서 Tool이 같은 상태 세 가지를 사용한다.
 */
export interface DocumentCheckResponse {
  status: 'COMPLETE' | 'ISSUES' | 'ERROR'
  steps: { name: string; status: 'WAITING' | 'RUNNING' | 'DONE' | 'NEEDS_CONFIRMATION' | 'ERROR' }[]
  issues: { code: string; document_ids: string[]; message: string }[]
  checked_at: string
}

/**
 * 서류 목록(`GET /cases/documents`). 올리기·확인·빼기·점검도 모두 이 모양을 돌려준다.
 * 서류를 더하거나 빼거나 확인하면 지난 점검은 지워진다(`check: null`).
 */
export interface DocumentListResponse {
  /** 사장님이 확인해 Case에 저장한 가게 이름. 서류에서 읽은 값과 구분한다 */
  store_name: string | null
  /** 확인 화면에서 고를 수 있는 종류와 이름. UNKNOWN은 선택 목록에 포함하지 않는다 */
  document_kinds: { kind: DocumentKind; label: string }[]
  documents: DocumentResponse[]
  check: DocumentCheckResponse | null
}

/** `POST /cases/documents/{id}/confirm` — 사장님이 확인한 종류와 값 전부 */
export interface DocumentConfirmRequest {
  kind: DocumentKind
  confirmed_fields: Partial<Record<DocumentFieldName, string>>
}

/**
 * `POST /cases/documents/check`. 이름은 이체확인증의 보낸 사람과, 폐업일은 폐업사실증명원과 맞춰 본다.
 * 폐업일을 비우면 예정일로 대신하지 않고 "폐업일 미확인"으로 점검이 끝나지 않는다
 */
export interface DocumentCheckRequest {
  /** 1~50자. 이미 저장한 이름이 있는 구형 호출자는 생략할 수 있다 */
  store_name?: string | null
  /** 1~50자 */
  applicant_name: string
  /** `YYYY-MM-DD` */
  closure_date: string | null
}
