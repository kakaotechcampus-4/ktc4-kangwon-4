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

  /**
   * 서버를 부를 때 앞에 붙이는 주소. 끝에 `/`를 붙이지 않는다.
   *
   * 비워두면 `/api`를 쓴다 — 같은 출처로 요청해 `vercel.json`의 프록시가 서버로 넘긴다.
   * 배포된 화면은 HTTPS인데 서버가 HTTP라, 직접 부르면 브라우저가 차단하기 때문이다.
   *
   * 로컬 개발은 `.env.local`에 서버 주소를 직접 넣는다. 서버 주소는 비밀이 아니다.
   */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
