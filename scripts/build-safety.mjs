import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync, copyFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pages, questions, latestUpdates } from '../docs/safety/content.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = join(root, 'docs/safety')
const destination = join(root, 'frontend/public/safety')
const e = (s = '') => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const url = id => id === 'home' ? '/safety/' : `/safety/${id}/`
const arrow = '<span aria-hidden="true">↗</span>'
const iconPaths = {
  choice: '<path d="M12 38h30M28 12v38M28 12l-9 9m9-9 9 9M12 38l7-7m-7 7 7 7M42 38l-7-7m7 7-7 7"/>',
  document: '<path d="M17 7h23l9 9v40H17zM39 7v12h10M25 30h16M25 38h16M25 46h9"/>',
  shield: '<path d="M32 6l21 9v17c0 13-21 24-21 24S11 45 11 32V15zM22 31l7 7 14-15"/>',
  lock: '<rect x="13" y="27" width="38" height="29" rx="5"/><path d="M21 27V17a11 11 0 0 1 22 0v10M32 38v8"/>',
  path: '<path d="M10 51h32a10 10 0 0 0 0-20H24a10 10 0 0 1 0-20h27M44 4l7 7-7 7"/><circle cx="10" cy="51" r="4"/>',
}
const icon = name => `<svg class="line-icon" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${iconPaths[name] || iconPaths.document}</svg>`
const link = (title, href, className = 'text-link') => `<a class="${className}" href="${e(href)}">${e(title)} ${arrow}</a>`
const heading = text => e(text).replace(/\n/g, '<br>')
const faqs = items => items.map((q, i) => `<details class="faq" data-category="${e(q.category)}"><summary><span class="question-mark" aria-hidden="true">Q.</span><span>${e(q.question)}</span><span class="plus" aria-hidden="true"></span></summary><div class="faq-answer"><p>${e(q.answer)}</p>${link('자세히 알아보기', q.link)}</div></details>`).join('')
const featureScreens = [
  { id: '2026-11-09-action-done', title: '준비 확인 버튼' },
  { id: '2026-11-09-procedures-completed', title: '절차 안내 종료 화면' },
  { id: '2026-11-09-my-info', title: '내 정보 화면' },
]
const mediaFiles = ['brand-intro.mp4', 'brand-intro-poster.jpg']

function home() {
  return `<section class="brand-hero container" aria-labelledby="hero-title">
    <p class="eyebrow">RE:BORN 안심가이드</p>
    <h1 id="hero-title">가게의 마무리도,<br>사장님의 다음 시작도.</h1>
    <div class="hero-film" data-motion="paused">
      <video class="brand-video" width="1920" height="1080" muted playsinline loop preload="metadata" poster="/safety/assets/brand-intro-poster.jpg" aria-describedby="film-description">
        <source src="/safety/assets/brand-intro.mp4" type="video/mp4">
        <p>마무리는 차근차근. 다음 시작은 사장님답게.</p>
      </video>
      <button class="film-toggle" type="button" aria-label="소개 영상 재생" aria-pressed="false"><span class="film-control-icon" aria-hidden="true">▶</span><span class="film-control-label">영상 재생</span></button>
    </div>
    <p id="film-description" class="sr-only">가게를 정리하려는데 무엇부터 해야 할까요? 지금 확인할 일부터 하나씩 살펴봐요. 마무리는 차근차근. 다음 시작은 사장님답게. 리본 소개 영상입니다.</p>
    <a class="scroll-cue" href="#home-updates">리본의 이용 안내 살펴보기 <span aria-hidden="true">↓</span></a>
  </section>
  <section id="home-updates" class="feature-section container" aria-labelledby="features-title">
    <header class="feature-intro"><p class="eyebrow">리본과 함께</p><h2 id="features-title">더 쉽게 답하고,<br>마무리까지 확인하도록.</h2></header>
    <div class="feature-list">${latestUpdates.map((item, i) => `<article class="feature-panel ${e(item.tone)}" aria-labelledby="feature-${i + 1}">
      <div class="feature-copy"><p class="feature-category">${e(item.category)}</p><h3 id="feature-${i + 1}">${heading(item.title)}</h3><p class="feature-description">${e(item.text)}</p><a class="feature-link" href="${e(item.href)}" aria-label="${e(item.category)} 자세히 보기">자세히 보기 <span aria-hidden="true">→</span></a></div>
      <figure class="feature-media"><span class="feature-number" aria-hidden="true">0${i + 1}</span><div class="feature-device"><img src="/safety/assets/${e(featureScreens[i].id)}.png" alt="${e(featureScreens[i].title)} 미리보기" loading="lazy" width="390" height="844"></div><figcaption>미리보기 화면 · 2026.11.09</figcaption></figure>
    </article>`).join('')}</div>
  </section>`
}

function detail(page) {
  const categories = ['전체', ...new Set(questions.map(q => q.category))]
  const content = page.id === 'questions' ? `<div class="faq-filters" role="group" aria-label="질문 분류">${categories.map((c, i) => `<button type="button" data-filter="${e(c)}" aria-pressed="${i === 0}">${e(c)}</button>`).join('')}</div><p class="filter-status" role="status">${questions.length}개의 질문</p><div class="question-list">${faqs(questions)}</div>` : `<div class="article-layout"><aside class="contents"><strong>이 페이지에서</strong>${page.sections.map(s => `<a href="#${e(s.id)}">${e(s.title)}</a>`).join('')}</aside><div class="article-body">${page.sections.map((s, i) => `<section id="${e(s.id)}"><span class="small-number">0${i + 1}</span><h2>${e(s.title)}</h2><p>${e(s.text)}</p>${s.steps ? `<ol class="process">${s.steps.map(t => `<li>${e(t)}</li>`).join('')}</ol>` : ''}${s.links ? `<div class="article-links">${s.links.map(([title, href]) => link(title, href)).join('')}</div>` : ''}</section>`).join('')}</div></div>`
  return `<div class="container"><nav class="breadcrumb" aria-label="현재 위치"><a href="/safety/">안심가이드</a><span aria-hidden="true">/</span><span>${e(page.nav)}</span></nav><header class="page-heading"><div><p class="eyebrow">${e(page.eyebrow)}</p><h1>${heading(page.title)}</h1><p>${e(page.description)}</p></div><div class="heading-icon">${icon(page.icon)}</div></header>${content}<nav class="related-pages" aria-label="함께 살펴보기">${link('안심가이드 홈', '/safety/')}${link(page.id === 'questions' ? '리본의 운영철학' : '사례와 질문', page.id === 'questions' ? url('philosophy') : url('questions'))}</nav></div>`
}

export function buildSafety({ check, contract, documentationIds, documentationPages }) {
  const ids = new Set(pages.map(p => p.id))
  if (ids.size !== pages.length) throw new Error('안심가이드 페이지가 중복됩니다.')
  if (latestUpdates.length !== featureScreens.length) throw new Error('홈 안내와 화면 자료 수가 다릅니다.')
  for (const file of mediaFiles) if (!existsSync(join(source, 'media', file))) throw new Error(`안심가이드 영상 자료가 없습니다: ${file}`)
  for (const screen of featureScreens) if (!existsSync(join(root, 'docs/developers/images', `${screen.id}.png`))) throw new Error(`안심가이드 미리보기 자료가 없습니다: ${screen.id}`)
  const built = new Map(), index = []
  for (const page of pages) {
    for (const path of page.sources) if (!existsSync(join(root, path))) throw new Error(`안심가이드 구현 근거가 없습니다: ${path}`)
    const main = page.id === 'home' ? home() : detail(page)
    const nav = pages.filter(p => p.id !== 'home').map(p => `<a href="${url(p.id)}"${page.id === p.id ? ' aria-current="page"' : ''}>${e(p.nav)}</a>`).join('')
    const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="${e(page.description)}"><meta name="theme-color" content="#c3410c"><title>${e(page.nav === '홈' ? '가게의 마무리도, 사장님의 다음 시작도' : page.nav)} | 리본 안심가이드</title><link rel="icon" type="image/svg+xml" href="/safety/assets/reborn-hammer.svg"><link rel="stylesheet" href="/safety/assets/safety.css"><script src="/safety/assets/safety.js" defer></script></head><body data-page="${e(page.id)}"><a class="skip-link" href="#main">본문 바로가기</a><header class="site-header"><div class="header-inner"><a class="brand" href="/safety/" aria-label="리본 안심가이드 홈"><img src="/safety/assets/reborn-hammer.svg" width="26" height="26" alt=""><strong>reborn</strong><span>안심가이드</span></a><nav id="site-nav" class="site-nav" aria-label="주 메뉴">${nav}</nav><div class="header-tools"><button class="search-open icon-button" aria-label="안심가이드 검색" aria-haspopup="dialog"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="10.5" cy="10.5" r="7.5"/><path d="m16 16 5 5"/></svg></button><button class="menu-toggle icon-button" aria-label="메뉴 열기" aria-controls="site-nav" aria-expanded="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/></svg></button></div></div></header><main id="main" tabindex="-1">${main}</main><footer class="site-footer"><div class="container"><div class="footer-top"><a class="brand" href="/safety/"><strong>reborn</strong><span>안심가이드</span></a><p>차근차근 정리하고,<br>다음 시작을 준비할 수 있도록.</p></div><nav class="footer-nav" aria-label="하단 메뉴">${nav}<a href="/developers/">개발 문서 ↗</a><a href="/">서비스로 ↗</a></nav><div class="footer-bottom"><span>© RE:BORN Team · 카카오테크 캠퍼스</span><span>안내 확인 ${e(contract.checked_at.slice(0, 10))}</span></div><p class="footer-note">현재 서비스의 원칙과 이용 방법을 설명하는 안내입니다. 이용약관이나 개인정보처리방침을 대신하지 않습니다.</p></div></footer><dialog class="search-dialog" aria-label="안심가이드 검색"><form method="dialog" class="search-heading"><strong>어떤 내용이 궁금하세요?</strong><button class="icon-button search-close" aria-label="검색 닫기">×</button></form><label for="safety-search" class="sr-only">검색어</label><input id="safety-search" type="search" placeholder="운영철학, 서류, 개인정보를 검색해 보세요" autocomplete="off"><p id="search-status" role="status"></p><ul id="search-results"></ul></dialog><button class="to-top" type="button" aria-label="맨 위로">↑</button></body></html>`
    built.set(page.id, html)
    index.push({ title: page.nav === '홈' ? '리본 안심가이드' : page.nav, description: page.description, url: url(page.id), text: main.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ') })
  }
  for (const [id, html] of built) {
    const anchors = [...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1])
    if (new Set(anchors).size !== anchors.length) throw new Error(`안심가이드 앵커 중복: ${id}`)
    for (const m of html.matchAll(/href="([^\"]+)"/g)) {
      const parsed = new URL(m[1], `https://reborn.invalid${url(id)}`)
      if (parsed.origin !== 'https://reborn.invalid') continue
      if (parsed.pathname.startsWith('/safety/') && !parsed.pathname.includes('/assets/')) {
        const target = parsed.pathname.replace(/^\/safety\/?/, '').replace(/\/$/, '') || 'home'
        if (!built.has(target) || (parsed.hash && !built.get(target).includes(`id="${decodeURIComponent(parsed.hash.slice(1))}"`))) throw new Error(`안심가이드 링크 누락: ${m[1]}`)
      } else if (parsed.pathname.startsWith('/developers/ko/') && !documentationIds.has(parsed.pathname.replace('/developers/ko/', '').replace(/\/$/, ''))) throw new Error(`개발 문서 링크 누락: ${m[1]}`)
    }
  }
  for (const html of documentationPages.values()) for (const m of html.matchAll(/href="\/safety\/([^"#]*)(?:#([^"]+))?"/g)) {
    const target = m[1].replace(/\/$/, '') || 'home'
    if (!built.has(target) || (m[2] && !built.get(target).includes(`id="${m[2]}"`))) throw new Error(`개발 문서에서 연결한 안심가이드가 없습니다: ${target}`)
  }
  if (!check) {
    rmSync(destination, { recursive: true, force: true })
    mkdirSync(join(destination, 'assets'), { recursive: true })
    for (const [id, html] of built) { const dir = id === 'home' ? destination : join(destination, id); mkdirSync(dir, { recursive: true }); writeFileSync(join(dir, 'index.html'), html) }
    for (const file of ['safety.css', 'safety.js']) copyFileSync(join(source, file), join(destination, 'assets', file))
    copyFileSync(join(root, 'frontend/src/assets/brand/reborn-hammer.svg'), join(destination, 'assets/reborn-hammer.svg'))
    for (const file of mediaFiles) copyFileSync(join(source, 'media', file), join(destination, 'assets', file))
    for (const screen of featureScreens) copyFileSync(join(root, 'docs/developers/images', `${screen.id}.png`), join(destination, 'assets', `${screen.id}.png`))
    writeFileSync(join(destination, 'search-index.json'), JSON.stringify(index))
    writeFileSync(join(destination, 'manifest.json'), JSON.stringify({ checked_at: contract.checked_at, source_revision: contract.source_revision, pages: pages.map(p => ({ id: p.id, title: p.nav, url: url(p.id) })) }, null, 2))
  }
  console.log(`안심가이드 ${check ? '검사 통과' : '생성 완료'}: ${pages.length}개 페이지, 질문 ${questions.length}개.`)
}
