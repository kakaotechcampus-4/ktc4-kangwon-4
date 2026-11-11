(() => {
  'use strict'
  const film = document.querySelector('.hero-film')
  if (film) {
    const video = film.querySelector('video')
    const control = film.querySelector('.film-toggle')
    const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)')
    let wantsPlayback = !reducedMotion.matches
    let visible = true
    video.muted = true
    function updateControl() {
      const playing = !video.paused && !video.ended
      film.dataset.motion = playing ? 'running' : 'paused'
      control.setAttribute('aria-pressed', String(playing))
      control.setAttribute('aria-label', playing ? '소개 영상 일시정지' : '소개 영상 재생')
      control.querySelector('.film-control-label').textContent = playing ? '영상 멈춤' : '영상 재생'
      control.querySelector('.film-control-icon').textContent = playing ? 'Ⅱ' : '▶'
    }
    async function syncPlayback() {
      if (!wantsPlayback || document.hidden || !visible) {
        video.pause()
      } else {
        try { await video.play() } catch { /* 자동 재생이 막혀도 재생 버튼을 남긴다. */ }
      }
      updateControl()
    }
    control.addEventListener('click', () => { wantsPlayback = video.paused; void syncPlayback() })
    video.addEventListener('play', updateControl)
    video.addEventListener('pause', updateControl)
    video.addEventListener('error', () => { wantsPlayback = false; control.hidden = true })
    reducedMotion.addEventListener('change', () => { wantsPlayback = !reducedMotion.matches; void syncPlayback() })
    document.addEventListener('visibilitychange', () => { void syncPlayback() })
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(entries => { visible = entries[0].isIntersecting; void syncPlayback() }, { threshold: 0.05 }).observe(film)
    }
    void syncPlayback()
  }
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
  // 같은 페이지 안의 #링크(목차, 본문 바로가기)를 누를 때만 부드럽게 옮긴다. html 전체에
  // scroll-behavior:smooth 를 두면 #이 붙은 주소로 들어오거나 새로고침할 때도 맨 위에서 미끄러져 내려간다
  document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const link = event.target.closest('a[href^="#"]')
    const target = link && document.getElementById(decodeURIComponent(link.hash.slice(1)))
    if (!target) return
    event.preventDefault()
    target.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
    if (location.hash !== link.hash) history.pushState(null, '', link.hash)
    if (target.hasAttribute('tabindex')) target.focus({ preventScroll: true })
  })
  // 첫 화면 카드는 화면에 들어올 때 아래에서 올라온다. 숨기는 class는 스크립트가 붙이므로
  // 스크립트가 돌지 않거나 움직임 줄이기를 켠 사람에게는 카드가 처음부터 그대로 보인다
  const panels = document.body.dataset.page === 'home' ? [...document.querySelectorAll('.feature-panel')] : []
  if (panels.length && 'IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.documentElement.classList.add('reveal-ready')
    const observer = new IntersectionObserver(entries => {
      // 한 번에 건너뛰어(맨 아래로, 새로고침 복원) 지나친 위쪽 카드도 같이 보이게 한다
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        for (const panel of panels.slice(0, panels.indexOf(entry.target) + 1)) {
          panel.classList.add('is-visible')
          observer.unobserve(panel)
        }
      }
    }, { threshold: 0.15 })
    panels.forEach(panel => observer.observe(panel))
  }
})()
