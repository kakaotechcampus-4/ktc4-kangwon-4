import { afterEach, describe, expect, it, vi } from 'vitest'

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

/**
 * 전환이 허용되지 않는 환경에서는 `?mock=` 을 아예 읽지 않는다.
 *
 * 이게 뚫리면 배포된 대표 주소에서 주소창에 `?mock=` 을 붙이는 것만으로 가짜 Case가
 * 보인다. 실제 사용자가 남의 가게 상황처럼 생긴 화면을 보고 자기 것으로 읽는다.
 *
 * `MOCK_SWITCH_ENABLED`는 모듈을 읽어 들일 때 한 번 계산되는 상수다. 그래서 환경변수만
 * 바꿔서는 이미 평가된 값이 그대로 남는다. 모듈 등록을 지우고(`resetModules`)
 * 다시 import해야 바뀐 환경으로 계산된다.
 */
describe('MOCK_SWITCH_ENABLED', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  async function loadWith(dev: boolean, flag: string) {
    vi.stubEnv('DEV', dev)
    vi.stubEnv('VITE_ENABLE_MOCK_SWITCH', flag)
    vi.resetModules()

    return import('./mockSwitch')
  }

  it('프로덕션에서는 ?mock= 을 읽지 않는다', async () => {
    const { MOCK_SWITCH_ENABLED, readMockKey } = await loadWith(false, '')

    expect(MOCK_SWITCH_ENABLED).toBe(false)
    expect(readMockKey('?mock=no-case')).toBe('')
  })

  /** Preview는 빌드 결과물이라 DEV가 false다. 환경변수로만 열린다 */
  it('배포 환경이라도 환경변수가 true면 읽는다', async () => {
    const { MOCK_SWITCH_ENABLED, readMockKey } = await loadWith(false, 'true')

    expect(MOCK_SWITCH_ENABLED).toBe(true)
    expect(readMockKey('?mock=no-case')).toBe('no-case')
  })

  /** 환경변수는 언제나 문자열이라 'false'도 truthy다. 값을 그대로 쓰면 여기서 뚫린다 */
  it("환경변수가 문자열 'false'면 읽지 않는다", async () => {
    const { MOCK_SWITCH_ENABLED } = await loadWith(false, 'false')

    expect(MOCK_SWITCH_ENABLED).toBe(false)
  })
})
