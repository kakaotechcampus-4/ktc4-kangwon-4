import type {
  CaseResultsEntryResponse,
  CaseResultsSubmitAcceptedResponse,
  CaseResultsSubmitRequest,
  CaseResultsSubmitResponse,
} from '../types/api'
import { ApiError, request, UnauthorizedError } from './api'

/**
 * 결과 제출 흐름의 서버 호출. 한 바퀴에 세 번 부른다.
 *
 *   들어올 때   GET  /cases/results          지금 판단 상태와 결과를 보낼 판단 번호
 *   보낼 때     POST /cases/results          접수 번호만 돌려준다
 *   기다릴 때   GET  /cases/results/status   판단이 끝날 때까지 다시 묻는다
 *
 * 응답을 화면 모양으로 바꾸지 않고 서버 모양 그대로 돌려준다. 바꾸는 것은 어댑터
 * (`adapters/results.ts`)가 하고, 여기는 부르고 기다리는 것만 한다.
 */

/**
 * 판단이 끝났는지 다시 묻는 간격. `useCase` 와 같은 값이다.
 *
 * 결과를 보낸 뒤의 판단도 `/case` 의 판단과 같은 AI 가 돌린다(실측 36~120초, BE #47).
 */
const POLL_INTERVAL_MS = 10_000

/**
 * 기다리는 상한. `useCase` 와 같은 값이고 이유도 같다 — 판단 도중 서버가 다시 뜨면
 * 그 제출은 계속 `PENDING` 으로 남는다(#40). 상한이 없으면 화면이 영영 기다린다.
 */
const POLL_TIMEOUT_MS = 10 * 60 * 1000

/** `/results` 에 들어올 때. 404 는 Case 가 없다는 뜻이고 `ApiError` 로 올라간다 */
export async function fetchResultsEntry(): Promise<CaseResultsEntryResponse | null> {
  const response = await request('/cases/results')
  // 본문이 `null` 일 수 있다고 타입에 드러낸다. 어댑터가 그 경우를 빠뜨리면 컴파일에서 막힌다
  return (await response.json()) as CaseResultsEntryResponse | null
}

/**
 * 결과를 보내고 접수 번호를 받는다.
 *
 * 409 는 지금 받을 수 없다는 뜻이다 — 확인을 기다리는 충돌이 있거나, 직전 제출이 아직
 * 판단 중이거나, 그사이 더 새로운 판단이 생겼다. 셋 다 화면이 아는 상황이 낡은 것이라
 * 구분하지 않고 `ApiError` 그대로 올린다.
 */
export async function submitResult(historyId: number, rawInput: string): Promise<number> {
  const body: CaseResultsSubmitRequest = { raw_input: rawInput, case_history_id: historyId }
  const response = await request('/cases/results', { method: 'POST', body })
  const accepted = (await response.json()) as Partial<CaseResultsSubmitAcceptedResponse>

  // 접수는 됐는데 번호가 없으면 결과를 물어볼 수 없다. 받았다고 넘기면 화면이
  // 끝나지 않는 대기에 들어간다
  if (!Number.isInteger(accepted.case_history_id)) {
    throw new ApiError(response.status, '접수 번호를 읽지 못했습니다.')
  }
  return accepted.case_history_id as number
}

/** 기다린 끝에 얻은 것 */
export type WaitResult =
  /** 판단이 끝났다. `PENDING` 이 아닌 응답이 그대로 담긴다 */
  | { kind: 'SETTLED'; body: CaseResultsSubmitResponse }
  /**
   * 이 제출을 더 물어볼 수 없다 — 그사이 더 새로운 제출이 생겼거나(409),
   * 제출 기록이 없다(404). 다른 탭에서 보냈을 때 이렇게 된다.
   */
  | { kind: 'STALE' }
  /** 상한까지 기다렸는데 아직 판단 중이다 */
  | { kind: 'WAITED_TOO_LONG' }

/** `ms` 만큼 기다린다. 중간에 `signal` 이 끊기면 그 이유로 실패한다 */
function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason)

    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)

    function onAbort() {
      clearTimeout(timer)
      reject(signal.reason)
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

/**
 * 판단이 끝날 때까지 기다린다.
 *
 * **처음 묻기 전에도 한 간격을 쉰다.** 방금 접수했으니 판단이 끝났을 리 없다.
 *
 * 한 번 묻다 실패해도 **멈추지 않고 다음 간격에 다시 묻는다** — 네트워크가 잠깐 끊기거나
 * 서버가 5xx 를 한 번 내는 것으로 끝내면, 판단은 멀쩡히 끝나 있는데 사장님만 실패를 본다.
 * 다시 물어도 답이 같을 것만 바로 끝낸다:
 *   401        로그인이 풀렸다. 그대로 던진다
 *   404·409    이 제출을 더 물어볼 수 없다. `STALE`
 *   그 밖 4xx  요청이 잘못됐다. 그대로 던진다
 *
 * `signal` 이 끊기면(화면을 떠나면) 기다리던 것을 멈추고 그 이유로 실패한다. 떠난 화면이
 * 몇 초 뒤 결과를 받아 사장님을 다른 화면으로 끌고 가면 안 된다.
 *
 * **상한은 물어본 뒤에 본다.** 쉬고 나서 바로 보면 상한에 닿는 마지막 차례에는 묻지 않고
 * 끝나, 그사이 끝난 판단을 두고 "오래 걸린다" 고 하게 된다.
 */
export async function waitForResult(
  historyId: number,
  { signal }: { signal: AbortSignal },
): Promise<WaitResult> {
  const startedAt = Date.now()

  for (;;) {
    await sleep(POLL_INTERVAL_MS, signal)

    // `undefined` 는 이번에 답을 못 받았다는 뜻이다. 본문이 `null` 인 답과 구분한다
    let body: CaseResultsSubmitResponse | undefined
    try {
      const response = await request(`/cases/results/status?case_history_id=${historyId}`)
      body = (await response.json()) as CaseResultsSubmitResponse
    } catch (error: unknown) {
      if (signal.aborted) throw signal.reason
      if (error instanceof UnauthorizedError) throw error
      if (error instanceof ApiError && (error.status === 404 || error.status === 409)) return { kind: 'STALE' }
      if (error instanceof ApiError && error.status < 500) throw error
      // 네트워크 실패·시간 초과·5xx·본문이 JSON 이 아님. 다음 간격에 다시 묻는다
    }

    // 요청이 나가 있는 사이 화면을 떠났다
    if (signal.aborted) throw signal.reason
    if (body !== undefined && body?.result !== 'PENDING') return { kind: 'SETTLED', body }
    if (Date.now() - startedAt >= POLL_TIMEOUT_MS) return { kind: 'WAITED_TOO_LONG' }
  }
}
