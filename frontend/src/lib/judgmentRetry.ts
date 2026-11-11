import type { CaseRetryResponse } from '../types/api'
import { ApiError, request } from './api'

/**
 * 실패한 판단을 다시 돌려 달라고 한다(`POST /cases/retry`, #196). 다시 돌린 판단 번호를 돌려준다.
 *
 * 무엇을 다시 돌릴지는 서버가 로그인한 사람의 최신 판단을 보고 정한다. 그래서 보내는 것이 없다.
 * 서버가 받는 것은 가입·결과 알려주기·서류 판단이 `RETRY` 로 실패한 경우이고(#196), 그 밖은 409 다.
 * 충돌 선택 실패는 고른 값이 저장되지 않아 받지 않는다(#108). 그때는 충돌이 남아 홈이 확인 화면으로 보낸다.
 *
 * 실패 응답은 `ApiError`(401 은 `UnauthorizedError`)로 올라간다 — 409 다시 돌릴 판단이 없음,
 * 404 Case 없음. 무엇을 할지는 부르는 화면이 정한다.
 */
export async function retryJudgment(): Promise<number> {
  const response = await request('/cases/retry', { method: 'POST' })
  const accepted = ((await response.json()) ?? {}) as Partial<CaseRetryResponse>

  // 받았다는 답인데 번호가 없으면(본문이 null 이어도) 정말 다시 돌았는지 알 수 없다
  if (!Number.isInteger(accepted.case_history_id)) {
    throw new ApiError(response.status, '다시 판단한 번호를 읽지 못했습니다.')
  }
  return accepted.case_history_id as number
}
