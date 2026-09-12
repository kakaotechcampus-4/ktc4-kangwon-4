import { insufficientCase, noBlockerCase, normalCase } from './mocks/currentCase'
import { CurrentCasePage } from './pages/CurrentCasePage'
import type { CurrentCaseView } from './types/view'

const MOCKS: Record<string, CurrentCaseView> = {
  'no-blocker': noBlockerCase,
  insufficient: insufficientCase,
}

/**
 * 이 환경에서 Mock 전환을 허용하는지.
 *
 * 로컬 개발 서버(`DEV`)는 항상 허용한다.
 * 배포된 환경은 빌드 결과물이라 `DEV`가 `false`라, 허용 여부를 환경변수로
 * 따로 받는다 — Preview는 켜고 Production은 끈다.
 *
 * 환경변수는 언제나 문자열로 들어온다. `'false'`도 truthy라 값을 그대로 쓰지 않고
 * `'true'`와 비교한다.
 */
const MOCK_SWITCH_ENABLED =
  import.meta.env.DEV || import.meta.env.VITE_ENABLE_MOCK_SWITCH === 'true'

/**
 * URL 쿼리로 Mock을 바꾼다. 예외 화면을 링크만으로 확인할 수 있어야
 * 리뷰어가 코드를 고치지 않고도 볼 수 있다.
 *
 *   /                      정상
 *   /?mock=no-blocker      막고 있는 것 없음
 *   /?mock=insufficient    정보 부족
 */
function resolveMock(): CurrentCaseView {
  if (!MOCK_SWITCH_ENABLED) return normalCase

  const key = new URLSearchParams(window.location.search).get('mock') ?? ''
  return MOCKS[key] ?? normalCase
}

function App() {
  return <CurrentCasePage data={resolveMock()} />
}

export default App
