import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from './api'
import { saveChecklist, saveSupportApproval } from './roadmapActions'

function mockFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () => new Response(status === 200 ? JSON.stringify(body) : null, { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const sent = (fetchMock: ReturnType<typeof mockFetch>) => {
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  return { url, method: init.method, body: JSON.parse(init.body as string) }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

/** 체크·심사 결과는 저장된 값으로만 화면을 바꾼다. 무엇이 저장됐는지 못 읽으면 실패로 끊는다 */
describe('saveChecklist', () => {
  it('할 일 번호 주소로 PUT 하고 저장된 상태를 돌려준다', async () => {
    const fetchMock = mockFetch({ task_id: 'dispose_stock', completed: true })

    await expect(saveChecklist('dispose_stock', true)).resolves.toBe(true)
    expect(sent(fetchMock)).toEqual({
      url: expect.stringMatching(/\/cases\/checklists\/dispose_stock$/),
      method: 'PUT',
      body: { completed: true },
    })
  })

  it('저장된 상태를 읽지 못하면 실패로 끊는다', async () => {
    mockFetch({ task_id: 'dispose_stock' })

    await expect(saveChecklist('dispose_stock', true)).rejects.toBeInstanceOf(ApiError)
  })
})

describe('saveSupportApproval', () => {
  /** "아직 모름"은 키를 빼지 않고 `null` 로 보낸다. 키가 빠지면 서버가 422 로 막는다 */
  it('아직 모름도 null 로 담아 보낸다', async () => {
    const fetchMock = mockFetch({ approved: null })

    await expect(saveSupportApproval(null)).resolves.toBeNull()
    expect(sent(fetchMock)).toEqual({
      url: expect.stringMatching(/\/cases\/support-approval$/),
      method: 'PUT',
      body: { approved: null },
    })
  })

  it('저장된 결과가 참·거짓·null 이 아니면 실패로 끊는다', async () => {
    mockFetch({ approved: 'yes' })

    await expect(saveSupportApproval(true)).rejects.toBeInstanceOf(ApiError)
  })
})
