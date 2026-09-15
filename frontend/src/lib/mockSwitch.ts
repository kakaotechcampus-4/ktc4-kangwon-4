/**
 * 개발용 Mock 전환.
 *
 * 예외 화면을 링크만으로 확인할 수 있어야 리뷰어가 코드를 고치지 않고도 볼 수 있다.
 * 화면마다 쓸 수 있는 Mock이 다르므로 키 해석은 각 페이지가 맡고, 여기서는
 * "전환이 허용되는 환경인가"와 "쿼리에 무엇이 들어왔는가"만 다룬다.
 */

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
export const MOCK_SWITCH_ENABLED =
  import.meta.env.DEV || import.meta.env.VITE_ENABLE_MOCK_SWITCH === 'true'

/**
 * URL 쿼리의 `?mock=` 값. 전환이 허용되지 않는 환경에서는 항상 빈 문자열이다.
 *
 * 호출부는 이 값을 자기 Mock 목록에서 찾고, 없으면 기본 Mock을 쓴다.
 * `null` 대신 빈 문자열을 돌려주는 것은 호출부에서 `?? ''` 를 반복하지 않게 하려는 것이다.
 */
export function readMockKey(search: string): string {
  if (!MOCK_SWITCH_ENABLED) return ''
  return new URLSearchParams(search).get('mock') ?? ''
}
