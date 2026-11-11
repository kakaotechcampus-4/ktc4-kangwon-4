import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, UnauthorizedError } from './api'
import { saveTokens } from './auth'
import { retryJudgment } from './judgmentRetry'

function respond(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () => new Response(body === null ? null : JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('retryJudgment', () => {
  it('본문 없이 보내고 다시 돌린 판단 번호를 받는다', async () => {
    saveTokens('access-1', 'refresh-1')
    const fetchMock = respond({ case_history_id: 3 })

    await expect(retryJudgment()).resolves.toBe(3)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/cases/retry')
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()
  })

  /** 받았다는 답인데 번호가 없으면 정말 다시 돌았는지 모른다. 받은 것처럼 넘기지 않는다 */
  it('번호를 읽지 못하면 실패로 올린다', async () => {
    saveTokens('access-1', 'refresh-1')
    respond({})

    await expect(retryJudgment()).rejects.toBeInstanceOf(ApiError)
  })

  it('본문이 null 이어도 같은 실패로 올린다', async () => {
    saveTokens('access-1', 'refresh-1')
    vi.stubGlobal('fetch', vi.fn(async () => new Response('null')))

    await expect(retryJudgment()).rejects.toBeInstanceOf(ApiError)
  })

  it('거절은 상태 코드 그대로 올린다', async () => {
    saveTokens('access-1', 'refresh-1')
    respond(null, 409)

    await expect(retryJudgment()).rejects.toMatchObject({ status: 409 })
  })

  it('로그인이 풀렸으면 그대로 알린다', async () => {
    saveTokens('access-1', 'refresh-1')
    respond(null, 401)

    await expect(retryJudgment()).rejects.toBeInstanceOf(UnauthorizedError)
  })
})
