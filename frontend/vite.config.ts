import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    /** 화면을 렌더해 역할·상태로 찾는 테스트라 DOM이 필요하다 */
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})
