import type {
  CaseChecklistResponse,
  CaseChecklistUpdateRequest,
  CaseClosureReportRequest,
  CaseClosureReportResponse,
  CaseDepositReturnRequest,
  CaseDepositReturnResponse,
  CaseSupportApprovalRequest,
  CaseSupportApprovalResponse,
  DepositReturnResult,
} from '../types/api'
import { ApiError, request } from './api'

/**
 * 로드맵 할 일에서 사장님이 직접 남기는 것(#149). 둘 다 저장된 값을 돌려준다.
 *
 * 화면은 저장이 끝난 뒤에야 체크·결과를 바꿔 보여준다(FE 규칙 2). 할 일 상태(완료 등)는 로드맵이
 * 저장된 체크·결과로 다시 계산하므로, 응답으로 할 일을 "완료"로 칠하지 않는다(승준님 #149).
 *
 * 실패 응답은 `ApiError`(401 은 `UnauthorizedError`)로 올라간다 — 404 Case 없음, 422 체크할 수 없는 항목.
 */

/** 체크하거나 푼다. 저장된 상태를 돌려준다 */
export async function saveChecklist(taskId: string, completed: boolean): Promise<boolean> {
  const body: CaseChecklistUpdateRequest = { completed }
  const response = await request(`/cases/checklists/${encodeURIComponent(taskId)}`, { method: 'PUT', body })
  const saved = (await response.json()) as Partial<CaseChecklistResponse>

  // 저장은 됐는데 무엇이 저장됐는지 모르면 화면이 짐작해 그리게 된다
  if (typeof saved.completed !== 'boolean') throw new ApiError(response.status, '저장된 체크를 읽지 못했습니다.')
  return saved.completed
}

/** 철거비 1차 적격심사 결과를 남긴다. 저장된 값을 돌려준다 */
export async function saveSupportApproval(approved: boolean | null): Promise<boolean | null> {
  const body: CaseSupportApprovalRequest = { approved }
  const response = await request('/cases/support-approval', { method: 'PUT', body })
  const saved = (await response.json()) as Partial<CaseSupportApprovalResponse>

  if (saved.approved !== null && typeof saved.approved !== 'boolean') {
    throw new ApiError(response.status, '저장된 심사 결과를 읽지 못했습니다.')
  }
  return saved.approved
}

/** 통합 폐업 신고 정보(폐업일 · 사유 · 주소)를 저장한다(#168). 저장된 값을 돌려준다 */
export async function saveClosureReport(body: CaseClosureReportRequest): Promise<CaseClosureReportResponse> {
  const response = await request('/cases/closure-report', { method: 'PUT', body })
  const saved = (await response.json()) as Partial<CaseClosureReportResponse>

  if (typeof saved.closure_date !== 'string' || typeof saved.road_address !== 'string' || !saved.closure_reason) {
    throw new ApiError(response.status, '저장된 신고 정보를 읽지 못했습니다.')
  }
  return saved as CaseClosureReportResponse
}

/** 보증금을 돌려받았는지 저장한다(#168). 저장된 값을 돌려준다 */
export async function saveDepositReturn(result: DepositReturnResult): Promise<DepositReturnResult> {
  const body: CaseDepositReturnRequest = { result }
  const response = await request('/cases/deposit-return', { method: 'PUT', body })
  const saved = (await response.json()) as Partial<CaseDepositReturnResponse>

  if (saved.result !== 'FULL' && saved.result !== 'PARTIAL' && saved.result !== 'NONE') {
    throw new ApiError(response.status, '저장된 보증금 결과를 읽지 못했습니다.')
  }
  return saved.result
}
