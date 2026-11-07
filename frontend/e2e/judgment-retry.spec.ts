import { type APIRequestContext, expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { BE_URL, TOKEN_FILE } from '../playwright.config.ts'

// e2e_server.py의 OUTAGE_TEXT와 같은 문장. 처음 한 번은 모델 서버가 끊긴 것처럼 실패하고(다시 시도 가능),
// 다시 판단하면 정상으로 돈다.
const OUTAGE_TEXT = '다시 확인해 보니 원상복구는 일부이고 카운터만 철거해야 합니다.'

type CaseView = {
  judgment_status: string
  recovery_action_code: string | null
  case_history_id: number | null
  next_action: { title: string } | null
  case: { restoration_scope: string; restoration_scope_detail: string | null }
}

/**
 * 결과 알려주기 판단이 실패하면 홈에 [다시 판단하기]가 뜨고, 누르면 같은 글로 다시 판단해 이어진다(#196·#210·#231).
 * 쓴 글은 화면에만 있다가 사라지므로, 서버에 남은 글로 다시 판단하는지가 핵심이다.
 */
test('결과 알려주기가 일시 장애로 실패하면 홈의 다시 판단하기로 같은 글을 다시 판단한다', async ({ page, request }) => {
  const { retry_member: member } = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'))
  const headers = { 'Access-Token': member.access_token }
  // 가입·첫 판단은 API로 준비한다. 진단 화면은 case-create.spec.ts가 본다
  const created = await request.post(`${BE_URL}/cases`, { headers, data: {
    business_type: 'CAFE', franchise_status: false, lease_status: 'LEASED_PAID', employee_count: 0,
  } })
  expect(created.ok()).toBe(true)
  const first = await settled(request, headers)
  expect(first.judgment_status).toBe('DONE')
  const firstAction = first.next_action!.title

  await page.addInitScript(([access, refresh]) => {
    sessionStorage.setItem('reborn:access-token', access)
    sessionStorage.setItem('reborn:refresh-token', refresh)
  }, [member.access_token, member.refresh_token])
  await page.goto('/results')
  await page.getByRole('button', { name: '직접 쓸게요', exact: true }).click()
  await page.getByRole('textbox').fill(OUTAGE_TEXT)
  const sent = page.waitForResponse(r => r.url() === `${BE_URL}/cases/results` && r.request().method() === 'POST')
  await page.getByRole('button', { name: '보내기', exact: true }).click()
  const accepted = await sent
  expect(accepted.ok()).toBe(true)
  const { case_history_id: historyId } = await accepted.json()

  const failed = await settled(request, headers)
  expect([failed.judgment_status, failed.recovery_action_code]).toEqual(['FAILED', 'RETRY'])

  // 홈: 실패 카드와 다시 판단하기. 첫 판단의 할 일을 새 성공처럼 보여주지 않는다
  await page.goto('/case')
  await expect(page.getByRole('heading', { level: 2, name: '다음 할 일을 정하지 못했어요' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: firstAction })).toHaveCount(0)

  const retried = page.waitForResponse(r => r.url() === `${BE_URL}/cases/retry` && r.request().method() === 'POST')
  await page.getByRole('button', { name: '다시 판단하기', exact: true }).click()
  const retry = await retried
  expect(retry.ok()).toBe(true)
  // 새 이력을 만들지 않고 실패한 그 판단을 다시 돌린다
  expect((await retry.json()).case_history_id).toBe(historyId)

  const done = await settled(request, headers)
  expect(done.judgment_status).toBe('DONE')
  expect([done.case.restoration_scope, done.case.restoration_scope_detail]).toEqual(['PARTIAL', '카운터'])
  const nextAction = page.getByRole('heading', { level: 2, name: done.next_action!.title })
  await expect(nextAction).toBeVisible({ timeout: 15_000 })
  await page.reload()
  await expect(page.getByRole('heading', { level: 2, name: done.next_action!.title })).toBeVisible()

  // 화면에서 사라진 글이 서버에는 그대로 남아 그 글로 판단했다
  expect(savedHistory(historyId)).toEqual({ source: 'USER_INPUT', raw_input: OUTAGE_TEXT, judgment_status: 'DONE' })
})

/** 판단이 끝날 때까지 서버에 묻는다. 화면과 따로 물어서, 화면이 틀리면 서버 값과 어긋나 드러난다 */
async function settled(request: APIRequestContext, headers: Record<string, string>): Promise<CaseView> {
  let body: CaseView
  await expect(async () => {
    body = await (await request.get(`${BE_URL}/cases`, { headers })).json()
    expect(body.judgment_status).not.toBe('PENDING')
  }).toPass({ timeout: 30_000 })
  return body!
}

// 새 Python 세션으로 격리 MySQL을 읽어 HTTP 응답이 아닌 실제 저장값을 본다
function savedHistory(id: number) {
  return JSON.parse(execFileSync(process.env.E2E_PYTHON ?? 'python', ['-c', `
import json, os, sys
from sqlmodel import Session, create_engine
from app.be.models.case_history import CaseHistory
with Session(create_engine(os.environ['E2E_DATABASE_URL'])) as session:
    row = session.get(CaseHistory, int(sys.argv[1]))
    print(json.dumps(dict(source=row.source, raw_input=row.raw_input, judgment_status=row.judgment_status)))
`, String(id)], { cwd: '../backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf-8' }))
}
