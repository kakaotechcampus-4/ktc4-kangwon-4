/**
 * 기기에서 "동작 줄이기"를 켰는지.
 *
 * 켰으면 저절로 바뀌거나 사라지는 글을 두지 않는다 — 읽는 도중에 사라진다.
 * 홈 띠(`HomeBanner`)와 알림 띠(`Toast`)가 같이 쓴다.
 */
export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
