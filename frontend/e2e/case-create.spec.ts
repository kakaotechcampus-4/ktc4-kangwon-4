import { type APIRequestContext, expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { BE_URL, TOKEN_FILE } from '../playwright.config'

/**
 * 진단 → 가입 → 홈 "지금 할 일" → 새로고침해도 유지. 가입한 사장님이 처음 보는 길 하나다.
 *
 * 로그인은 카카오를 거치지 않는다. E2E 서버가 만든 회원의 토큰을 화면이 로그인 뒤 두는 자리
 * (sessionStorage, lib/auth.ts)에 넣고 시작한다.
 */
test('진단을 마치면 홈에 지금 할 일이 뜨고, 새로고침해도 남는다', async ({ page, request }) => {
  const { access_token, refresh_token } = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'))
  await page.addInitScript(
    ([access, refresh]) => {
      sessionStorage.setItem('reborn:access-token', access)
      sessionStorage.setItem('reborn:refresh-token', refresh)
    },
    [access_token, refresh_token],
  )

  // Case가 없는 회원이라 진입 분기가 진단으로 보낸다
  await page.goto('/')
  await expect(page).toHaveURL(/\/cases\/new/)

  const answer = async (choice: string, button = '다음') => {
    await page.getByRole('radio', { name: choice }).click()
    await page.getByRole('button', { name: button }).click()
  }
  await answer('개인 카페')
  await page.getByRole('button', { name: /가게 자리를\s*빌려서 써요/ }).click()
  await page.getByRole('button', { name: '1개 선택 완료' }).click()
  await answer('네, 내고 있어요')
  await answer('네, 있어요')
  await answer('아니요, 없어요')
  await page.getByRole('button', { name: '잘 모르겠어요' }).click()
  await answer('다음 달', '폐업 순서 만들기')

  // 판단은 뒤에서 돌고 홈이 반복 조회한다(3초). 가짜 모델이라 몇 초면 끝난다
  await expect(page).toHaveURL(/\/case$/)
  const saved = await waitForJudgment(request, access_token)
  expect(saved.judgment_status).toBe('DONE')

  // 화면이 그린 할 일이 서버가 저장한 것과 같다
  const nextAction = page.getByRole('heading', { level: 2, name: saved.next_action.title })
  await expect(nextAction).toBeVisible()

  await page.reload()
  await expect(page).toHaveURL(/\/case$/)
  await expect(page.getByRole('heading', { level: 2, name: saved.next_action.title })).toBeVisible()
})

/** 판단이 끝날 때까지 서버에 묻는다. 화면과 따로 물어서, 화면이 틀리면 서버 값과 어긋나 드러난다 */
async function waitForJudgment(request: APIRequestContext, accessToken: string) {
  let body: { judgment_status: string; next_action: { title: string } }
  await expect(async () => {
    const response = await request.get(`${BE_URL}/cases`, { headers: { 'Access-Token': accessToken } })
    body = await response.json()
    expect(body.judgment_status).not.toBe('PENDING')
  }).toPass({ timeout: 30_000 })
  return body!
}
