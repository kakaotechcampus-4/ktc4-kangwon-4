import { readMockKey } from './mockSwitch'
import { createSessionFlag } from './sessionFlag'

/**
 * Case를 이미 만들었는지.
 *
 * 진입 분기가 `/start`와 `/case` 중 어디로 보낼지 정하는 데 쓴다.
 *
 * 서버가 없는 동안 이 값을 `?mock=` 으로만 판단하면, Mock 전환이 꺼지는 Production에서
 * 항상 "Case 있음"이 되어 `/start`와 `/cases/new`에 아무도 닿지 못한다. 실제로 만든
 * 적이 있는지를 기억해 두면 배포된 화면에서도 처음 온 사용자의 흐름이 그대로 돈다.
 *
 * TODO(API): `GET /cases` 응답의 `case`가 `null`인지로 판단한다. 그때 이 파일은 지운다 —
 * Case가 있는지는 서버가 아는 것이지 브라우저가 기억할 것이 아니다.
 */
const flag = createSessionFlag('reborn:has-case')

/** `search`를 반드시 받는 이유는 `isLoggedIn`과 같다 */
export function hasCase(search: string): boolean {
  if (readMockKey(search) === 'no-case') return false
  return flag.read()
}

export function markCaseCreated(): void {
  flag.write(true)
}
