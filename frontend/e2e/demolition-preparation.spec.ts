import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { BE_URL, TOKEN_FILE } from '../playwright.config.ts'

const SCOPE_TEXT = '원상복구 범위는 전부이고 철거가 필요합니다. 작업은 아직 시작하지 않았습니다.'
const PREPARATION_TEXT = '철거 전 사진을 찍고, 업체와 증빙 준비사항을 확인했습니다.'

// 모델 해석만 합성한다. 후보·검수·저장·새 조회는 실제 Graph/Guard와 격리 MySQL이다.
test('철거 준비 확인만 저장해도 반영을 알리고 같은 준비 확인을 다시 시키지 않는다', async ({ page, request }) => {
  const { preparation_member: member } = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'))
  const headers = { 'Access-Token': member.access_token }
  const created = await request.post(`${BE_URL}/cases`, { headers, data: {
    business_type: 'CAFE', franchise_status: false, lease_status: 'LEASED_PAID', employee_count: 0,
    had_employees: false, pension_enrolled: false, health_insurance_enrolled: false,
    employment_insurance_enrolled: false, industrial_accident_insurance_enrolled: false,
  } })
  expect(created.ok()).toBe(true)
  await expect(async () => {
    expect((await (await request.get(`${BE_URL}/cases`, { headers })).json()).judgment_status).toBe('DONE')
  }).toPass({ timeout: 30_000 })
  await page.addInitScript(([access, refresh]) => {
    sessionStorage.setItem('reborn:access-token', access)
    sessionStorage.setItem('reborn:refresh-token', refresh)
  }, [member.access_token, member.refresh_token])

  // 범위 확인도 화면에서 보고한다. 다음 행동이 실제 준비 확인인 상태부터 재현한다.
  await page.goto('/results')
  await page.getByRole('button', { name: '직접 쓸게요', exact: true }).click()
  await page.getByRole('textbox').fill(SCOPE_TEXT)
  await page.getByRole('button', { name: '보내기', exact: true }).click()
  await expect(page).toHaveURL(/\/replan\?history=/)
  const scopeId = Number(new URL(page.url()).searchParams.get('history'))
  expect(savedState(scopeId)).toMatchObject({
    action: 'CONFIRM_RESTORATION_REQUIREMENTS', requirements_confirmed: false, submitted: false,
  })

  await page.goto('/results')
  await page.getByRole('textbox').fill(PREPARATION_TEXT)
  const sent = page.waitForResponse(response => response.url() === `${BE_URL}/cases/results`
    && response.request().method() === 'POST')
  await page.getByRole('button', { name: '보내기', exact: true }).click()
  const accepted = await sent
  expect(accepted.ok()).toBe(true)
  const { case_history_id: historyId } = await accepted.json()
  let result: { result: string; changes: unknown[]; next_action: { title: string } }
  await expect(async () => {
    const response = await request.get(`${BE_URL}/cases/results/status?case_history_id=${historyId}`, { headers })
    expect(response.ok()).toBe(true)
    result = await response.json()
    expect(result.result).not.toBe('PENDING')
  }).toPass({ timeout: 30_000 })

  // 새 DB 세션에서 준비만 반영됐음을 확인한다. 공사 실행·완료·제출은 자동 확정하지 않는다.
  const saved = savedState(historyId)
  expect(saved).toMatchObject({
    judgment_status: 'DONE', raw_input: PREPARATION_TEXT, restoration_status: 'NOT_STARTED',
    step_status: 'IN_PROGRESS', requirements_confirmed: true, submitted: false,
    field_changes: 0, progress_changes: 1, conflict_snapshot: null, retained_info_result: null,
  })
  expect(saved.action).not.toBe('CONFIRM_RESTORATION_REQUIREMENTS')
  expect(saved.action).not.toBe('PERFORM_RESTORATION')
  expect(saved.evidence_refs.length).toBeGreaterThan(0)
  expect(saved.source_refs).toContain(`case_history:${historyId}`)
  expect(result!.result).toBe('UPDATED')
  expect(result!.changes).toEqual([])
  await expect(page).toHaveURL(new RegExp(`/replan\\?history=${historyId}$`))
  await expect(page.getByRole('heading', { name: '알려주신 내용을 반영했어요', exact: true })).toBeVisible()
  await expect(page.getByText(result!.next_action.title, { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '가게 정보에 바뀐 내용은 없어요', exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('heading', { name: '알려주신 내용을 반영했어요', exact: true })).toBeVisible()
  await page.goto('/case')
  await expect(page.getByRole('heading', { level: 2, name: result!.next_action.title, exact: true })).toBeVisible()
  const reread = await (await request.get(`${BE_URL}/cases`, { headers })).json()
  expect(reread.judgment_status).toBe('DONE')
  expect(reread.case.restoration_status).toBe('NOT_STARTED')
  expect(reread.next_action.title).toBe(result!.next_action.title)
  expect(savedState(historyId)).toEqual(saved)
})

function savedState(historyId: number) {
  return JSON.parse(execFileSync(process.env.E2E_PYTHON ?? 'python', ['-c', `
import json, os, sys
from sqlmodel import Session, create_engine, select
import app.be.models
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.case_field_history import CaseFieldHistory
from app.be.models.evidence import Evidence
from app.be.models.procedure_step import CaseProcedureStep, CaseProcedureStepHistory, ProcedureStep
with Session(create_engine(os.environ['E2E_DATABASE_URL'])) as session:
    history = session.get(CaseHistory, int(sys.argv[1]))
    case = session.get(Case, history.case_id)
    step = session.exec(select(CaseProcedureStep).join(ProcedureStep).where(
        CaseProcedureStep.case_id == case.id, ProcedureStep.step_code == 'PERFORM_RESTORATION')).one()
    print(json.dumps(dict(judgment_status=history.judgment_status, raw_input=history.raw_input,
        action=history.next_action_code, restoration_status=case.restoration_status,
        step_status=step.status, requirements_confirmed=step.requirements_confirmed, submitted=step.submitted,
        evidence_refs=step.evidence_refs, source_refs=[row.source_ref for row in session.exec(
            select(Evidence).where(Evidence.evidence_id.in_(step.evidence_refs or []))).all()],
        conflict_snapshot=history.conflict_snapshot, retained_info_result=history.retained_info_result,
        field_changes=len(session.exec(select(CaseFieldHistory).where(CaseFieldHistory.case_history_id == history.id)).all()),
        progress_changes=len(session.exec(select(CaseProcedureStepHistory).where(
            CaseProcedureStepHistory.case_history_id == history.id)).all()))))
`, String(historyId)], { cwd: '../backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf-8' }))
}
