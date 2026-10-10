import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

/**
 * 배포된 화면은 서버를 `/api/...` 로 부르고 `vercel.json` 의 규칙이 서버로 넘긴다.
 * 개발 서버에도 같은 규칙을 둬서, 로컬에서도 배포와 같은 길로 요청이 나가게 한다.
 *
 * 이게 없으면 로컬만 서버 주소를 직접 부르게 되어, "로컬에서는 되는데 배포에서만
 * 안 되는" 차이가 생긴다. 설정을 빠뜨렸을 때 로컬에서 바로 드러나는 편이 낫다.
 *
 * 로컬 BE 에 붙일 때는 `.env.local` 의 `VITE_API_BASE_URL` 로 이 프록시를 건너뛴다.
 */
const API_SERVER = 'https://reborn-ktc.duckdns.org'

/** 개발 서버(`dev`)와 빌드 확인용 서버(`preview`)가 같은 규칙을 써야 한다 */
const API_PROXY = {
  '/api': {
    target: API_SERVER,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: API_PROXY },
  preview: { proxy: API_PROXY },
  test: {
    /** 화면을 렌더해 역할·상태로 찾는 테스트라 DOM이 필요하다 */
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})
