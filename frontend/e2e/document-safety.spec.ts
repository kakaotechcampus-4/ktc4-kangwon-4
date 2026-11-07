import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { BE_URL, TOKEN_FILE } from '../playwright.config.ts'

const scenarios = [
  { decision: 'REFUSE', status: 422, title: '이 파일은 자동으로 읽지 않았어요.' },
  { decision: 'CRISIS_SUPPORT', status: 422, title: '지금 많이 힘드시다면, 혼자 견디지 않으셔도 돼요.' },
  { decision: 'UNAVAILABLE', status: 502, title: '서류를 읽지 못했어요.' },
]

for (const [index, scenario] of scenarios.entries()) {
  test(`서류 ${scenario.decision} 뒤에도 목록·점검을 지키고 재진입 시 재업로드를 요구하지 않는다`, async ({ page, request }) => {
    test.setTimeout(90_000)
    const { document_safety_members: members, document_files: files, document_safety_files: faults } = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'))
    const member = members[index]
    const headers = { 'Access-Token': member.access_token }
    expect((await request.post(`${BE_URL}/cases`, { headers, data: {
      store_name: '봄날개인카페', business_type: 'CAFE', franchise_status: false,
      lease_status: 'OWNED', employee_count: 0, had_employees: false,
      pension_enrolled: false, health_insurance_enrolled: false,
      employment_insurance_enrolled: false, industrial_accident_insurance_enrolled: false,
    } })).ok()).toBe(true)
    const uploaded = await request.post(`${BE_URL}/cases/documents`, { headers, multipart: {
      file: { name: 'kept-transfer.pdf', mimeType: 'application/pdf', buffer: readFileSync(files.TRANSFER) },
    } })
    expect(uploaded.ok()).toBe(true)
    const record = (await uploaded.json()).documents[0]
    expect((await request.post(`${BE_URL}/cases/documents/${record.document_id}/confirm`, { headers, data: {
      kind: record.kind,
      confirmed_fields: Object.fromEntries(record.fields.map((field: { name: string; value: string }) => [field.name, field.value])),
    } })).ok()).toBe(true)
    const checked = await request.post(`${BE_URL}/cases/documents/check`, { headers, data: {
      store_name: '봄날개인카페', applicant_name: '김리본', closure_date: '2026-10-31',
    } })
    expect(checked.ok()).toBe(true)
    const before = await checked.json()
    expect(before.check.status).toBe('ISSUES')
    await page.addInitScript(([access, refresh]) => {
      sessionStorage.setItem('reborn:access-token', access)
      sessionStorage.setItem('reborn:refresh-token', refresh)
    }, [member.access_token, member.refresh_token])
    await page.goto('/docs')
    await expect(page.getByText('kept-transfer.pdf', { exact: true })).toBeVisible()
    let uploads = 0
    page.on('request', request => {
      if (request.url() === `${BE_URL}/cases/documents` && request.method() === 'POST') uploads += 1
    })
    await page.getByRole('button', { name: '서류 올리기', exact: true }).click()
    const waiting = page.waitForResponse(response => response.url() === `${BE_URL}/cases/documents` && response.request().method() === 'POST')
    await page.getByLabel('파일에서 고르기', { exact: true }).setInputFiles(faults[scenario.decision])
    const response = await waiting
    expect(response.status()).toBe(scenario.status)
    if (scenario.status === 422) expect((await response.json()).detail.code).toBe(`AGENT_SAFETY_${scenario.decision}`)
    await expect(page.getByText(scenario.title, { exact: true })).toBeVisible()
    if (scenario.decision === 'CRISIS_SUPPORT') {
      await expect(page.getByRole('link', { name: '상담전화 109', exact: true })).toHaveAttribute('href', 'tel:109')
    }
    if (scenario.status === 422) {
      await expect(page.getByText('서류를 읽지 못했어요.', { exact: true })).toHaveCount(0)
      await expect(page.getByText('잠시 뒤 다시 올려 주세요.', { exact: false })).toHaveCount(0)
    }
    expect(await (await request.get(`${BE_URL}/cases/documents`, { headers })).json()).toEqual(before)
    await expect(page.getByRole('listitem').filter({ hasText: 'kept-transfer.pdf' })).toHaveCount(1)
    await page.reload()
    await expect(page.getByText('kept-transfer.pdf', { exact: true })).toBeVisible()
    await expect(page.getByText('점검에서 확인할 것이 있어요.', { exact: true })).toBeVisible()
    await page.goto('/case')
    await page.goto('/docs')
    await expect(page.getByText('kept-transfer.pdf', { exact: true })).toBeVisible()
    await expect(page.getByText('읽는 데 시간이 오래 걸려 기다림이 끊겼어요.', { exact: true })).toHaveCount(0)
    await expect(page.getByText('같은 파일을 한 번 더 올려 주시면 이어서 받아요.', { exact: true })).toHaveCount(0)
    expect(uploads).toBe(1)
    expect(await (await request.get(`${BE_URL}/cases/documents`, { headers })).json()).toEqual(before)
  })
}
