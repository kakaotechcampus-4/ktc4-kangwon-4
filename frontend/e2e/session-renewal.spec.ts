import { type APIRequestContext, type Page, expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { BE_URL, TOKEN_FILE } from '../playwright.config.ts'

// e2e_server.py의 가짜 Info가 받는 직접 입력 문장(restoration-answer.spec.ts와 같다)
const DIRECT_TEXT = '원상복구는 일부이고 카운터만 철거해야 합니다.'
// 서버가 받지 않는 토큰. 만료·위조 모두 서버에서는 같은 401이다
const BROKEN = 'expired.token.value'

type Member = { access_token: string; refresh_token: string }

/**
 * 로그인 토큰(30분)이 만료되면 화면이 /reissue로 새 토큰을 받아 하던 요청을 이어 간다(#210·#212).
 * 서버는 Refresh 토큰을 쓸 때마다 새것으로 바꾸고 마지막 하나만 기억한다(auth_service.reissue).
 */
test.describe('로그인 만료', () => {
  test('Access 토큰만 만료되면 새로 받아 홈을 그대로 보여 주고 Refresh도 바뀐다', async ({ page, request }) => {
    const member = sessionMember(0)
    const action = await signUp(request, member)
    await signIn(page, BROKEN, member.refresh_token)

    const reissued = page.waitForResponse(r => r.url() === `${BE_URL}/reissue` && r.request().method() === 'POST')
    await page.goto('/case')
    expect((await reissued).ok()).toBe(true)

    await expect(page.getByRole('heading', { level: 2, name: action })).toBeVisible()
    const stored = await page.evaluate(() => [sessionStorage.getItem('reborn:access-token'), sessionStorage.getItem('reborn:refresh-token')])
    expect(stored[0]).not.toBe(BROKEN)
    // 서버가 기억하는 Refresh가 화면이 들고 있는 새 값으로 바뀌었다. 옛 값은 더 못 쓴다
    expect(stored[1]).not.toBe(member.refresh_token)
    expect(savedRefreshToken(member)).toBe(stored[1])
  })

  test('글을 쓰는 중에 만료돼도 보내기를 누르면 새 토큰으로 같은 글이 접수된다', async ({ page, request }) => {
    const member = sessionMember(1)
    await signUp(request, member)
    await signIn(page, member.access_token, member.refresh_token)
    await page.goto('/results')
    await page.getByRole('button', { name: '직접 쓸게요', exact: true }).click()
    await page.getByRole('textbox').fill(DIRECT_TEXT)

    // 쓰는 사이에 30분이 지난 것처럼 Access 토큰만 망가뜨린다
    await page.evaluate(token => sessionStorage.setItem('reborn:access-token', token), BROKEN)
    const statuses: number[] = []
    page.on('response', r => {
      if (r.url() === `${BE_URL}/cases/results` && r.request().method() === 'POST') statuses.push(r.status())
    })
    const accepted = page.waitForResponse(r => r.url() === `${BE_URL}/cases/results`
      && r.request().method() === 'POST' && r.ok())
    await page.getByRole('button', { name: '보내기', exact: true }).click()
    const { case_history_id: historyId } = await (await accepted).json()

    // 처음 보낸 것은 401로 막히고, 재발급 뒤 한 번만 다시 보내 접수됐다
    expect(statuses).toEqual([401, 200])
    expect(savedInput(historyId)).toBe(DIRECT_TEXT)
    await expect(page).toHaveURL(new RegExp(`/replan\\?history=${historyId}$`))
  })

  test('Refresh 토큰까지 쓸 수 없으면 로그인 화면으로 보낸다', async ({ page, request }) => {
    const member = sessionMember(2)
    await signUp(request, member)
    await signIn(page, BROKEN, BROKEN)

    await page.goto('/case')

    await expect(page).toHaveURL(/\/login/)
    // 못 쓰는 토큰을 들고 있지 않는다
    expect(await page.evaluate(() => sessionStorage.getItem('reborn:access-token'))).toBeNull()
  })
})

function sessionMember(index: number): Member {
  return JSON.parse(readFileSync(TOKEN_FILE, 'utf-8')).session_members[index]
}

/** 가입하고 첫 판단이 끝날 때까지 기다린다. 첫 할 일 제목을 돌려준다 */
async function signUp(request: APIRequestContext, member: Member): Promise<string> {
  const headers = { 'Access-Token': member.access_token }
  const created = await request.post(`${BE_URL}/cases`, { headers, data: {
    business_type: 'CAFE', franchise_status: false, lease_status: 'LEASED_PAID', employee_count: 0,
  } })
  expect(created.ok()).toBe(true)
  let title = ''
  await expect(async () => {
    const body = await (await request.get(`${BE_URL}/cases`, { headers })).json()
    expect(body.judgment_status).toBe('DONE')
    title = body.next_action.title
  }).toPass({ timeout: 30_000 })
  return title
}

async function signIn(page: Page, access: string, refresh: string) {
  await page.addInitScript(([a, r]) => {
    // 새로고침·이동 때마다 다시 넣지 않는다. 화면이 받은 새 토큰을 덮으면 재발급을 볼 수 없다
    if (sessionStorage.getItem('e2e:signed-in')) return
    sessionStorage.setItem('e2e:signed-in', '1')
    sessionStorage.setItem('reborn:access-token', a)
    sessionStorage.setItem('reborn:refresh-token', r)
  }, [access, refresh])
}

// 새 Python 세션으로 격리 MySQL을 읽는다
function python(code: string, ...args: string[]) {
  return execFileSync(process.env.E2E_PYTHON ?? 'python', ['-c', code, ...args],
    { cwd: '../backend', env: { ...process.env, PYTHONPATH: '.' }, encoding: 'utf-8' }).trim()
}

function savedRefreshToken(member: Member) {
  return python(`
import os, sys, jwt
from sqlmodel import Session, create_engine
from app.be.models.member import Member
member_id = int(jwt.decode(sys.argv[1], options={'verify_signature': False})['sub'])
with Session(create_engine(os.environ['E2E_DATABASE_URL'])) as session:
    print(session.get(Member, member_id).refresh_token)
`, member.refresh_token)
}

function savedInput(historyId: number) {
  return python(`
import os, sys
from sqlmodel import Session, create_engine
from app.be.models.case_history import CaseHistory
with Session(create_engine(os.environ['E2E_DATABASE_URL'])) as session:
    print(session.get(CaseHistory, int(sys.argv[1])).raw_input)
`, String(historyId))
}
