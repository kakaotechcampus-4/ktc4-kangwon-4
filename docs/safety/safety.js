(() => {
  'use strict'
  const nav = document.querySelector('.site-nav')
  const toggle = document.querySelector('.menu-toggle')
  function menu(open) {
    nav.classList.toggle('is-open', open)
    toggle.setAttribute('aria-expanded', String(open))
    toggle.setAttribute('aria-label', open ? '메뉴 닫기' : '메뉴 열기')
  }
  toggle.addEventListener('click', () => menu(toggle.getAttribute('aria-expanded') !== 'true'))
  document.addEventListener('click', event => { if (!nav.contains(event.target) && !toggle.contains(event.target)) menu(false) })
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') { menu(false); toggle.focus() } })
  for (const filter of document.querySelectorAll('[data-filter]')) filter.addEventListener('click', () => {
    const category = filter.dataset.filter
    document.querySelectorAll('[data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button === filter)))
    let count = 0
    document.querySelectorAll('.question-list .faq').forEach(item => {
      item.hidden = category !== '전체' && category !== item.dataset.category
      if (!item.hidden) count++
    })
    document.querySelector('.filter-status').textContent = `${count}개의 질문`
  })

  const dialog = document.querySelector('.search-dialog')
  const input = document.getElementById('safety-search')
  const results = document.getElementById('search-results')
  const status = document.getElementById('search-status')
  let index, generation = 0
  async function search() {
    const turn = ++generation
    const query = input.value.trim().toLocaleLowerCase('ko-KR')
    results.replaceChildren()
    if (!query) { status.textContent = '원칙, 이용 방법 또는 궁금한 내용을 검색해 보세요.'; return }
    status.textContent = '안내를 찾고 있어요.'
    try {
      if (!index) index = fetch('/safety/search-index.json').then(r => { if (!r.ok) throw new Error('index'); return r.json() }).catch(error => { index = undefined; throw error })
      const entries = await index
      if (turn !== generation) return
      const terms = query.split(/\s+/).filter(Boolean)
      const hits = entries.map(item => ({ item, score: terms.reduce((score, term) => score + (item.title.toLocaleLowerCase('ko-KR').includes(term) ? 20 : item.text.toLocaleLowerCase('ko-KR').includes(term) ? 1 : -1000), 0) })).filter(hit => hit.score > 0).sort((a, b) => b.score - a.score)
      status.textContent = hits.length ? `${hits.length}개의 안내를 찾았어요.` : '검색 결과가 없어요. 다른 단어로 찾아보세요.'
      for (const { item } of hits) {
        const li = document.createElement('li'), a = document.createElement('a'), title = document.createElement('strong'), description = document.createElement('p')
        a.href = item.url; title.textContent = item.title; description.textContent = item.description
        a.append(title, description); li.append(a); results.append(li)
      }
    } catch { if (turn === generation) status.textContent = '검색 자료를 불러오지 못했어요. 잠시 뒤 다시 검색해 주세요.' }
  }
  function openSearch() { menu(false); if (!dialog.open) dialog.showModal(); input.focus(); void search() }
  document.querySelector('.search-open').addEventListener('click', openSearch)
  input.addEventListener('input', search)
  document.addEventListener('keydown', event => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch() } })
  dialog.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); dialog.close(); return }
    const links = [...results.querySelectorAll('a')]
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const current = links.indexOf(document.activeElement), delta = event.key === 'ArrowDown' ? 1 : -1
      if (links.length) links[current < 0 ? (delta > 0 ? 0 : links.length - 1) : (current + delta + links.length) % links.length].focus()
    } else if (event.key === 'Enter' && document.activeElement === input && links.length) { event.preventDefault(); links[0].click() }
  })
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return
    const r = dialog.getBoundingClientRect()
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close()
  })
  document.querySelector('.to-top').addEventListener('click', () => window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' }))
})()
