import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { BE_URL, TOKEN_FILE } from '../playwright.config.ts'

// 실제 화면→API→Agent 그래프→MySQL→새 API 조회. 모델 응답만 합성값이다.
const scenarios = [
  { name: '전부', scope: 'FULL', label: '전부 원래대로 해야 한대요' },
  { name: '일부·세부 없음', scope: 'PARTIAL', label: '일부만 원래대로 하면 된대요', asks: true },
  { name: '일부·세부 있음', scope: 'PARTIAL', label: '일부만 원래대로 하면 된대요', known: true },
  { name: '불필요', scope: 'NOT_REQUIRED', label: '원상복구는 안 해도 된대요' },
  { name: '아직 모름', scope: 'UNKNOWN', label: '범위는 아직 안 정해졌대요' },
  { name: '기타 직접 입력', scope: 'PARTIAL', direct: true },
]
const directText = '원상복구는 일부이고 카운터만 철거해야 합니다. 연락처는 010-1234-5678입니다.'
const detailQuestion = '확인한 원상복구 범위의 구체적인 내용을 알려주세요.'

for (const [index, scenario] of scenarios.entries()) {
  test(`원상복구 ${scenario.name}: 보낸 값이 저장되고 새로 조회해도 유지된다`, async ({ page, request }) => {
    const { restoration_members: members } = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'))
    const { access_token: access, refresh_token: refresh } = members[index]
    const headers = { 'Access-Token': access }
    // 가입/첫 판단은 실제 API로 준비한다. 원래 가입 E2E는 진단 화면까지 별도로 검사한다.
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
    if (scenario.known) databaseState(caseId, true) // 이전에 확인한 세부 정보만 격리 DB에 준비
    await page.addInitScript(([a, r]) => {
      sessionStorage.setItem('reborn:access-token', a)
      sessionStorage.setItem('reborn:refresh-token', r)
    }, [access, refresh])
    await page.goto('/results')
    if (scenario.direct) {
      await page.getByRole('button', { name: '직접 쓸게요' }).click()
      await page.getByRole('textbox').fill(directText)
    } else {
      await page.getByRole('radio', { name: scenario.label!, exact: true }).click()
      await page.getByRole('radio', { name: scenario.scope === 'UNKNOWN' ? '철거는 아직 안 정해졌대요' : '철거해야 한대요', exact: true }).click()
    }
    const sent = page.waitForResponse(response => response.url() === `${BE_URL}/cases/results`
      && response.request().method() === 'POST')
    await page.getByRole('button', { name: '보내기', exact: true }).click()
    const accepted = await sent
    expect(accepted.ok()).toBe(true)
    const submitted = accepted.request().postDataJSON()
    expect(submitted).toEqual(scenario.direct
      ? { case_history_id: expect.any(Number), raw_input: directText }
      : { case_history_id: expect.any(Number), restoration_answer: {
        restoration_scope: scenario.scope,
        demolition_required: scenario.scope === 'UNKNOWN' ? 'UNKNOWN' : 'REQUIRED',
      } })
    const { case_history_id: historyId } = await accepted.json()
    let result: { result: string; questions_for_user?: string[] }
    await expect(async () => {
      const response = await request.get(`${BE_URL}/cases/results/status?case_history_id=${historyId}`, { headers })
      expect(response.ok()).toBe(true)
      result = await response.json()
      expect(result.result).toBe(scenario.asks ? 'NEEDS_MORE_INFO' : scenario.scope === 'UNKNOWN' ? 'NO_CHANGE' : 'UPDATED')
    }).toPass({ timeout: 30_000 })
    if (scenario.asks) {
      expect(result!.questions_for_user).toEqual([detailQuestion])
      await expect(page.getByRole('textbox', { name: detailQuestion, exact: true })).toBeVisible()
    } else {
      await expect(page).toHaveURL(/\/replan\?history=/)
      await expect(page.getByRole('textbox')).toHaveCount(0)
    }
    await page.reload()
    if (scenario.asks) await expect(page.getByRole('textbox', { name: detailQuestion, exact: true })).toBeVisible()
    else {
      await expect(page).toHaveURL(new RegExp(`/replan\\?history=${historyId}$`))
      await expect(page.getByRole('button', { name: scenario.scope === 'UNKNOWN' ? '홈으로' : '맞아요', exact: true })).toBeVisible()
    }
    const saved = databaseState(historyId)
    expect(saved.source).toBe('USER_INPUT')
    expect(saved.restoration_answer).toEqual(scenario.direct ? null : submitted.restoration_answer)
    expect(saved.raw_input).toBe(scenario.direct ? directText : [
      { FULL: '원상복구 범위는 전부입니다.', PARTIAL: '원상복구 범위는 일부입니다.',
        NOT_REQUIRED: '원상복구는 필요하지 않습니다.', UNKNOWN: '원상복구 범위는 아직 확인하지 못했습니다.' }[scenario.scope],
      scenario.scope === 'UNKNOWN' ? '철거 필요 여부는 아직 확인하지 못했습니다.' : '철거가 필요합니다.',
    ].join('\n'))
    const reread = await (await request.get(`${BE_URL}/cases`, { headers })).json()
    expect(reread.case.restoration_scope).toBe(scenario.scope)
    expect(reread.case.restoration_scope_detail).toBe(scenario.known || scenario.direct ? '카운터' : null)
    expect(reread.case.demolition_required).toBe(scenario.scope === 'UNKNOWN' ? 'UNKNOWN' : 'REQUIRED')
    expect(await page.locator('body').innerText()).not.toContain('010-1234-5678')
    if (scenario.direct) {
      // 같은 Case에서 한 번 더 실제 진행 보고→상태 반영→다음 판단을 이어간다.
      await page.goto('/results')
      const progressText = '원상복구 작업을 시작했습니다.'
      // 범위를 알린 뒤 할 일은 철거 준비 확인이라 [준비했어요] 버튼이 먼저 뜬다. 진행 보고는 직접 쓴다
      await page.getByRole('button', { name: '직접 쓸게요', exact: true }).click()
      await page.getByRole('textbox').fill(progressText)
      const next = page.waitForResponse(response => response.url() === `${BE_URL}/cases/results`
        && response.request().method() === 'POST')
      await page.getByRole('button', { name: '보내기', exact: true }).click()
      const nextAccepted = await next
      expect(nextAccepted.ok()).toBe(true)
      const { case_history_id: nextId } = await nextAccepted.json()
      await expect(page).toHaveURL(new RegExp(`/replan\\?history=${nextId}$`))
      await page.reload()
      await expect(page.getByRole('button', { name: '맞아요', exact: true })).toBeVisible()
      const nextCase = await (await request.get(`${BE_URL}/cases`, { headers })).json()
      expect(nextCase.case.id).toBe(caseId)
      expect(nextCase.case.restoration_status).toBe('IN_PROGRESS')
      expect(nextCase.judgment_status).toBe('DONE')
      expect(databaseState(nextId)).toMatchObject({ source: 'USER_INPUT', raw_input: progressText })
    }
  })
}

// 새 Python 세션으로 격리 MySQL을 읽어 HTTP 응답뿐 아니라 실제 저장값도 대조한다.
// knownDetail은 알려진 세부 답변을 준비하는 테스트 setup일 때만 쓴다.
function databaseState(id: number, knownDetail = false) {
  return JSON.parse(execFileSync(process.env.E2E_PYTHON ?? 'python', ['-c', `
import json, os, sys
from sqlmodel import Session, create_engine
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
with Session(create_engine(os.environ['E2E_DATABASE_URL'])) as session:
    if sys.argv[2] == 'true':
        row = session.get(Case, int(sys.argv[1]))
        row.restoration_scope_detail = '카운터'
        session.add(row)
        session.commit()
        print('{}')
    else:
        row = session.get(CaseHistory, int(sys.argv[1]))
        print(json.dumps(dict(source=row.source, restoration_answer=row.restoration_answer, raw_input=row.raw_input)))
`, String(id), String(knownDetail)], { cwd: '../backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf-8' }))
}
