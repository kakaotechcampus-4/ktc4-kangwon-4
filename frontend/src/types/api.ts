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

/**
 * `POST /cases` 로 보내는 것.
 *
 * 선택 항목은 모르면 `null` 로 보낸다. 빼먹거나 빈 문자열로 보내지 않는다 —
 * "아직 모른다"와 "없다"가 서버에서 같아진다.
 */
export interface CaseCreateRequest {
  business_type: string
  franchise_status: boolean
  employee_count: number | null
  lease_status: LeaseStatus
  /** `YYYY-MM-DD` */
  planned_closure_date: string | null
}

/**
 * Case 를 이루는 값들. 두 응답이 공통으로 담는 부분이다.
 *
 * 화면이 실제로 읽는 것은 여기까지다 — `adapters/case.ts` 가 이 모양만 보면 된다.
 */
interface CaseFields {
  id: number
  member_id: number
  business_type: string
  franchise_status: boolean
  employee_count: number | null
  lease_status: LeaseStatus
  restoration_status: RestorationStatus
  restoration_scope: RestorationScope
  restoration_scope_detail: string | null
  demolition_required: DemolitionRequired
  /** `YYYY-MM-DD` */
  planned_closure_date: string | null
}

/**
 * `GET /cases` 안에 담겨 오는 Case.
 *
 * 서버가 조회용과 생성용 응답을 나눴다. 조회 쪽에는 진행 상태와 시각이 빠져 있다.
 * 하나로 합쳐두면 실제로는 안 오는 필드를 있는 것처럼 적게 되고, 그 필드를 쓰는
 * 코드가 생기면 `undefined` 를 값으로 다루게 된다.
 */
export type CaseResponse = CaseFields

/**
 * `POST /cases` 응답. 조회보다 네 개가 더 온다.
 *
 * 지금은 생성 직후 `/case` 로 옮겨 가며 다시 조회하므로 FE 가 읽는 값이 없다.
 * 그래도 모양은 적어둔다 — 서버가 무엇을 주는지가 이 파일의 일이다.
 */
export interface CaseCreateResponse extends CaseFields {
  case_status: CaseStatus
  completed_at: string | null
  created_at: string
  updated_at: string
}

/**
 * Agent 가 이 Case 를 어디까지 판단했는지.
 *
 *   PENDING          판단 중 — 잠시 후 다시 물어봐야 한다
 *   DONE             판단 완료
 *   NEEDS_MORE_INFO  물어볼 질문이 따로 온다
 *   FAILED           판단 실패 — 다시 시도 안내
 *
 * BE 가 `CONFLICT` 추가를 건의했지만 아직 확정되지 않아 넣지 않는다. 모르는 값이 오면
 * 어댑터가 가려내고 화면은 "판단 내용을 불러오지 못했어요" 로 간다 (`CLAUDE.md` 규칙 9).
 */
export type JudgmentStatus = 'PENDING' | 'DONE' | 'NEEDS_MORE_INFO' | 'FAILED'

/**
 * `GET /cases` 응답.
 *
 * Case 가 없으면 `case` 가 `null` 이다. 빈 객체 대신 이 모양을 쓰기로 한 것은,
 * TypeScript 에서 빈 객체가 거의 모든 값과 맞는다고 판단돼 가려낼 수 없기 때문이다.
 *
 * **Case 와 판단은 서로 다른 시점의 정보다.** `POST /cases` 가 저장만 하고 바로 응답한 뒤
 * 판단은 뒤에서 돌기 때문에, Case 는 있는데 판단은 아직 `PENDING` 인 구간이 반드시 생긴다.
 *
 * `blocker` 와 `next_action` 은 문자열 하나씩이다. 서버가 제목만 꺼내 보내고 있어서
 * "왜 이걸 먼저 해야 하는지"와 "상대에게 물어볼 말"은 아직 오지 않는다 — DB 에는 들어
 * 있고 BE 가 내려주기로 했다(#44). 그때까지 화면은 제목만으로 성립해야 한다.
 */
export interface CasesEnvelope {
  case: CaseResponse | null
  /** 지금 진행을 막고 있는 것. 제목 한 줄 */
  blocker: string | null
  /** 다음 할 일의 제목. 이유와 질문 목록은 아직 없다 */
  next_action: string | null
  judgment_status: JudgmentStatus | null
  /** 서비스가 사장님에게 되묻는 질문. `next_action` 의 "물어볼 말"과 다른 것이다 */
  questions_for_user: string[] | null
}
