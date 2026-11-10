(() => {
  'use strict'
  const base = '/developers/'
  const page = document.body.dataset.page
  const sidebar = document.querySelector('.sidebar')
  const menu = document.querySelector('.menu-toggle')
  menu.addEventListener('click', () => {
    const open = sidebar.classList.toggle('mobile-open')
    menu.setAttribute('aria-expanded', String(open))
    menu.setAttribute('aria-label', open ? '사이드 메뉴 닫기' : '사이드 메뉴 열기')
  })
  document.addEventListener('click', event => {
    if (!sidebar.contains(event.target) && !menu.contains(event.target)) {
      sidebar.classList.remove('mobile-open')
      menu.setAttribute('aria-expanded', 'false')
      menu.setAttribute('aria-label', '사이드 메뉴 열기')
    }
  })
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      sidebar.classList.remove('mobile-open')
      menu.setAttribute('aria-expanded', 'false')
      menu.setAttribute('aria-label', '사이드 메뉴 열기')
    }
  })

  let recent = []
  try {
    const saved = JSON.parse(localStorage.getItem('reborn:docs:recent') || '[]')
    recent = Array.isArray(saved) ? saved.filter(item => item && typeof item.title === 'string' && typeof item.url === 'string' && /^\/developers\/ko\/[a-z0-9/-]+\/$/.test(item.url)).slice(0, 5) : []
  } catch { /* 저장소를 쓸 수 없어도 문서를 읽을 수 있다. */ }
  const recentBox = document.querySelector('.recent-docs')
  const clearRecent = document.querySelector('.clear-recent')
  function renderRecent() {
    if (!recentBox) return
    recentBox.replaceChildren()
    if (recent.length) {
      recent.forEach(item => { const link = document.createElement('a'); link.href = item.url; link.textContent = item.title; recentBox.append(link) })
    } else {
      const text = document.createElement('p'); text.textContent = '최근에 본 문서가 없습니다.'; recentBox.append(text)
    }
    if (clearRecent) clearRecent.disabled = !recent.length
  }
  renderRecent()
  if (clearRecent) clearRecent.addEventListener('click', () => {
    recent = []
    try { localStorage.removeItem('reborn:docs:recent') } catch { /* 메모리의 기록은 지운다. */ }
    renderRecent()
  })
  if (page && page !== 'home') {
    const current = { title: document.querySelector('h1').textContent, url: `/developers/ko/${page}/` }
    recent = [current, ...recent.filter(item => item.url !== current.url)].slice(0, 5)
    try { localStorage.setItem('reborn:docs:recent', JSON.stringify(recent)) } catch { /* 읽기를 막지 않는다. */ }
  }

  const dialog = document.querySelector('.search-dialog')
  const input = document.getElementById('doc-search')
  const results = document.getElementById('search-results')
  const status = document.getElementById('search-status')
  let indexPromise
  let generation = 0
  function loadIndex() {
    if (!indexPromise) {
      indexPromise = fetch(base + 'search-index.json').then(response => {
        if (!response.ok) throw new Error('search index')
        return response.json()
      }).catch(error => { indexPromise = undefined; throw error })
    }
    return indexPromise
  }
  async function search() {
    const current = ++generation
    const query = input.value.trim().toLocaleLowerCase('ko-KR')
    results.replaceChildren()
    if (!query) { status.textContent = '문서 제목, 기능, API 경로나 에러 코드로 검색하세요.'; return }
    status.textContent = '문서를 찾고 있습니다.'
    try {
      const index = await loadIndex()
      if (current !== generation) return
      const terms = query.split(/\s+/).filter(Boolean)
      const hits = index.map(item => {
        const title = item.title.toLocaleLowerCase('ko-KR')
        const description = item.description.toLocaleLowerCase('ko-KR')
        const text = item.text.toLocaleLowerCase('ko-KR')
        return { item, score: terms.reduce((sum, term) => sum + (title.includes(term) ? 20 : description.includes(term) ? 6 : text.includes(term) ? 1 : -1000), 0) }
      }).filter(hit => hit.score > 0).sort((a, b) => b.score - a.score).slice(0, 14)
      status.textContent = hits.length ? `검색 결과 ${hits.length}개` : '검색 결과가 없습니다. 다른 단어로 검색하세요.'
      for (const { item } of hits) {
        const li = document.createElement('li'), a = document.createElement('a'), title = document.createElement('strong'), desc = document.createElement('p')
        a.href = item.url; title.textContent = item.title; desc.textContent = item.description
        a.append(title, desc); li.append(a); results.append(li)
      }
    } catch { if (current === generation) status.textContent = '검색 자료를 불러오지 못했습니다. 잠시 뒤 다시 검색하세요.' }
  }
  function openSearch() {
    if (!dialog.open) dialog.showModal()
    input.focus()
    void search()
  }
  document.querySelector('.search-open').addEventListener('click', openSearch)
  document.querySelector('.search-close').addEventListener('click', () => dialog.close())
  dialog.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close() } })
  input.addEventListener('input', search)
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch() }
  })
  dialog.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); dialog.close(); return }
    const links = [...results.querySelectorAll('a')]
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const delta = event.key === 'ArrowDown' ? 1 : -1
      const current = links.indexOf(document.activeElement)
      if (links.length) links[current < 0 ? (delta > 0 ? 0 : links.length - 1) : (current + delta + links.length) % links.length].focus()
    } else if (event.key === 'Enter' && document.activeElement === input && links.length) { event.preventDefault(); links[0].click() }
  })

  let toastTimer
  function toast(text) {
    const box = document.querySelector('.toast'); box.textContent = text; box.hidden = false
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { box.hidden = true }, 2400)
  }
  for (const button of document.querySelectorAll('.copy')) button.addEventListener('click', async () => {
    const code = button.closest('.code-block').querySelector('pre code')
    try { await navigator.clipboard.writeText(code.textContent); toast('코드를 복사했습니다.') }
    catch { const range = document.createRange(); range.selectNodeContents(code); const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); toast('코드를 선택했습니다. 복사 단축키로 복사하세요.') }
  })
  document.querySelector('.to-top')?.addEventListener('click', () => window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }))
  document.querySelector('.info-button')?.addEventListener('click', () => toast('최근 본 문서는 이 브라우저에 문서 제목과 주소만 저장합니다.'))

  if ('IntersectionObserver' in window) {
    const links = [...document.querySelectorAll('.page-toc a')]
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
      if (!visible) return
      links.forEach(link => { const active = decodeURIComponent(link.hash.slice(1)) === visible.target.id; link.classList.toggle('active', active); if (active) link.setAttribute('aria-current', 'location'); else link.removeAttribute('aria-current') })
    }, { rootMargin: '-125px 0px -60% 0px' })
    for (const link of links) { const section = document.getElementById(decodeURIComponent(link.hash.slice(1))); if (section) observer.observe(section) }
  }
})()
