import { afterEach, describe, expect, it, vi } from 'vitest'

import { getAccessToken, isLoggedIn, isMockSession, logInWithMock, logOut, saveTokens } from './auth'

/**
 * 로그인 판단이 틀리면 둘 중 하나가 된다 — 로그인한 사람이 계속 로그인 화면으로
 * 되돌아오거나, 토큰 없는 사람이 보호된 화면에 들어간다. 어느 쪽도 화면만 봐서는
 * 원인을 알기 어렵다.
 */
describe('auth', () => {
  it('토큰을 저장하면 로그인 상태가 된다', () => {
    expect(isLoggedIn('')).toBe(false)

    saveTokens('access-1', 'refresh-1')

    expect(isLoggedIn('')).toBe(true)
  })

  /** 서버에 실어 보낼 값이라, 저장한 것과 다른 게 나오면 요청이 전부 401이 된다 */
  it('저장한 Access 토큰을 그대로 돌려준다', () => {
    saveTokens('access-1', 'refresh-1')

    expect(getAccessToken()).toBe('access-1')
  })

  it('로그아웃하면 토큰이 남지 않는다', () => {
    saveTokens('access-1', 'refresh-1')

    logOut()

    expect(isLoggedIn('')).toBe(false)
    expect(getAccessToken()).toBeNull()
  })

  /** 로그인 화면을 다시 보려고 만든 Mock이다. 저장된 상태를 이기지 못하면 쓸 수 없다 */
  it('토큰이 있어도 ?mock=logged-out이면 로그인하지 않은 것으로 본다', () => {
    saveTokens('access-1', 'refresh-1')

    expect(isLoggedIn('?mock=logged-out')).toBe(false)
  })

  it('가짜 로그인도 로그인 상태이지만 진짜 세션과 구분된다', () => {
    logInWithMock()

    expect(isLoggedIn('')).toBe(true)
    expect(isMockSession()).toBe(true)
  })

  it('진짜 토큰은 가짜 세션으로 보지 않는다', () => {
    saveTokens('access-1', 'refresh-1')

    expect(isMockSession()).toBe(false)
  })
})

/**
 * 가짜 로그인이 프로덕션에서 살아 있으면, 실제 사용자가 서버에 없는 세션을 들고
 * 보호된 화면에 들어간다. 버튼을 숨기는 것만으로는 부족해서 함수 자체에서 막는다.
 *
 * `MOCK_SWITCH_ENABLED`는 모듈을 읽어 들일 때 한 번 계산되는 상수라, 환경변수만 바꿔서는
 * 이미 평가된 값이 남는다. 모듈 등록을 지우고 다시 import해야 바뀐 환경으로 계산된다.
 */
describe('프로덕션에서의 가짜 로그인', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('아무 일도 하지 않는다', async () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_ENABLE_MOCK_SWITCH', '')
    vi.resetModules()

    const auth = await import('./auth')
    auth.logInWithMock()

    expect(auth.isLoggedIn('')).toBe(false)
    expect(auth.isMockSession()).toBe(false)
  })
})
