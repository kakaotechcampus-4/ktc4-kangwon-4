import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CaseResultsSubmitResponse } from '../types/api'
import { ApiError, UnauthorizedError } from './api'
import { fetchResultsEntry, submitResult, waitForResult } from './resultSubmit'

const INTERVAL_MS = 10_000
const TIMEOUT_MS = 10 * 60 * 1000

function json(body: unknown, status = 200) {
  return () => new Response(JSON.stringify(body), { status })
}

function status(code: number) {
  return () => new Response(null, { status: code })
}

/** 네트워크가 끊겼을 때 `fetch` 가 던지는 것 */
function offline() {
  return () => {
    throw new TypeError('Failed to fetch')
  }
}

/** 부를 때마다 다음 답을 준다. 목록이 끝나면 마지막 답을 계속 준다 */
function mockFetchSequence(...answers: (() => Response)[]) {
  let call = 0
  const fetchMock = vi.fn().mockImplementation(async () => {
    const answer = answers[Math.min(call, answers.length - 1)]
    call += 1
    return answer()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** 판단 결과 응답. 칸은 모두 비워 두고 필요한 것만 채운다 */
function result(overrides: Partial<CaseResultsSubmitResponse>): CaseResultsSubmitResponse {
  return {
    result: 'PENDING',
    changes: null,
    blocker: null,
    next_action: null,
    questions_for_user: null,
    raw_input: null,
    conflicts: null,
    recovery_action_code: null,
    requested_field_paths: null,
    ...overrides,
  }
}

const PENDING = json(result({ result: 'PENDING' }))
const UPDATED = result({ result: 'UPDATED', changes: [], blocker: '원상복구 범위 미확인' })

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('fetchResultsEntry', () => {
  it('들어올 때 지금 판단 상태를 묻는다', async () => {
    const fetchMock = mockFetchSequence(json({ judgment_status: 'DONE', case_history_id: 12 }))

    await expect(fetchResultsEntry()).resolves.toMatchObject({ case_history_id: 12 })
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/results$/)
  })
})

describe('submitResult', () => {
  it('적은 글과 판단 번호를 보내고 접수 번호를 받는다', async () => {
    const fetchMock = mockFetchSequence(json({ case_history_id: 13 }))

    await expect(submitResult(12, '임대인이 전체 철거래요')).resolves.toBe(13)

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({
      raw_input: '임대인이 전체 철거래요',
      case_history_id: 12,
    })
  })

  /** 번호 없이 넘기면 화면이 물어볼 것이 없는 대기에 들어간다 */
  it('접수 번호가 없으면 실패로 끊는다', async () => {
    mockFetchSequence(json({}))

    await expect(submitResult(12, '철거래요')).rejects.toBeInstanceOf(ApiError)
  })

  /** 어떤 409 인지 가르는 것은 화면 몫이 아니다. 상태 코드를 그대로 넘긴다 */
  it('지금 받을 수 없다는 답은 상태 코드째 올린다', async () => {
    mockFetchSequence(status(409))

    await expect(submitResult(12, '철거래요')).rejects.toMatchObject({ status: 409 })
  })
})

/**
 * 기다리는 동안 무엇을 버티고 무엇에서 멈추는지.
 *
 * 한 번 실패로 끝내면 판단은 끝나 있는데 사장님만 실패를 본다. 반대로 끝까지 버티면
 * 다시 물어도 소용없는 상황에서 10분을 붙잡힌다.
 */
describe('waitForResult', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('판단 중이면 다시 묻고, 끝나면 그 응답을 돌려준다', async () => {
    const fetchMock = mockFetchSequence(PENDING, PENDING, json(UPDATED))
    const waiting = waitForResult(13, { signal: new AbortController().signal })

    await vi.advanceTimersByTimeAsync(INTERVAL_MS * 3)

    await expect(waiting).resolves.toEqual({ kind: 'SETTLED', body: UPDATED })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/cases\/results\/status\?case_history_id=13$/)
  })

  /** 방금 접수했으니 끝났을 리 없다. 곧바로 물으면 요청 하나를 버린다 */
  it('처음 묻기 전에 한 간격을 쉰다', async () => {
    const fetchMock = mockFetchSequence(json(UPDATED))
    void waitForResult(13, { signal: new AbortController().signal })

    await vi.advanceTimersByTimeAsync(INTERVAL_MS - 1)
    expect(fetchMock).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['네트워크가 끊겨도', offline()],
    ['서버가 500 을 내도', status(500)],
    ['본문이 JSON 이 아니어도', () => new Response('<html>', { status: 200 })],
  ])('%s 다음 간격에 다시 묻는다', async (_, failure) => {
    mockFetchSequence(failure, json(UPDATED))
    const waiting = waitForResult(13, { signal: new AbortController().signal })

    await vi.advanceTimersByTimeAsync(INTERVAL_MS * 2)

    await expect(waiting).resolves.toEqual({ kind: 'SETTLED', body: UPDATED })
  })

  /** 다른 탭에서 새로 보냈거나 제출 기록이 없다. 다시 물어도 답이 같다 */
  it.each([409, 404])('%i 이면 더 묻지 않고 상황이 바뀐 것으로 둔다', async (code) => {
    const fetchMock = mockFetchSequence(status(code))
    const waiting = waitForResult(13, { signal: new AbortController().signal })

    await vi.advanceTimersByTimeAsync(INTERVAL_MS * 3)

    await expect(waiting).resolves.toEqual({ kind: 'STALE' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('로그인이 풀렸으면 그대로 던진다', async () => {
    mockFetchSequence(status(401))
    const waiting = waitForResult(13, { signal: new AbortController().signal })
    const assertion = expect(waiting).rejects.toBeInstanceOf(UnauthorizedError)

    await vi.advanceTimersByTimeAsync(INTERVAL_MS)
    await assertion
  })

  it('요청이 잘못됐다는 답은 다시 묻지 않고 던진다', async () => {
    const fetchMock = mockFetchSequence(status(422))
    const waiting = waitForResult(13, { signal: new AbortController().signal })
    const assertion = expect(waiting).rejects.toMatchObject({ status: 422 })

    await vi.advanceTimersByTimeAsync(INTERVAL_MS * 3)
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  /** 상한 직전에 끝난 판단을 두고 "오래 걸린다" 고 하면 안 된다 */
  it('상한에 닿는 마지막 차례에도 물어본다', async () => {
    const answers = [...Array.from({ length: TIMEOUT_MS / INTERVAL_MS - 1 }, () => PENDING), json(UPDATED)]
    mockFetchSequence(...answers)
    const waiting = waitForResult(13, { signal: new AbortController().signal })

    await vi.advanceTimersByTimeAsync(TIMEOUT_MS)

    await expect(waiting).resolves.toEqual({ kind: 'SETTLED', body: UPDATED })
  })

  /** 판단 도중 서버가 다시 뜨면 그 제출은 영영 `PENDING` 이다(#40) */
  it('상한까지 판단 중이면 그만 기다린다', async () => {
    const fetchMock = mockFetchSequence(PENDING)
    const waiting = waitForResult(13, { signal: new AbortController().signal })

    await vi.advanceTimersByTimeAsync(TIMEOUT_MS)

    await expect(waiting).resolves.toEqual({ kind: 'WAITED_TOO_LONG' })
    const calls = fetchMock.mock.calls.length

    await vi.advanceTimersByTimeAsync(INTERVAL_MS * 3)
    expect(fetchMock).toHaveBeenCalledTimes(calls)
  })

  /**
   * 떠난 화면이 결과를 받아 사장님을 다른 화면으로 끌고 가면 안 된다.
   *
   * 실패한 이유를 값으로 받아 둔다. 끊긴 이유가 아니라 결과가 오면 `toBe` 에서 걸린다
   */
  it('쉬는 사이 화면을 떠나면 더 묻지 않는다', async () => {
    const fetchMock = mockFetchSequence(json(UPDATED))
    const controller = new AbortController()
    const waiting = waitForResult(13, { signal: controller.signal }).catch((reason: unknown) => reason)

    controller.abort()
    await vi.advanceTimersByTimeAsync(INTERVAL_MS * 3)

    expect(await waiting).toBe(controller.signal.reason)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('묻는 사이 화면을 떠나면 돌아온 답을 버린다', async () => {
    const controller = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async () => {
        controller.abort()
        return json(UPDATED)()
      }),
    )
    const waiting = waitForResult(13, { signal: controller.signal }).catch((reason: unknown) => reason)

    await vi.advanceTimersByTimeAsync(INTERVAL_MS)

    expect(await waiting).toBe(controller.signal.reason)
  })
})
