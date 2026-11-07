import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { BE_URL, TOKEN_FILE } from '../playwright.config.ts'

test('같은 Case의 이체 누락을 보완·확인하고 점검한 뒤 ZIP을 받는다', async ({ page, request }) => {
  test.setTimeout(120_000)
  const { document_member: member, document_directory: directory, document_files: files } = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'))
  const headers = { 'Access-Token': member.access_token }
  // #230 진단 화면의 이름 입력을 완료했다고 보지 않는다. 알려진 상호는 합성 Case 준비값이다.
  const created = await request.post(`${BE_URL}/cases`, { headers, data: {
    store_name: '봄날개인카페', business_type: 'CAFE', franchise_status: false,
    lease_status: 'LEASED_PAID', employee_count: 0, had_employees: false,
    pension_enrolled: false, health_insurance_enrolled: false,
    employment_insurance_enrolled: false, industrial_accident_insurance_enrolled: false,
  } })
  expect(created.ok()).toBe(true)
  const { id: caseId } = await created.json()
  await page.addInitScript(([access, refresh]) => {
    sessionStorage.setItem('reborn:access-token', access)
    sessionStorage.setItem('reborn:refresh-token', refresh)
  }, [member.access_token, member.refresh_token])
  await page.goto('/docs')

  async function uploadAndConfirm(kind: string) {
    await page.getByRole('button', { name: '서류 올리기', exact: true }).click()
    const pending = page.waitForResponse(r => r.url() === `${BE_URL}/cases/documents` && r.request().method() === 'POST')
    await page.getByLabel('파일에서 고르기', { exact: true }).setInputFiles(files[kind])
    const uploaded = await pending
    expect(uploaded.ok()).toBe(true)
    const body = await uploaded.json()
    const record = body.documents.find((d: { kind: string }) => d.kind === kind)
    expect(record.needs_confirmation).toBe(true)
    expect(body.check).toBeNull()
    await page.getByRole('button', { name: `${record.kind_label} 확인하기`, exact: true }).click()
    const confirmed = page.waitForResponse(r => r.url().endsWith(`/${record.document_id}/confirm`))
    await page.getByRole('button', { name: '맞아요, 확인했어요', exact: true }).click()
    const saved = await confirmed
    expect(saved.ok()).toBe(true)
    const latest = (await saved.json()).documents.find((d: { document_id: string }) => d.document_id === record.document_id)
    expect(latest.needs_confirmation).toBe(false)
    expect(latest.confirmed_fields).toEqual(Object.fromEntries(record.fields.map((f: { name: string; value: string }) => [f.name, f.value])))
  }
  async function check() {
    await page.getByRole('button', { name: '정산 서류 점검하기', exact: true }).click()
    await page.getByRole('button', { name: '점검 시작하기', exact: true }).click()
    await page.getByLabel('신청인 이름', { exact: true }).fill('김리본')
    await page.getByLabel('실제 폐업일 (선택)', { exact: true }).fill('2026-10-31')
    const pending = page.waitForResponse(r => r.url().endsWith('/cases/documents/check') && r.request().method() === 'POST')
    await page.getByRole('button', { name: '점검하기', exact: true }).click()
    const response = await pending
    expect(response.ok()).toBe(true)
    return response.json()
  }
  for (const kind of Object.keys(files).filter(kind => kind !== 'TRANSFER')) await uploadAndConfirm(kind)
  const missing = await check()
  expect(missing.check.status).toBe('ISSUES')
  expect(missing.check.issues.map((i: { code: string }) => i.code)).toEqual(['MISSING_TRANSFER'])
  await expect(page.getByText('정산 점검 목록에서 빠진 서류: 이체확인증', { exact: true })).toBeVisible()
  expect((await request.get(`${BE_URL}/cases/documents/settlement.zip`, { headers })).status()).toBe(422)
  await page.reload()
  await expect(page.getByRole('button', { name: '서류함으로 가기', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '서류함으로 가기', exact: true }).click()
  await uploadAndConfirm('TRANSFER')
  const complete = await check()
  expect(complete.documents).toHaveLength(6)
  expect(complete.check.status).toBe('COMPLETE')
  expect(complete.check.issues).toEqual([])
  await page.getByRole('button', { name: '결과 보기', exact: true }).click()
  await page.reload()
  await expect(page.getByRole('button', { name: '파일 받기', exact: true })).toBeEnabled()
  const pendingDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '파일 받기', exact: true }).click()
  const download = await pendingDownload
  expect(download.suggestedFilename()).toBe('settlement.zip')
  const stored = JSON.parse(execFileSync(process.env.E2E_PYTHON ?? 'python', ['-c', `
import json, os, sys
import re
from pathlib import Path
from zipfile import ZipFile
import pymupdf
from sqlmodel import Session, create_engine
from app.be.models.case import Case
from app.be.services.document import document_case_id
with Session(create_engine(os.environ['E2E_DATABASE_URL'])) as session:
    case = session.get(Case, int(sys.argv[2]))
    assert case.store_name == '봄날개인카페'
    context = json.loads((Path(sys.argv[1]) / str(document_case_id(case)) / 'case_documents.json').read_text())
with pymupdf.open(Path(sys.argv[1]) / 'CONSTRUCTION_STATEMENT.pdf') as source:
    assert '8001011234567' in re.sub(r'[\\s-]', '', ''.join(page.get_text() for page in source))
with ZipFile(sys.argv[3]) as archive:
    assert archive.testzip() is None
    assert len(archive.namelist()) == 8
    assert {name.rsplit('_', 1)[0] for name in archive.namelist() if name.endswith('.pdf') and name != '제출안내.pdf'} == {
        'CONSTRUCTION_STATEMENT', 'TAX_INVOICE', 'BEFORE_PHOTO', 'AFTER_PHOTO', 'CLOSURE_CERTIFICATE', 'TRANSFER'}
    for name in archive.namelist():
        if name.endswith('.pdf'):
            with pymupdf.open(stream=archive.read(name), filetype='pdf') as pdf:
                assert '1234567' not in re.sub(r'[\\s-]', '', ''.join(page.get_text() for page in pdf))
    report = json.loads(archive.read('점검결과.json'))
    assert report['status'] == 'COMPLETE' and report['issues'] == []
print(json.dumps(dict(ids=[d['document_id'] for d in context['documents']], status=context['document_check']['status'])))
`, directory, String(caseId), (await download.path())!], { cwd: '../backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf-8' }))
  expect(stored.status).toBe('COMPLETE')
  expect(stored.ids.sort()).toEqual(complete.documents.map((d: { document_id: string }) => d.document_id).sort())
})
