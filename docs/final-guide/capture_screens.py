"""Capture the actual local React pages with the repository's preview fixtures."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'images'
BASE = 'http://127.0.0.1:5173'
ANSWERS = dict(business='PERSONAL_CAFE', franchise=False,
    situations=['LEASE', 'STAFF', 'LOAN', 'CONTRACT'], paysRent=True,
    restorationClause='EXISTS', fullTimeCount=1, partTimeCount=1,
    hadEmployees=True, insurances=['PENSION', 'HEALTH', 'EMPLOYMENT', 'INDUSTRIAL_ACCIDENT'], closure='THIS_MONTH')

async def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    records = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless=True)
        ctx = await browser.new_context(viewport={'width': 402, 'height': 874}, device_scale_factor=2, reduced_motion='reduce', locale='ko-KR')
        page = await ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        async def snap(name, url=None, setup=None, action=None):
            if url:
                await page.goto(BASE + url, wait_until='networkidle')
            if setup:
                await page.evaluate(setup)
                await page.reload(wait_until='networkidle')
            if action:
                await action()
            await page.evaluate('document.fonts.ready')
            await page.wait_for_timeout(350)
            if await page.locator('body').evaluate('(el) => el.scrollHeight') > 950:
                await page.screenshot(path=str(ASSETS / f'{name}-full.png'), full_page=True, animations='disabled')
            await page.screenshot(path=str(ASSETS / f'{name}.png'), full_page=False, animations='disabled')
            record = dict(id=name, url=page.url, path=f'images/{name}.png', text=(await page.locator('body').inner_text())[:5000])
            records.append(record)
            print(name, page.url, flush=True)
        await snap('01-login', '/login')
        await page.evaluate("sessionStorage.setItem('reborn:access-token', 'mock-session')")
        for step in ['biz', 'situ', 'rent', 'restore', 'staff', 'insurance', 'date']:
            setup = '(a) => sessionStorage.setItem("reborn:diagnosis", JSON.stringify({state:{answers:a},version:0}))'
            await page.evaluate(setup, ANSWERS)
            await snap(f'02-diagnosis-{step}', f'/cases/new?mock=no-case&step={step}')
        alternate = dict(ANSWERS, business='RESTAURANT', situations=['LEASE'], fullTimeCount=0, partTimeCount=0, hadEmployees=False)
        for step in ['franchise', 'hadStaff']:
            await page.evaluate(setup, alternate)
            await snap(f'02-diagnosis-{step}', f'/cases/new?mock=no-case&step={step}')
        for name,url in [
            ('03-creating','/cases/new?mock=creating'),
            ('04-home','/case?mock=done'),('05-task','/task?mock=done'),
            ('06-results-text','/results?mock=done'),('07-results-choice','/results?mock=result-choice'),
            ('08-confirm','/confirm?mock=conflict'),('09-replan','/replan?mock=done'),
            ('10-replan-unchanged','/replan?mock=no-change'),('11-roadmap','/roadmap?mock=roadmap'),
            ('12-checklist','/roadmap/notify_employees?mock=roadmap'),
            ('13-attachment','/roadmap/before_photo?mock=roadmap'),
            ('14-support-result','/roadmap/support_approval?mock=roadmap'),
            ('15-closure','/roadmap/closure_submission?mock=roadmap'),
            ('16-deposit','/roadmap/deposit_settlement?mock=roadmap'),
            ('17-docs','/docs?mock=docs'),('18-docs-issues','/docs/check?mock=docs-issues'),
            ('19-docs-complete','/docs/check?mock=docs-complete'),('20-package','/docs/done?mock=docs-complete'),
            ('21-log','/log?mock=done'),('22-notifications','/notifications?mock=done'),
            ('23-pending','/case?mock=pending'),('24-more-info','/case?mock=more-info'),
            ('25-failed-retry','/case?mock=judgment-failed'),('26-failed-detail','/case?mock=judgment-failed-detail'),
            ('27-failed-service','/case?mock=judgment-failed-service'),('28-conflict-home','/case?mock=judgment-conflict'),
            ('29-completed','/case?mock=completed'),('30-unsupported','/roadmap?mock=roadmap-unsupported'),
            ('31-answer','/results?mock=more-info'),('32-pending-long','/case?mock=pending-long'),
            ('33-log-empty','/log?mock=logs-empty'),('34-check-blocked','/roadmap/closure_certificate?mock=roadmap')]:
            await snap(name,url)
        await snap('35-doc-upload','/docs?mock=docs',action=lambda:page.get_by_role('button',name='서류 올리기',exact=True).click())
        await snap('36-doc-confirm','/docs?mock=docs',action=lambda:page.get_by_role('button',name='철거 전 사진 확인하기',exact=True).click())
        await snap('37-check-applicant','/docs/check?mock=docs',action=lambda:page.get_by_role('button',name='점검 시작하기').click())
        await page.goto(BASE+'/results?mock=done',wait_until='networkidle')
        await page.get_by_role('textbox').fill('카운터랑 싱크대는 빼고, 간판도 떼야 한대요. 바닥 타일은 그대로 둬도 된대요.')
        await snap('38-result-filled')
        await page.get_by_role('button',name='보내기',exact=True).click()
        await page.wait_for_url('**/replan**')
        await snap('39-understood')
        (ROOT/'screenshots.json').write_text(json.dumps(dict(mode='local preview fixtures',base=BASE,viewport=[402,874],records=records,page_errors=errors),ensure_ascii=False,indent=2))
        await browser.close()

if __name__=='__main__':
    asyncio.run(main())
