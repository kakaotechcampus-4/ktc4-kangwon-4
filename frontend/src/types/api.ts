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

/** Case 한 건. `POST /cases` 응답과 `GET /cases` 안에 담겨 온다 */
export interface CaseResponse {
  id: number
  member_id: number
  business_type: string
  franchise_status: boolean
  employee_count: number | null
  case_status: CaseStatus
  lease_status: LeaseStatus
  restoration_status: RestorationStatus
  restoration_scope: RestorationScope
  restoration_scope_detail: string | null
  demolition_required: DemolitionRequired
  /** `YYYY-MM-DD` */
  planned_closure_date: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

/**
 * `GET /cases` 응답.
 *
 * Case 가 없으면 `case` 가 `null` 이다. 빈 객체 대신 이 모양을 쓰기로 한 것은,
 * TypeScript 에서 빈 객체가 거의 모든 값과 맞는다고 판단돼 가려낼 수 없기 때문이다.
 *
 * TODO(API): 같은 응답에 `blocker` 와 `next_action` 이 실릴 예정이다(BE #39).
 * 모양이 확정되면 여기 추가한다 — 지금 미리 열어두면 비어 있어도 그냥 넘어간다.
 */
export interface CasesEnvelope {
  case: CaseResponse | null
}
