import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { BE_URL, TOKEN_FILE } from '../playwright.config.ts'

for (const [index, side] of ['STORED', 'PROPOSED'].entries()) {
  test(`충돌 ${side}: 확인 전 기존 값을 지키고 고른 값만 저장한다`, async ({ page, request }) => {
    const { conflict_members: members } = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'))
    const member = members[index]
    const headers = { 'Access-Token': member.access_token }
    const created = await request.post(`${BE_URL}/cases`, { headers, data: {
      business_type: 'CAFE', franchise_status: false, lease_status: 'LEASED_PAID', employee_count: 0,
      had_employees: false, pension_enrolled: false, health_insurance_enrolled: false,
      employment_insurance_enrolled: false, industrial_accident_insurance_enrolled: false,
    } })
    expect(created.ok()).toBe(true)
    const { id: caseId } = await created.json()
    await expect(async () => {
      const entry = await (await request.get(`${BE_URL}/cases/results`, { headers })).json()
      expect(entry.judgment_status).toBe('DONE')
      expect(entry.result_input_kind).toBe('RESTORATION_ANSWER')
    }).toPass({ timeout: 30_000 })
    databaseState(caseId, true) // 이전에 확인한 전부·카운터·철거 필요라는 합성 기록
    await page.addInitScript(([access, refresh]) => {
      sessionStorage.setItem('reborn:access-token', access)
      sessionStorage.setItem('reborn:refresh-token', refresh)
    }, [member.access_token, member.refresh_token])
    await page.goto('/results')
    await page.getByRole('radio', { name: '일부만 원래대로 하면 된대요', exact: true }).click()
    await page.getByRole('radio', { name: '철거해야 한대요', exact: true }).click()
    await page.getByRole('button', { name: '보내기', exact: true }).click()
    await expect(page).toHaveURL(/\/confirm$/)
    const proceed = page.getByRole('button', { name: '이대로 진행하기', exact: true })
    await expect(proceed).toBeDisabled()
    await expect(page.getByRole('button', { pressed: true })).toHaveCount(0)
    const conflicted = await (await request.get(`${BE_URL}/cases/results`, { headers })).json()
    expect(conflicted.judgment_status).toBe('CONFLICT')
    expect(conflicted.conflicts).toEqual([{
      id: expect.any(Number), field: 'restoration_scope', stored_value: 'FULL', proposed_value: 'PARTIAL',
    }])
    expect(databaseState(caseId)).toMatchObject({ scope: 'FULL', conflict_status: 'PENDING' })
    // 새 진입도 저장된 충돌을 복원한다. 선택은 자동으로 채우지 않는다.
    await page.goto('/results')
    await expect(page).toHaveURL(/\/confirm$/)
    await expect(proceed).toBeDisabled()
    await expect(page.getByRole('button', { pressed: true })).toHaveCount(0)
    await page.getByRole('button', { name: side === 'STORED' ? /^지금 기록/ : /^이번에 말씀하신 것/ }).click()
    const pending = page.waitForResponse(r => r.url().endsWith('/cases/results/decision') && r.request().method() === 'POST')
    await proceed.click()
    const accepted = await pending
    expect(accepted.ok()).toBe(true)
    expect(accepted.request().postDataJSON()).toEqual({ decisions: [{ conflict_reference_id: conflicted.conflicts[0].id, side }] })
    const { case_history_id: historyId } = await accepted.json()
    await expect(page).toHaveURL(new RegExp(`/replan\\?history=${historyId}&from=confirm$`))
    await page.reload()
    await expect(page.getByRole('button', { name: '홈으로', exact: true })).toBeVisible()
    const decision = await (await request.get(`${BE_URL}/cases/results/status?case_history_id=${historyId}`, { headers })).json()
    expect(decision.result).toBe(side === 'STORED' ? 'NO_CHANGE' : 'UPDATED')
    expect(decision.next_action.title).toEqual(expect.any(String))
    const reread = await (await request.get(`${BE_URL}/cases`, { headers })).json()
    expect(reread.case.id).toBe(caseId)
    expect(reread.judgment_status).toBe('DONE')
    expect(reread.case.restoration_scope).toBe(side === 'STORED' ? 'FULL' : 'PARTIAL')
    expect(databaseState(caseId)).toMatchObject({
      scope: side === 'STORED' ? 'FULL' : 'PARTIAL', detail: '카운터',
      conflict_status: side === 'STORED' ? 'REJECTED' : 'CONFIRMED',
      resolved_by: historyId, source: 'CONFLICT_DECISION', judgment: 'DONE',
    })
  })
}

// 새 세션에서 실제 저장값을 대조한다. prepare는 격리 DB의 합성 이전 기록만 만든다.
function databaseState(caseId: number, prepare = false) {
  return JSON.parse(execFileSync(process.env.E2E_PYTHON ?? 'python', ['-c', `
import json, os, sys
from sqlmodel import Session, create_engine, select
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference
with Session(create_engine(os.environ['E2E_DATABASE_URL'])) as session:
    case = session.get(Case, int(sys.argv[1]))
    if sys.argv[2] == 'true':
        case.restoration_scope = 'FULL'
        case.restoration_scope_detail = '카운터'
        case.demolition_required = 'REQUIRED'
        session.add(case)
        session.commit()
        print('{}')
    else:
        conflict = session.exec(select(ConflictReference).where(ConflictReference.case_id == case.id)).one()
        history = session.get(CaseHistory, conflict.resolved_by_case_history_id) if conflict.resolved_by_case_history_id else None
        print(json.dumps(dict(scope=case.restoration_scope, detail=case.restoration_scope_detail,
            conflict_status=conflict.status, resolved_by=conflict.resolved_by_case_history_id,
            source=history.source if history else None, judgment=history.judgment_status if history else None)))
`, String(caseId), String(prepare)], { cwd: '../backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf-8' }))
}
