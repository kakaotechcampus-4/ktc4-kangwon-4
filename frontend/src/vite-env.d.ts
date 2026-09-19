/// <reference types="vite/client" />

/**
 * 환경변수 타입 선언.
 *
 * `VITE_` 접두사가 붙은 값만 빌드 결과에 포함되어 브라우저에서 읽을 수 있다.
 * 즉, 여기 적는 값은 전부 공개되므로 키나 토큰을 두지 않는다.
 */
interface ImportMetaEnv {
  /**
   * Preview 배포에서 URL 쿼리로 Mock을 전환할 수 있게 한다.
   * Vercel의 Preview 환경에만 설정하고 Production에는 두지 않는다.
   */
  readonly VITE_ENABLE_MOCK_SWITCH?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
