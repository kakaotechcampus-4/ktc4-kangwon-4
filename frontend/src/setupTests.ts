/**
 * 테스트 전역 설정.
 *
 * `toBeDisabled`, `toBeInTheDocument` 같은 DOM 단언을 쓰려면 matcher를 등록해야 한다.
 * `/vitest` 진입점은 등록과 타입 확장을 함께 해준다 — 이것 없이는 타입 검사에서 막힌다.
 */
import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

/**
 * 렌더한 화면을 테스트마다 걷어낸다.
 *
 * Testing Library는 `afterEach`가 전역에 있을 때만 이 정리를 스스로 건다.
 * 이 프로젝트는 `describe`·`it`을 명시적으로 import하는 쪽이라 전역이 없어서 직접 건다.
 * 없으면 앞 테스트의 화면이 남아 같은 역할이 여러 개로 잡힌다.
 */
afterEach(cleanup)
