import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { BE_URL, TOKEN_FILE } from '../playwright.config.ts'

// 실제 화면·HTTP·MySQL·서류 저장·판단 그래프를 잇는다. 모델 해석만 합성 답변이다.
async function prepare(page: Page, request: APIRequestContext, index: number) {
  const tokens = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'))
  const member = tokens.replan_members[index]
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
  }).toPass({ timeout: 30_000 })
  await page.addInitScript(([access, refresh]) => {
    sessionStorage.setItem('reborn:access-token', access)
    sessionStorage.setItem('reborn:refresh-token', refresh)
  }, [member.access_token, member.refresh_token])
  await page.goto('/docs')
  return { caseId, headers, directory: tokens.document_directory,
    files: { ...tokens.replan_files, TRANSFER: tokens.document_files.TRANSFER } }
}

async function upload(page: Page, file: string, confirm = true) {
  await page.getByRole('button', { name: '서류 올리기', exact: true }).click()
  const pending = page.waitForResponse(r => r.url() === `${BE_URL}/cases/documents` && r.request().method() === 'POST')
  await page.getByLabel('파일에서 고르기', { exact: true }).setInputFiles(file)
  const response = await pending
  expect(response.ok()).toBe(true)
  const body = await response.json()
  const record = body.documents.find((d: { filename: string }) => d.filename === basename(file))
  expect(record).toBeDefined()
  if (confirm && record.needs_confirmation) {
    await page.getByRole('button', { name: `${record.kind_label} 확인하기`, exact: true }).click()
    const confirmed = page.waitForResponse(r => r.url().endsWith(`/${record.document_id}/confirm`))
    await page.getByRole('button', { name: '맞아요, 확인했어요', exact: true }).click()
    const saved = await confirmed
    expect(saved.ok()).toBe(true)
    const reread = (await saved.json()).documents.find((d: { document_id: string }) => d.document_id === record.document_id)
    expect(reread.needs_confirmation).toBe(false)
    expect(reread.confirmed_fields).toEqual(Object.fromEntries(record.fields.map((f: { name: string; value: string }) => [f.name, f.value])))
  }
  return body.documents.length
}

async function documentJudgmentsDone(caseId: number, directory: string, count: number) {
  await expect(async () => {
    const saved = databaseState(caseId, directory)
    expect(saved.documents).toHaveLength(count)
    expect(saved.documents.every((h: { status: string }) => h.status === 'DONE')).toBe(true)
    expect(saved.histories.some((h: { status: string }) => h.status === 'PENDING')).toBe(false)
    expect(saved.scope).toBe('PARTIAL')
  }).toPass({ timeout: 30_000 })
}

test('확인한 조항이 바뀔 때만 재판단하고 같은 파일·같은 조항·금액 추가는 제외한다', async ({ page, request }) => {
  const { caseId, headers, directory, files } = await prepare(page, request, 0)
  await upload(page, files.LEASE, false)
  expect(databaseState(caseId, directory).documents).toHaveLength(0)
  await page.getByRole('button', { name: '임대차계약서 확인하기', exact: true }).click()
  const confirmed = page.waitForResponse(r => r.url().endsWith('/confirm'))
  await page.getByRole('button', { name: '맞아요, 확인했어요', exact: true }).click()
  expect((await confirmed).ok()).toBe(true)
  await documentJudgmentsDone(caseId, directory, 1)
  expect(await upload(page, files.LEASE)).toBe(1)
  expect(await upload(page, files.SAME_CLAUSE)).toBe(2)
  expect(await upload(page, files.TRANSFER)).toBe(3)
  expect(databaseState(caseId, directory).documents).toHaveLength(1)
  await upload(page, files.CHANGED_CLAUSE)
  await documentJudgmentsDone(caseId, directory, 2)
  const saved = databaseState(caseId, directory)
  expect(saved.documents[1].input).toContain('작업 전 보양한다.')
  expect(saved.uploads).toBe(4) // 같은 파일은 새 업로드 이력도 만들지 않는다.
  expect(saved.stored).toHaveLength(4)
  await page.reload()
  const reread = await (await request.get(`${BE_URL}/cases/documents`, { headers })).json()
  expect(reread.documents.map((d: { document_id: string }) => d.document_id).sort()).toEqual(saved.stored.sort())
})

test('판단 중 확인한 업로드를 보존하고 앞 판단 뒤 서류를 한 번 판단한다', async ({ page, request }) => {
  test.setTimeout(90_000)
  const { caseId, directory, files } = await prepare(page, request, 1)
  await upload(page, files.LEASE)
  await documentJudgmentsDone(caseId, directory, 1)
  await page.goto('/results')
  await page.getByRole('textbox').fill('원상복구 작업을 시작했습니다. 서류 대기 검증입니다.')
  const sent = page.waitForResponse(r => r.url() === `${BE_URL}/cases/results` && r.request().method() === 'POST')
  await page.getByRole('button', { name: '보내기', exact: true }).click()
  expect((await sent).ok()).toBe(true)
  try {
    await expect.poll(() => existsSync(join(directory, 'model-entered'))).toBe(true)
    await page.goto('/docs')
    await upload(page, files.CHANGED_CLAUSE)
    const held = databaseState(caseId, directory)
    expect(held.stored).toHaveLength(2)
    expect(held.uploads).toBe(2)
    expect(held.documents).toHaveLength(1)
    expect(held.histories.at(-1)).toMatchObject({ source: 'USER_INPUT', status: 'PENDING' })
    expect(held.baseline).toHaveLength(1)
  } finally {
    writeFileSync(join(directory, 'model-release'), '')
  }
  await documentJudgmentsDone(caseId, directory, 2)
  const saved = databaseState(caseId, directory)
  expect(saved.status).toBe('IN_PROGRESS')
  expect(saved.histories.slice(-2).map((h: { source: string }) => h.source)).toEqual(['USER_INPUT', 'DOCUMENT_SUBMITTED'])
  expect(saved.baseline.sort()).toEqual(saved.stored.sort())
  await page.reload()
  await expect(page.getByRole('button', { name: '임대차계약서 확인하기', exact: true })).toHaveCount(0)
})

test('충돌 대기 중 확인한 서류는 저장하고 사용자 선택이 끝나면 이어서 판단한다', async ({ page, request }) => {
  const { caseId, headers, directory, files } = await prepare(page, request, 2)
  await upload(page, files.LEASE)
  await documentJudgmentsDone(caseId, directory, 1)
  databaseState(caseId, directory, true) // 이전에 전부로 확인한 합성 기록만 준비한다.
  await page.goto('/results')
  // 이전 행동이 자유글이므로 실제 TEXT 계약으로 충돌을 만든다.
  await page.getByRole('textbox').fill('원상복구는 일부이고 카운터만 철거해야 합니다.')
  await page.getByRole('button', { name: '보내기', exact: true }).click()
  await expect(page).toHaveURL(/\/confirm$/)
  const conflicted = await (await request.get(`${BE_URL}/cases/results`, { headers })).json()
  expect(conflicted.judgment_status).toBe('CONFLICT')
  await page.goto('/docs')
  await upload(page, files.CHANGED_CLAUSE)
  const held = databaseState(caseId, directory)
  expect(held.stored).toHaveLength(2)
  expect(held.uploads).toBe(2)
  expect(held.documents).toHaveLength(1)
  expect(held.scope).toBe('FULL')
  expect(held.conflicts).toEqual(['PENDING'])
  expect(held.baseline).toHaveLength(1)
  await page.goto('/results')
  await expect(page).toHaveURL(/\/confirm$/)
  const proceed = page.getByRole('button', { name: '이대로 진행하기', exact: true })
  await expect(proceed).toBeDisabled()
  await page.getByRole('button', { name: /^이번에 말씀하신 것/ }).click()
  await proceed.click()
  await documentJudgmentsDone(caseId, directory, 2)
  const saved = databaseState(caseId, directory)
  expect(saved.conflicts).toEqual(['CONFIRMED'])
  expect(saved.histories.slice(-2).map((h: { source: string }) => h.source)).toEqual(['CONFLICT_DECISION', 'DOCUMENT_SUBMITTED'])
  expect(saved.histories.slice(-2).every((h: { status: string }) => h.status === 'DONE')).toBe(true)
  expect(saved.baseline.sort()).toEqual(saved.stored.sort())
  await page.goto('/docs')
  await page.reload()
  await expect(page.getByRole('button', { name: '임대차계약서 확인하기', exact: true })).toHaveCount(0)
})

// 새 DB 세션과 실제 서류 JSON을 함께 읽는다. 범위 준비 외에는 저장 경로를 대체하지 않는다.
function databaseState(caseId: number, directory: string, prepareConflict = false) {
  return JSON.parse(execFileSync(process.env.E2E_PYTHON ?? 'python', ['-c', `
import json, os, sys
from pathlib import Path
from sqlmodel import Session, create_engine, select
from app.be.models.case import Case
from app.be.models.case_history import CaseHistory
from app.be.models.case_document_history import CaseDocumentHistory
from app.be.models.evidence import ConflictReference
from app.be.services.document import document_case_id
with Session(create_engine(os.environ['E2E_DATABASE_URL'])) as session:
    case = session.get(Case, int(sys.argv[1]))
    if sys.argv[3] == 'true':
        case.restoration_scope = 'FULL'
        session.commit()
        print('{}')
    else:
        histories = session.exec(select(CaseHistory).where(CaseHistory.case_id == case.id).order_by(CaseHistory.id)).all()
        rows = [dict(id=h.id, source=h.source, status=h.judgment_status, input=h.raw_input) for h in histories]
        folder = Path(sys.argv[2]) / str(document_case_id(case))
        def ids(filename):
            return [d['document_id'] for d in json.loads((folder / filename).read_text())['documents']] if (folder / filename).is_file() else []
        uploads = session.exec(select(CaseDocumentHistory).where(CaseDocumentHistory.case_id == case.id, CaseDocumentHistory.action == 'UPLOADED')).all()
        conflicts = session.exec(select(ConflictReference.status).where(ConflictReference.case_id == case.id)).all()
        print(json.dumps(dict(scope=case.restoration_scope, status=case.restoration_status,
            histories=rows, documents=[h for h in rows if h['source'] == 'DOCUMENT_SUBMITTED'],
            uploads=len(uploads), stored=ids('case_documents.json'), baseline=ids('judged_documents.json'), conflicts=list(conflicts))))
`, String(caseId), directory, String(prepareConflict)], { cwd: '../backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf-8' }))
}
