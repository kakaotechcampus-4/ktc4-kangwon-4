import { defineConfig, devices } from '@playwright/test'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

/**
 * 브라우저 E2E. 진짜 FE(빌드본) · 진짜 BE · 진짜 MySQL로 핵심 흐름 하나를 돈다. 모델은 부르지 않는다.
 *
 * BE는 `backend/tests/e2e_server.py`가 띄운다. 판단은 진짜 AI 그래프로 돌고 모델 자리만 가짜다.
 * 켤 때 DB의 표를 전부 지우므로 `E2E_DATABASE_URL`을 꼭 따로 준다(개발 DB 주소를 쓰지 않는다).
 *
 *   E2E_DATABASE_URL='mysql+pymysql://root:pw@127.0.0.1:3306/e2e?charset=utf8mb4' \
 *   E2E_PYTHON=../backend/.venv/bin/python npm run test:e2e
 */
const BE_PORT = 8765
const FE_PORT = 4173
export const BE_URL = `http://127.0.0.1:${BE_PORT}`
export const TOKEN_FILE = process.env.E2E_TOKEN_FILE ?? join(tmpdir(), 'reborn-e2e-token.json')

const databaseUrl = process.env.E2E_DATABASE_URL
if (!databaseUrl) {
  throw new Error('E2E_DATABASE_URL이 필요합니다. 켤 때 표를 지우므로 개발 DB 주소를 쓰지 마세요.')
}

export default defineConfig({
  testDir: './e2e',
  // 실패를 다시 돌려 덮지 않는다. 한 번이라도 깨지면 원인을 본다
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${FE_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // 화면이 모바일 기준(375px)이라 그 폭으로 본다
  projects: [{ name: 'mobile-chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 375, height: 812 } } }],
  webServer: [
    {
      command: `${process.env.E2E_PYTHON ?? 'python'} tests/e2e_server.py`,
      cwd: '../backend',
      url: `${BE_URL}/health`,
      env: { E2E_DATABASE_URL: databaseUrl, E2E_TOKEN_FILE: TOKEN_FILE, E2E_BE_PORT: String(BE_PORT) },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // 배포와 같은 빌드본으로 본다. 서버 주소만 E2E BE로 바꾼다(lib/api.ts)
      command: `npm run build && npx vite preview --host 127.0.0.1 --port ${FE_PORT} --strictPort`,
      url: `http://127.0.0.1:${FE_PORT}`,
      env: { VITE_API_BASE_URL: BE_URL },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
})
