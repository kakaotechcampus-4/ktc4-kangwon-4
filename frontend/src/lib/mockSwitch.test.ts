import { describe, expect, it } from 'vitest'

import { readMockKey } from './mockSwitch'

/**
 * 호출부는 돌려받은 키를 자기 Mock 목록에서 찾는다. 그래서 "없음"이 `null`이나
 * `undefined`가 아니라 **빈 문자열**이어야 호출부마다 `?? ''`를 반복하지 않는다.
 * 아래는 그 약속을 고정한다.
 */
describe('readMockKey', () => {
  it('mock 값을 그대로 돌려준다', () => {
    expect(readMockKey('?mock=conflict')).toBe('conflict')
  })

  it('다른 쿼리가 함께 있어도 mock만 읽는다', () => {
    expect(readMockKey('?foo=1&mock=no-change')).toBe('no-change')
  })

  it('쿼리가 없으면 빈 문자열', () => {
    expect(readMockKey('')).toBe('')
  })

  it('mock 키가 없으면 빈 문자열', () => {
    expect(readMockKey('?foo=1')).toBe('')
  })

  it('mock 값이 비어 있어도 빈 문자열', () => {
    expect(readMockKey('?mock=')).toBe('')
  })
})
