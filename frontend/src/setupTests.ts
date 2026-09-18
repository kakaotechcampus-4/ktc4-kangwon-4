/**
 * 테스트 전역 설정.
 *
 * `toBeDisabled`, `toBeInTheDocument` 같은 DOM 단언을 쓰려면 matcher를 등록해야 한다.
 * `/vitest` 진입점은 등록과 타입 확장을 함께 해준다 — 이것 없이는 타입 검사에서 막힌다.
 */
import '@testing-library/jest-dom/vitest'
