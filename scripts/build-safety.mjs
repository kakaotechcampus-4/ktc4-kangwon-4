import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync, copyFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pages, principles, questions } from '../docs/safety/content.mjs'

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
const store = `<svg class="store-scene" viewBox="0 0 640 430" fill="none" aria-hidden="true"><ellipse cx="322" cy="390" rx="240" ry="18" fill="#A53406" opacity=".17"/><path d="M105 359c62-42 100 41 167 7s72-30 140-4 91 1 134-24" stroke="#FFD6B1" stroke-width="3" stroke-dasharray="9 11"/><g transform="rotate(-7 235 220)"><rect x="118" y="95" width="248" height="269" rx="14" fill="#FFF9EE"/><path d="M117 148h250l-20-53H137z" fill="#FAD6AD"/><path d="M132 148h28v39a14 14 0 0 1-28 0zm56 0h28v39a14 14 0 0 1-28 0zm56 0h28v39a14 14 0 0 1-28 0zm56 0h28v39a14 14 0 0 1-28 0z" fill="#C8460C"/><path d="M160 148h28v39a14 14 0 0 1-28 0zm56 0h28v39a14 14 0 0 1-28 0zm56 0h28v39a14 14 0 0 1-28 0zm56 0h28v39a14 14 0 0 1-28 0z" fill="#FFE8C9"/><rect x="146" y="222" width="106" height="94" rx="7" fill="#EEDCC7"/><path d="M146 269h106M199 222v94" stroke="#FFF9EE" stroke-width="5"/><path d="M279 234a21 21 0 0 1 42 0v130h-42z" fill="#B83D0B"/><circle cx="308" cy="290" r="3" fill="#FDE2BE"/><path d="M154 332h76" stroke="#C8B6A0" stroke-width="4" stroke-linecap="round"/></g><g transform="rotate(9 455 233)"><rect x="353" y="173" width="183" height="174" rx="11" fill="#FFF9EE"/><path d="M377 213h111M377 231h62M377 282h53" stroke="#DCC8B2" stroke-width="6" stroke-linecap="round"/><circle cx="484" cy="292" r="40" fill="#E1ECC7"/><path d="M466 290l12 12 23-24" stroke="#446136" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><path d="M384 154v37M423 154v37M462 154v37M501 154v37" stroke="#FFF9EE" stroke-width="8" stroke-linecap="round"/></g><circle cx="482" cy="87" r="30" fill="#F9CFA2"/><path d="M469 87h26M482 74v26" stroke="#C0460D" stroke-width="3" stroke-linecap="round"/><path d="M95 76l10 6-10 6-10-6zM561 223l10 6-10 6-10-6z" fill="#FFD9B3"/><path d="M375 46v19M366 55h19" stroke="#FFD9B3" stroke-width="3" stroke-linecap="round"/></svg>`

function home() {
  return `<section class="hero container"><p class="eyebrow">RE:BORN 안심가이드</p><h1>가게의 마무리도,<br>사장님의 내일도<br class="mobile-only"> 안심할 수 있도록.</h1><p class="hero-description">복잡한 폐업 준비 속에서도, 사장님의 선택과 정보를 소중히.<br>리본이 지키려는 원칙과 함께 확인할 것들을 소개해요.</p><div class="hero-poster"><div class="poster-copy"><span class="poster-label">다음 시작을 위한, 리본</span><p>정리는 차근차근.<br>선택은 사장님답게.</p><span class="poster-foot">가게의 마지막 단계까지 함께 살펴요.</span></div>${store}<div class="poster-stamp">당신의<br><strong>다음 시작</strong></div></div><a class="scroll-cue" href="#principles">리본의 약속 살펴보기 <span aria-hidden="true">↓</span></a></section><section id="principles" class="principles-section container"><div class="section-intro"><p class="eyebrow">우리의 약속</p><h2>도움이 되는 안내에는,<br>지켜야 할 원칙이 있어요.</h2>${link('운영철학 알아보기', url('philosophy'))}</div><div class="principle-grid">${principles.map((p, i) => `<article><span class="small-number">0${i + 1}</span>${icon(p.icon)}<h3>${e(p.title)}</h3><p>${e(p.text)}</p></article>`).join('')}</div></section><section class="story-section"><div class="container"><div class="section-intro"><p class="eyebrow">안심을 만드는 방법</p><h2>어떻게 돕는지,<br>알고 이용할 수 있도록.</h2></div><div class="story-grid"><a class="story-card peach" href="${url('guide')}"><span class="story-category">안심 이용 가이드</span><h3>다르게 이해했다면,<br>바로잡을 수 있어요.</h3><p>확인한 내용, 아직 모르는 내용.<br>사장님의 답을 함께 살펴요.</p><div class="story-art">${icon('choice')}<span class="art-note">확인하고, 다시 알려주기</span></div><span class="round-arrow" aria-hidden="true">↗</span></a><a class="story-card sage" href="${url('privacy')}"><span class="story-category">서류와 정보 보호</span><h3>서류 한 장에도,<br>소중한 정보가 있으니까.</h3><p>가림의 범위와 제출 파일을<br>함께 확인해요.</p><div class="story-art">${icon('lock')}<span class="art-note">필요한 정보만 차근차근</span></div><span class="round-arrow" aria-hidden="true">↗</span></a><a class="story-card lavender" href="${url('ai')}"><span class="story-category">AI와 검수</span><h3>기술의 역할도,<br>한계도 알려드려요.</h3><p>다음 행동이 만들어지는 과정과<br>멈추고 확인하는 기준을 알아봐요.</p><div class="story-art">${icon('shield')}<span class="art-note">제안 뒤에도 한 번 더 검수</span></div><span class="round-arrow" aria-hidden="true">↗</span></a></div></div></section><section class="home-questions container"><div class="section-intro"><p class="eyebrow">궁금한 순간에</p><h2>이런 점이<br>궁금하셨나요?</h2>${link('사례와 질문 모두 보기', url('questions'))}</div><div>${faqs([questions[0], questions[3], questions[4], questions[6]])}</div></section><section class="transparency container"><div><p class="eyebrow">설명도 함께 최신화해요</p><h2>서비스가 달라지면,<br>안내도 함께 바뀌어요.</h2><p>현재 제공하는 기능과 검증한 범위를 개발 문서에서 공개해요.</p></div><div class="transparency-links">${link('현재 서비스 운영 기준', url('standards'))}${link('검증 기록 확인하기', '/developers/ko/reference/tests/')}${link('변경 이력 살펴보기', '/developers/ko/reference/changes/')}</div></section>`
}

function detail(page) {
  const categories = ['전체', ...new Set(questions.map(q => q.category))]
  const content = page.id === 'questions' ? `<div class="faq-filters" role="group" aria-label="질문 분류">${categories.map((c, i) => `<button type="button" data-filter="${e(c)}" aria-pressed="${i === 0}">${e(c)}</button>`).join('')}</div><p class="filter-status" role="status">${questions.length}개의 질문</p><div class="question-list">${faqs(questions)}</div>` : `<div class="article-layout"><aside class="contents"><strong>이 페이지에서</strong>${page.sections.map(s => `<a href="#${e(s.id)}">${e(s.title)}</a>`).join('')}</aside><div class="article-body">${page.sections.map((s, i) => `<section id="${e(s.id)}"><span class="small-number">0${i + 1}</span><h2>${e(s.title)}</h2><p>${e(s.text)}</p>${s.steps ? `<ol class="process">${s.steps.map(t => `<li>${e(t)}</li>`).join('')}</ol>` : ''}${s.links ? `<div class="article-links">${s.links.map(([title, href]) => link(title, href)).join('')}</div>` : ''}</section>`).join('')}</div></div>`
  return `<div class="container"><nav class="breadcrumb" aria-label="현재 위치"><a href="/safety/">안심가이드</a><span aria-hidden="true">/</span><span>${e(page.nav)}</span></nav><header class="page-heading"><div><p class="eyebrow">${e(page.eyebrow)}</p><h1>${heading(page.title)}</h1><p>${e(page.description)}</p></div><div class="heading-icon">${icon(page.icon)}</div></header>${content}<nav class="related-pages" aria-label="함께 살펴보기">${link('안심가이드 홈', '/safety/')}${link(page.id === 'questions' ? '리본의 운영철학' : '사례와 질문', page.id === 'questions' ? url('philosophy') : url('questions'))}</nav></div>`
}

export function buildSafety({ check, contract, documentationIds, documentationPages }) {
  const ids = new Set(pages.map(p => p.id))
  if (ids.size !== pages.length) throw new Error('안심가이드 페이지가 중복됩니다.')
  const built = new Map(), index = []
  for (const page of pages) {
    for (const path of page.sources) if (!existsSync(join(root, path))) throw new Error(`안심가이드 구현 근거가 없습니다: ${path}`)
    const main = page.id === 'home' ? home() : detail(page)
    const nav = pages.filter(p => p.id !== 'home').map(p => `<a href="${url(p.id)}"${page.id === p.id ? ' aria-current="page"' : ''}>${e(p.nav)}</a>`).join('')
    const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="${e(page.description)}"><meta name="theme-color" content="#c3410c"><title>${e(page.nav === '홈' ? '가게의 마무리도, 사장님의 내일도' : page.nav)} | 리본 안심가이드</title><link rel="icon" type="image/svg+xml" href="/safety/assets/reborn-hammer.svg"><link rel="stylesheet" href="/safety/assets/safety.css"><script src="/safety/assets/safety.js" defer></script></head><body data-page="${e(page.id)}"><a class="skip-link" href="#main">본문 바로가기</a><header class="site-header"><div class="header-inner"><a class="brand" href="/safety/" aria-label="리본 안심가이드 홈"><img src="/safety/assets/reborn-hammer.svg" width="26" height="26" alt=""><strong>reborn</strong><span>안심가이드</span></a><nav id="site-nav" class="site-nav" aria-label="주 메뉴">${nav}</nav><div class="header-tools"><button class="search-open icon-button" aria-label="안심가이드 검색" aria-haspopup="dialog"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="10.5" cy="10.5" r="7.5"/><path d="m16 16 5 5"/></svg></button><button class="menu-toggle icon-button" aria-label="메뉴 열기" aria-controls="site-nav" aria-expanded="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/></svg></button></div></div></header><main id="main" tabindex="-1">${main}</main><footer class="site-footer"><div class="container"><div class="footer-top"><a class="brand" href="/safety/"><strong>reborn</strong><span>안심가이드</span></a><p>차근차근 정리하고,<br>다음 시작을 준비할 수 있도록.</p></div><nav class="footer-nav" aria-label="하단 메뉴">${nav}<a href="/developers/">개발 문서 ↗</a><a href="/">서비스로 ↗</a></nav><div class="footer-bottom"><span>© RE:BORN Team · 카카오테크 캠퍼스</span><span>안내 확인 ${e(contract.checked_at.slice(0, 10))}</span></div><p class="footer-note">현재 서비스의 원칙과 이용 방법을 설명하는 안내입니다. 이용약관이나 개인정보처리방침을 대신하지 않습니다.</p></div></footer><dialog class="search-dialog" aria-label="안심가이드 검색"><form method="dialog" class="search-heading"><strong>어떤 내용이 궁금하세요?</strong><button class="icon-button search-close" aria-label="검색 닫기">×</button></form><label for="safety-search" class="sr-only">검색어</label><input id="safety-search" type="search" placeholder="운영철학, 서류, 개인정보를 검색해 보세요" autocomplete="off"><p id="search-status" role="status"></p><ul id="search-results"></ul></dialog><button class="to-top" type="button" aria-label="맨 위로">↑</button></body></html>`
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
    writeFileSync(join(destination, 'search-index.json'), JSON.stringify(index))
    writeFileSync(join(destination, 'manifest.json'), JSON.stringify({ checked_at: contract.checked_at, source_revision: contract.source_revision, pages: pages.map(p => ({ id: p.id, title: p.nav, url: url(p.id) })) }, null, 2))
  }
  console.log(`안심가이드 ${check ? '검사 통과' : '생성 완료'}: ${pages.length}개 페이지, 질문 ${questions.length}개.`)
}
