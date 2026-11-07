import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { BE_URL, TOKEN_FILE } from '../playwright.config.ts'

test('판단 일시 실패는 입력·Case를 보존하고 홈에서 같은 이력을 다시 판단한다', async ({ page, request }) => {
  const { retry_member: member } = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'))
  const headers = { 'Access-Token': member.access_token }
  const created = await request.post(`${BE_URL}/cases`, { headers, data: {
    business_type: 'CAFE', franchise_status: false, lease_status: 'LEASED_PAID', employee_count: 0,
    had_employees: false, pension_enrolled: false, health_insurance_enrolled: false,
    employment_insurance_enrolled: false, industrial_accident_insurance_enrolled: false,
  } })
  expect(created.ok()).toBe(true)
  let original: { case: Record<string, unknown>; judgment_status: string; next_action: { title: string } }
  await expect(async () => {
    original = await (await request.get(`${BE_URL}/cases`, { headers })).json()
    expect(original.judgment_status).toBe('DONE')
  }).toPass({ timeout: 30_000 })
  await page.addInitScript(([access, refresh]) => {
    sessionStorage.setItem('reborn:access-token', access)
    sessionStorage.setItem('reborn:refresh-token', refresh)
  }, [member.access_token, member.refresh_token])
  await page.goto('/results')
  await page.getByRole('button', { name: '직접 쓸게요', exact: true }).click()
  const text = '원상복구는 일부이고 카운터만 철거해야 합니다. 일시 장애 확인용 합성 입력입니다.'
  await page.getByRole('textbox').fill(text)
  const submission = page.waitForResponse(r => r.url() === `${BE_URL}/cases/results` && r.request().method() === 'POST')
  await page.getByRole('button', { name: '보내기', exact: true }).click()
  const accepted = await submission
  expect(accepted.ok()).toBe(true)
  const { case_history_id: historyId } = await accepted.json()
  await expect(page.getByRole('button', { name: '다시 보내기', exact: true })).toBeEnabled()
  await expect(page.getByRole('textbox')).toHaveValue(text)
  const failed = await (await request.get(`${BE_URL}/cases`, { headers })).json()
  expect(failed.judgment_status).toBe('FAILED')
  expect(failed.case).toEqual(original!.case)
  expect(failed.next_action).toBeNull()
  expect(failed.recovery_action_code).toBe('RETRY')
  expect(databaseState(historyId)).toMatchObject({
    status: 'FAILED', raw_input: text, next_action: null, field_changes: 0, retryable: true,
  })
  // 화면을 떠나도 접수한 글은 DB에 남는다. 이전 성공의 할 일을 새 성공처럼 보여주지 않는다.
  await page.goto('/case')
  await page.reload()
  const retry = page.getByRole('button', { name: '다시 판단하기', exact: true })
  await expect(retry).toBeEnabled()
  await expect(page.getByRole('heading', { name: original!.next_action.title, exact: true })).toHaveCount(0)
  const retrying = page.waitForResponse(r => r.url().endsWith('/cases/retry') && r.request().method() === 'POST')
  await retry.click()
  const retried = await retrying
  expect(retried.ok()).toBe(true)
  expect(await retried.json()).toEqual({ case_history_id: historyId })
  let saved: typeof failed
  await expect(async () => {
    saved = await (await request.get(`${BE_URL}/cases`, { headers })).json()
    expect(saved.judgment_status).toBe('DONE')
  }).toPass({ timeout: 30_000 })
  expect(saved!.case.id).toBe(original!.case.id)
  expect(saved!.case).toMatchObject({ restoration_scope: 'PARTIAL', restoration_scope_detail: '카운터', demolition_required: 'REQUIRED' })
  expect(databaseState(historyId)).toMatchObject({
    status: 'DONE', raw_input: text, field_changes: 3, failure_code: null,
  })
  await page.reload()
  await expect(page.getByRole('heading', { level: 2, name: saved!.next_action.title, exact: true })).toBeVisible()
  await expect(retry).toHaveCount(0)
})

// 실패·재판단 모두 같은 DB 이력을 새 세션으로 읽는다. 모델 대역 외 저장 경로는 실제 코드다.
function databaseState(historyId: number) {
  return JSON.parse(execFileSync(process.env.E2E_PYTHON ?? 'python', ['-c', `
import json, os, sys
from sqlmodel import Session, create_engine, select
from app.be.models.case_history import CaseHistory
from app.be.models.case_field_history import CaseFieldHistory
with Session(create_engine(os.environ['E2E_DATABASE_URL'])) as session:
    history = session.get(CaseHistory, int(sys.argv[1]))
    changes = session.exec(select(CaseFieldHistory).where(CaseFieldHistory.case_history_id == history.id)).all()
    print(json.dumps(dict(status=history.judgment_status, raw_input=history.raw_input, next_action=history.next_action,
        field_changes=len(changes), failure_code=history.failure_code, retryable=history.retryable)))
`, String(historyId)], { cwd: '../backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf-8' }))
}
