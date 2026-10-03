import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createOAuthState,
  getAccessToken,
  isLoggedIn,
  isMockSession,
  logInWithMock,
  logOut,
  saveTokens,
  verifyOAuthState,
} from './auth'

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
 * state 가 없으면 공격자가 자기 계정의 `code` 가 담긴 콜백 주소를 사장님에게 열게 해서
 * 사장님 브라우저를 공격자 계정으로 로그인시킬 수 있다. 이 검사가 느슨해지면 화면은
 * 아무 이상 없이 동작하기 때문에, 뚫렸다는 사실이 밖으로 드러나지 않는다.
 */
describe('OAuth state', () => {
  it('내보낸 값은 그대로 다시 통과한다', () => {
    const state = createOAuthState()

    expect(verifyOAuthState(state)).toBe(true)
  })

  /** 제일 쉬운 공격이다. 주소에서 state 만 빼고 code 를 들고 오면 된다 */
  it('돌아온 값이 없으면 통과시키지 않는다', () => {
    createOAuthState()

    expect(verifyOAuthState(null)).toBe(false)
  })

  /** 새 탭에서 콜백 주소를 열거나, 저장소를 쓸 수 없는 브라우저인 경우다 */
  it('저장분이 없으면 통과시키지 않는다', () => {
    expect(verifyOAuthState('꾸며낸-값')).toBe(false)
  })

  /**
   * 실제 공격은 이 모양이다. 공격자가 state 없이 code 만 담은 주소를 보내고
   * 사장님이 새 탭에서 연다 — 양쪽이 다 비어 있다.
   *
   * `returned === saved` 한 줄로만 비교하면 `null === null` 이 참이라 그대로 통과한다.
   * 둘 중 하나만 비우는 테스트로는 이걸 못 잡는다. 다른 쪽 값이 비교를 막아주기 때문이다.
   */
  it('양쪽이 다 비어 있으면 통과시키지 않는다', () => {
    expect(verifyOAuthState(null)).toBe(false)
  })

  it('값이 다르면 통과시키지 않는다', () => {
    createOAuthState()

    expect(verifyOAuthState('꾸며낸-값')).toBe(false)
  })

  /**
   * state 하나는 로그인 시도 하나다. 성공한 뒤에도 남아 있으면 같은 콜백 주소를
   * 다시 열었을 때 또 통과한다.
   */
  it('통과한 값은 다시 쓸 수 없다', () => {
    const state = createOAuthState()
    verifyOAuthState(state)

    expect(verifyOAuthState(state)).toBe(false)
  })

  /**
   * 실패했을 때 저장분을 남겨두면, 공격자가 한 번 실패시켜 놓고 진짜 값이 그대로
   * 살아 있는 동안 다시 시도할 수 있다. 맞든 안 맞든 한 번 보면 버린다.
   */
  it('어긋난 시도 뒤에는 원래 값도 쓸 수 없다', () => {
    const state = createOAuthState()
    verifyOAuthState('꾸며낸-값')

    expect(verifyOAuthState(state)).toBe(false)
  })

  it('다시 시작하면 앞서 만든 값은 못 쓴다', () => {
    const first = createOAuthState()
    createOAuthState()

    expect(verifyOAuthState(first)).toBe(false)
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
