import type { CaseRetryResponse } from '../types/api'
import { ApiError, request } from './api'

/**
 * 실패한 판단을 다시 돌려 달라고 한다(`POST /cases/retry`, #196). 다시 돌린 판단 번호를 돌려준다.
 *
 * 무엇을 다시 돌릴지는 서버가 로그인한 사람의 최신 판단을 보고 정한다. 그래서 보내는 것이 없다.
 * 서버가 받는 것은 가입·서류 판단이 `RETRY` 로 실패한 경우뿐이고, 그 밖은 409 다.
 *
 * 실패 응답은 `ApiError`(401 은 `UnauthorizedError`)로 올라간다 — 409 다시 돌릴 판단이 없음,
 * 404 Case 없음. 무엇을 할지는 부르는 화면이 정한다.
 */
export async function retryJudgment(): Promise<number> {
  const response = await request('/cases/retry', { method: 'POST' })
  const accepted = (await response.json()) as Partial<CaseRetryResponse>

  // 받았다는 답인데 번호가 없으면 정말 다시 돌았는지 알 수 없다
  if (!Number.isInteger(accepted.case_history_id)) {
    throw new ApiError(response.status, '다시 판단한 번호를 읽지 못했습니다.')
  }
  return accepted.case_history_id as number
}
