import { insufficientCase, noBlockerCase, normalCase } from './mocks/currentCase'
import { CurrentCasePage } from './pages/CurrentCasePage'
import type { CurrentCaseView } from './types/view'

const MOCKS: Record<string, CurrentCaseView> = {
  'no-blocker': noBlockerCase,
  insufficient: insufficientCase,
}

/**
 * 개발 중에만 URL 쿼리로 Mock을 바꾼다. 예외 화면을 링크만으로 확인할 수 있어야
 * 리뷰어가 코드를 고치지 않고도 볼 수 있다.
 *
 *   /                      정상
 *   /?mock=no-blocker      막고 있는 것 없음
 *   /?mock=insufficient    정보 부족
 */
function resolveMock(): CurrentCaseView {
  if (!import.meta.env.DEV) return normalCase

  const key = new URLSearchParams(window.location.search).get('mock') ?? ''
  return MOCKS[key] ?? normalCase
}

function App() {
  return <CurrentCasePage data={resolveMock()} />
}

export default App
