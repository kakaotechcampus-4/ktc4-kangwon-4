import type {
  CaseConflictsDecisionRequest,
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
 *               POST /cases/results/decision 충돌 확인에서는 글 대신 고른 쪽을 보낸다
 *   기다릴 때   GET  /cases/results/status   판단이 끝날 때까지 다시 묻는다
 *
 * 응답을 화면 모양으로 바꾸지 않고 서버 모양 그대로 돌려준다. 바꾸는 것은 어댑터
 * (`adapters/results.ts`)가 하고, 여기는 부르고 기다리는 것만 한다.
 */

/**
 * 결과로 보내는 글(`raw_input`)의 최대 글자 수. BE가 같은 숫자로 넘는 글을 422로 거절한다(11/04 현석님 제안,
 * 승준님 동의). 되물은 질문에 답할 때는 질문을 붙여 묶은 **보내는 글 전체**로 센다.
 *
 * 브라우저는 이모지 하나를 2자로 세고 서버(파이썬)는 1자로 세서, FE가 더 엄격하다. FE를 통과한 글이
 * 서버에서 걸리지는 않는다.
 */
export const MAX_RESULT_LENGTH = 2_000

/** 이만큼 넘게 적으면 남은 글자를 보여준다. 그 전에는 숫자를 띄우지 않는다 — 평소 답은 수십 자다 */
export const RESULT_LENGTH_HINT_FROM = 1_800

/** 완료된 결과를 더 빨리 반영하려고 3초마다 확인한다. `useCase` 와 같은 간격이다. */
const POLL_INTERVAL_MS = 3_000

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
  return readAcceptedId(await request('/cases/results', { method: 'POST', body }))
}

/**
 * 충돌마다 고른 쪽을 보내고 접수 번호를 받는다. 결과는 결과 제출과 같은 길로 기다린다.
 *
 * 409 는 결정을 받을 수 없다는 뜻이다 — 남은 충돌이 없거나, 직전 결정이 아직 판단 중이거나,
 * 그사이 이미 해결됐다. 422 는 화면이 요청을 잘못 만든 것이다(덜 고름·중복). 어느 쪽인지
 * 가르는 것은 화면 몫이라 `ApiError` 그대로 올린다.
 */
export async function submitDecision(body: CaseConflictsDecisionRequest): Promise<number> {
  return readAcceptedId(await request('/cases/results/decision', { method: 'POST', body }))
}

/**
 * 접수 응답에서 번호를 꺼낸다.
 *
 * 접수는 됐는데 번호가 없으면 결과를 물어볼 수 없다. 받았다고 넘기면 화면이 끝나지 않는
 * 대기에 들어간다.
 */
async function readAcceptedId(response: Response): Promise<number> {
  const accepted = (await response.json()) as Partial<CaseResultsSubmitAcceptedResponse>
  if (!Number.isInteger(accepted.case_history_id)) {
    throw new ApiError(response.status, '접수 번호를 읽지 못했습니다.')
  }
  return accepted.case_history_id as number
}

/**
 * 판단 번호 하나의 결과를 한 번 묻는다.
 *
 * 기다릴 때(`waitForResult`)와 반영 결과 화면(`/replan?history=`)이 같이 쓴다. 401 은
 * `UnauthorizedError`, 그 밖의 실패 응답은 `ApiError` 로 올라간다 — 404 는 그 번호가 없다는 것,
 * 409 는 그 번호 뒤로 새 판단이 생겼다는 것이다.
 */
export async function fetchResultStatus(historyId: number): Promise<CaseResultsSubmitResponse | null> {
  const response = await request(`/cases/results/status?case_history_id=${historyId}`)
  return (await response.json()) as CaseResultsSubmitResponse | null
}

/** 기다린 끝에 얻은 것 */
export type WaitResult =
  /** 판단이 끝났다. `PENDING` 이 아닌 응답이 그대로 담긴다 */
  | { kind: 'SETTLED'; body: CaseResultsSubmitResponse | null }
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
    let body: CaseResultsSubmitResponse | null | undefined
    try {
      body = await fetchResultStatus(historyId)
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
