import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, copyFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { groups, pages as guides, apiGroups, operationNotes } from '../docs/developers/content.mjs'
import { buildSafety } from './build-safety.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = join(root, 'docs/developers')
const destination = join(root, 'frontend/public/developers')
const contract = JSON.parse(readFileSync(join(source, 'generated/contracts.json'), 'utf8'))
const screenshots = JSON.parse(readFileSync(join(source, 'screenshots.json'), 'utf8'))
const spec = contract.openapi
const schemas = spec.components.schemas
const check = process.argv.includes('--check')
const e = (s = '') => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const url = id => `/developers/ko/${id}/`
const sha = content => createHash('sha256').update(content).digest('hex')
const changed = Object.entries(contract.source_hashes).filter(([file, digest]) => !existsSync(join(root, file)) || sha(readFileSync(join(root, file))) !== digest).map(([file]) => file)
const currentFiles = []
for (const folder of ['backend/app', 'backend/sql', 'frontend/src']) {
  const walk = base => { for (const entry of readdirSync(join(root, base), { withFileTypes: true })) {
    const file = `${base}/${entry.name}`
    if (entry.isDirectory() && entry.name !== '__pycache__') walk(file)
    else if (/\.(py|json|sql|ts|tsx|css)$/.test(file) && !file.includes('.test.')) currentFiles.push(file)
  } }
  walk(folder)
}
const added = currentFiles.filter(file => !contract.source_hashes[file])
const stale = [...changed, ...added]
const operations = apiGroups.flatMap(group => group.operations)
const actualOperations = Object.entries(spec.paths).flatMap(([path, methods]) => Object.keys(methods).map(method => `${method.toUpperCase()} ${path}`))
if (new Set(operations).size !== operations.length || operations.length !== actualOperations.length || actualOperations.some(key => !operations.includes(key))) throw new Error('API 문서와 실제 OpenAPI 작업 목록이 다릅니다.')
for (const page of guides) for (const path of page.sources) if (!existsSync(join(root, path))) throw new Error(`문서 근거 파일이 없습니다: ${path}`)
for (const key of operations) if (!operationNotes[key]) throw new Error(`API 설명이 없습니다: ${key}`)
if (stale.length && check) throw new Error(`코드가 변경되어 문서 확인이 필요합니다:\n${stale.join('\n')}\n관련 설명을 수정한 뒤 Backend에서 python scripts/export_documentation.py를 실행하세요.`)

const table = (heads, rows) => `<div class="table-wrap"><table><thead><tr>${heads.map(h => `<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(v => `<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
const paragraph = text => `<p>${e(text)}</p>`
const callout = (title, text, tone = 'info') => `<aside class="callout ${tone}"><strong>${e(title)}</strong>${paragraph(text)}</aside>`
const code = (text, label = 'JSON') => `<div class="code-block"><div class="code-bar"><span>${e(label)}</span><button type="button" class="copy" aria-label="${e(label)} 코드 복사">복사</button></div><pre><code>${e(text)}</code></pre></div>`
const imageIds = new Set()
const images = ids => `<div class="screens">${ids.map(id => {
  imageIds.add(id)
  const info = screenshots[id]
  if (!info) throw new Error(`캡처 정보가 없습니다: ${id}`)
  return `<figure><a href="/developers/assets/screens/${e(id)}.png" target="_blank" rel="noopener" aria-label="${e(info.title)} 화면 크게 보기"><img src="/developers/assets/screens/${e(id)}.png" alt="리본 ${e(info.title)} 화면 미리보기" loading="lazy" width="402" height="874"></a><figcaption>${e(info.title)}<br>${e(info.captured_at)} UI 캡처 · 미리보기 데이터</figcaption></figure>`
}).join('')}</div>`

function type(schema = {}) {
  if (schema.$ref) { const name = schema.$ref.split('/').at(-1); return `<a class="type-ref" href="${url('reference/schemas')}#${e(name)}">${e(name)}</a>` }
  if (schema.anyOf) return schema.anyOf.map(type).join(' / ')
  if (schema.type === 'array') return `${type(schema.items)}[]`
  if (schema.enum || schema.const) return 'Enum'
  return ({ string: schema.format === 'binary' ? 'Multipart File' : schema.format === 'date' ? 'Date' : schema.format === 'date-time' ? 'Datetime' : 'String', integer: 'Integer', number: 'Double', boolean: 'Boolean', object: 'JSON', null: 'null' })[schema.type] || 'JSON'
}
function constraints(schema = {}) {
  const labels = [['minLength', '최소 길이'], ['maxLength', '최대 길이'], ['minimum', '최소'], ['maximum', '최대'], ['pattern', '형식']]
  const parts = labels.filter(([k]) => schema[k] !== undefined).map(([k, label]) => `${label}: ${schema[k]}`)
  if (schema.default !== undefined) parts.push(`기본값: ${JSON.stringify(schema.default)}`)
  if (schema.enum) parts.push(`사용 가능한 값: ${schema.enum.join(', ')}`)
  if (schema.const !== undefined) parts.push(`고정값: ${schema.const}`)
  if (schema.format && schema.format !== 'binary') parts.push(`형식: ${schema.format}`)
  if (schema.anyOf) for (const item of schema.anyOf) { const nested = constraints(item); if (nested) parts.push(nested) }
  return parts.join(' · ')
}
function resolveSchema(schema) { return schema?.$ref ? schemas[schema.$ref.split('/').at(-1)] : schema }
function fieldTable(raw, request = false) {
  const schema = resolveSchema(raw) || {}
  if (!schema.properties) return table(['이름', '타입', '설명'], [['-', type(raw), e(schema.description || constraints(schema) || '상세 계약은 원본 OpenAPI를 확인합니다.')]])
  return table(['이름', '타입', '설명', '필수'], Object.entries(schema.properties).map(([name, value]) => {
    let required = schema.required?.includes(name) ? 'O' : 'X'
    let description = [value.description, constraints(value)].filter(Boolean).join(' · ') || fieldDescriptions[name] || '코드 계약의 필드입니다. 상세 타입을 확인하세요.'
    if (request && ['raw_input', 'restoration_answer'].includes(name)) { required = 'X*'; description += ' · 둘 중 하나만 전달' }
    return [`<code>${e(name)}</code>`, type(value), e(description), required]
  }))
}
const fieldDescriptions = {
  case_history_id: '판단 또는 접수 이력 번호', case: '회원의 현재 Case, 없으면 null', blocker: '현재 우선 확인 조건',
  next_action: '검수한 다음 행동', result: '이번 입력의 업무 처리 결과', judgment_status: '저장된 판단 상태',
  changes: '직전 값과 반영한 값의 변화', questions_for_user: '다음 판단에 필요한 사용자 질문',
  recovery_action_code: '실패 뒤 가능한 복구 종류', retryable: '다시 시도할 수 있는지', requested_field_paths: '보완이 필요한 필드',
  raw_input: '사용자가 직접 적은 결과', restoration_answer: '사용자가 고른 원상복구 범위와 철거 여부',
  result_input_kind: '서버가 현재 허용하는 입력 종류', conflicts: '사용자 선택이 필요한 충돌',
  new_tasks: '직전 판단보다 새로 해야 할 일이 된 작업', completed: '사용자 완료 체크 여부',
  approved: '사용자가 기관에서 확인한 1차 심사 결과, null은 미확인',
  source: '판단을 시작한 입력의 종류', code: '카카오에서 받은 인가 코드',
  closure_date: '사용자가 확인한 실제 폐업일', closure_reason: '폐업 사유', road_address: '도로명 주소',
  address_detail: '상세 주소', applicant_name: '서류 점검 신청인', confirmed_fields: '사용자가 확인한 문서 값',
  document_id: 'Case의 문서 UUID', kind: '문서 종류', kind_label: '종류의 표시 이름', filename: '파일 이름',
  documents: '저장된 문서 목록', check: '현재 문서의 점검 결과, 문서 변경 시 null', fields: '문서에서 추출한 값',
  needs_confirmation: '종류 또는 추출값을 사용자가 확인해야 하는지',
  id: '레코드 번호', member_id: '소유 회원 번호', store_name: '가게 이름', business_type: '가게 업종',
  franchise_status: '프랜차이즈 여부', employee_count: '현재 직원 수', has_business_loan: '사업 대출 여부',
  has_service_contracts: '서비스 계약 여부', lease_status: '점포 임차 형태', restoration_clause: '원상복구 조항 존재 여부',
  planned_closure_date: '예정 폐업일', planned_closure_month: '날짜 대신 알고 있는 예상 달', had_employees: '과거를 포함한 고용 이력',
  pension_enrolled: '사업장 국민연금 가입 이력', health_insurance_enrolled: '사업장 건강보험 가입 이력',
  employment_insurance_enrolled: '사업장 고용보험 가입 이력', industrial_accident_insurance_enrolled: '사업장 산재보험 가입 이력',
  decisions: '충돌 항목별 선택 목록', conflict_reference_id: '선택할 충돌 참조 번호', side: '기존값 또는 새값 선택',
  restoration_scope: '원상복구 범위', demolition_required: '철거 필요 여부', restoration_scope_detail: '구체 원상복구 내용',
  restoration_status: '원상복구 진행 상태', case_status: '서비스의 Case 진행 상태', created_at: '생성 시각', updated_at: '갱신 시각', completed_at: '서비스 완료 기록 시각',
}
function example(raw, depth = 0, name = '') {
  const schema = resolveSchema(raw) || {}
  if (schema.default !== undefined) return schema.default
  if (schema.const !== undefined) return schema.const
  if (schema.enum) return schema.enum[0]
  if (schema.anyOf) { if (schema.anyOf.some(s => s.type === 'null')) return null; return example(schema.anyOf[0], depth + 1, name) }
  if (schema.type === 'object' || schema.properties) return depth > 5 ? {} : Object.fromEntries(Object.entries(schema.properties || {}).map(([key, value]) => [key, example(value, depth + 1, key)]))
  if (schema.type === 'array') return []
  if (schema.type === 'integer' || schema.type === 'number') return name.endsWith('id') ? 13 : (schema.minimum ?? 0)
  if (schema.type === 'boolean') return false
  if (schema.type === 'null') return null
  if (schema.format === 'uuid') return '00000000-0000-4000-8000-000000000001'
  if (schema.format === 'date') return '2026-11-07'
  if (schema.format === 'date-time') return '2026-11-07T12:00:00+09:00'
  return '예시 값'
}

const apiPages = apiGroups.map(group => ({ id: `${group.family}/rest-api`, family: group.family, title: group.title, description: group.description, sources: ['backend/app/be/routers/case.py', 'backend/app/be/routers/auth.py', 'backend/app/be/routers/document.py', 'backend/app/be/dependencies/auth.py'], api: group }))
const typesPage = { id: 'reference/schemas', title: '타입과 필드', description: '현재 FastAPI OpenAPI에 선언된 타입과 필드를 확인합니다.', sources: ['backend/app/be/schemas/case.py', 'backend/app/be/schemas/document.py', 'backend/app/agent/schemas.py'], schemas: true }
const home = { id: 'home', title: '문서', description: '리본의 서비스 흐름과 API 사용을 위한 문서를 제공합니다.', sources: [], home: true }
const allPages = [home, ...guides, ...apiPages, typesPage]
const byId = new Map(allPages.map(page => [page.id, page]))
if (byId.size !== allPages.length) throw new Error('문서 ID가 중복됩니다.')
for (const group of groups) for (const [id] of group.items) if (!byId.has(id) && !byId.has(`${id}/common`)) throw new Error(`메뉴가 연결되지 않았습니다: ${id}`)

function renderSections(sections) {
  return sections.map(s => `<section id="${e(s.id)}" class="doc-section"><h2><a class="heading-anchor" href="#${e(s.id)}">${e(s.title)}<span aria-hidden="true">#</span></a></h2>${(s.text || []).filter(Boolean).map(paragraph).join('')}${s.list ? `<ul>${s.list.map(t => `<li>${e(t)}</li>`).join('')}</ul>` : ''}${s.steps ? `<ol class="steps">${s.steps.map(t => `<li>${e(t)}</li>`).join('')}</ol>` : ''}${s.table ? table(s.table[0].map(e), s.table.slice(1).map(r => r.map(e))) : ''}${s.images ? images(s.images) : ''}${s.note ? callout(s.note.title, s.note.text, s.note.tone) : ''}${s.code ? code(s.code.text, s.code.language) : ''}${s.tests ? s.tests.map(t => `<details class="test-case"><summary>${e(t.name)}</summary>${paragraph(t.expected)}</details>`).join('') : ''}${s.links ? `<div class="related-links">${s.links.map(([label, href]) => `<a href="${e(href)}"${href.startsWith('http') ? ' target="_blank" rel="noopener noreferrer"' : ''}>${e(label)} <span aria-hidden="true">↗</span></a>`).join('')}</div>` : ''}${s.roadmap ? table(['단계', '작업 ID', '작업 이름'], contract.roadmap.map(t => [e(t.stage_title), `<code>${e(t.task_id)}</code>`, e(t.title)])) : ''}${s.validation ? renderValidation() : ''}</section>`).join('')
}
function renderValidation() {
  const path = join(source, 'validation.json')
  if (!existsSync(path)) return callout('검증 시점', '이번 코드의 검증 결과는 준비 중입니다. 과거 수치를 현재 결과로 사용하지 않습니다.')
  const v = JSON.parse(readFileSync(path, 'utf8'))
  return table(['항목', '실행 결과', '기준'], v.results.map(r => [e(r.name), e(r.result), e(v.source_revision.slice(0, 7))])) + paragraph(v.note)
}
function apiContent(page) {
  return callout('요청 경로와 인증', '표는 Backend 경로입니다. 예제의 REBORN_API_BASE_URL은 Backend 주소(로컬 기본 http://localhost:8000)로 설정합니다. FE의 같은 출처 프록시 주소를 쓸 때는 /api까지 포함합니다. 리본 API에는 리본 자체 JWT를 Access-Token 헤더로 보냅니다. 카카오 토큰과 구분하세요.') + page.api.operations.map((key, index) => {
    const split = key.indexOf(' '); const method = key.slice(0, split); const path = key.slice(split + 1)
    const operation = spec.paths[path][method.toLowerCase()]; const notes = operationNotes[key]
    const publicApi = ['/login/form', '/login', '/health'].includes(path)
    const header = publicApi ? null : path === '/reissue' ? 'Refresh-Token' : 'Access-Token'
    const bodyContent = operation.requestBody?.content || {}; const mime = Object.keys(bodyContent)[0]
    const bodySchema = bodyContent[mime]?.schema; const bodyName = bodySchema?.$ref?.split('/').at(-1)
    const payload = contract.request_examples[bodyName]
    const params = (operation.parameters || []).filter(p => !['Access-Token', 'Refresh-Token'].includes(p.name))
    let requestPath = path.replace('{task_id}', 'notify_landlord').replace('{document_id}', '00000000-0000-4000-8000-000000000001')
    const queries = params.filter(p => p.in === 'query' && p.required).map(p => `${p.name}=${p.name === 'case_history_id' ? '13' : encodeURIComponent(example(p.schema))}`)
    if (queries.length) requestPath += `?${queries.join('&')}`
    let curl = `curl -X ${method} "\${REBORN_API_BASE_URL}${requestPath}"`
    if (header) curl += ` \\\n  -H "${header}: \${${header === 'Access-Token' ? 'ACCESS_TOKEN' : 'REFRESH_TOKEN'}}"`
    if (mime === 'application/json' && payload) curl += ` \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(payload, null, 2)}'`
    if (mime === 'multipart/form-data') curl += ' \\\n  -F "file=@\${DOCUMENT_PATH}"'
    if (notes.binary) curl += ' \\\n  --output settlement.zip'
    const responseSchema = operation.responses['200']?.content?.['application/json']?.schema
    let response = notes.responseExample === undefined ? example(responseSchema) : notes.responseExample
    let result = `<section id="operation-${index + 1}" class="api-operation"><h2>${e(notes.title)}</h2>${paragraph(notes.description)}${table(['메서드', 'URL', '인증 방식'], [[`<span class="method method-${method.toLowerCase()}">${method}</span>`, `<code>${e(path)}</code>`, header ? `리본 <code>${header}</code>` : '-']])}`
    const requirements = publicApi ? '기능 설명과 설정 문서를 확인합니다.' : !path.startsWith('/cases') ? '해당 유형의 유효한 리본 인증 토큰이 필요합니다. Case 생성 여부와 무관하게 인증 기능을 사용합니다.' : path === '/cases' ? '유효한 리본 Access-Token이 필요합니다. 생성은 아직 Case가 없는 회원이 사용하고, 조회는 Case가 없으면 case: null을 반환합니다.' : '유효한 리본 Access-Token과 현재 회원의 Case가 필요합니다. 각 API의 최신 이력·충돌·문서 상태 조건을 확인하세요.'
    result += `<h3>요구 사항</h3>${paragraph(requirements)}`
    result += '<h3>요청</h3>'
    if (header) result += table(['헤더', '설명', '필수'], [[`<code>${header}</code>`, '리본이 발급한 해당 유형의 JWT', 'O']])
    if (params.length) result += table(['이름', '위치', '타입', '설명', '필수'], params.map(p => [`<code>${e(p.name)}</code>`, e(p.in), type(p.schema), e(p.description || constraints(p.schema)), p.required ? 'O' : 'X']))
    if (bodySchema) result += `<h4>본문 · ${e(mime)}</h4>${fieldTable(bodySchema, true)}`
    else result += paragraph('요청 본문 없음')
    if (bodyName === 'CaseResultsSubmitRequest') result += paragraph('* raw_input과 restoration_answer 중 하나만 전달합니다. 화면의 질문과 답을 묶은 글도 전체 길이 제한을 확인합니다.')
    result += code(curl, 'cURL · 자리 표시자를 바꾸어 사용')
    result += `<h3>응답</h3><p>HTTP <code>${e(notes.status || '200')}</code>${notes.binary ? ' · Content-Type: application/zip' : ''}</p>`
    if (['/login', '/reissue'].includes(path)) result += table(['응답 헤더', '설명'], [['Access-Token', '새 리본 액세스 토큰'], ['Refresh-Token', '새 리본 리프레시 토큰']])
    if (notes.binary) result += table(['이름', '타입', '설명'], [['-', 'Binary', '점검된 정산 서류와 결과가 들어 있는 ZIP']])
    else if (notes.status === '303') result += paragraph('응답은 Location 헤더의 카카오 인가 화면으로 이동합니다. JSON 본문을 소비하는 로그인 요청이 아닙니다.')
    else { if (responseSchema?.$ref) result += fieldTable(responseSchema); result += code(JSON.stringify(response, null, 2), 'JSON · 응답 구조 예시') }
    if (['POST /cases', 'POST /cases/results', 'POST /cases/results/decision', 'POST /cases/retry'].includes(key)) result += callout('접수와 반영 완료', '성공 응답은 접수 상태입니다. 저장된 새 번호 또는 재개한 번호로 상태를 조회하고 업무 결과를 확인합니다.')
    result += `<p class="operation-related"><a href="${url('reference/errors')}">에러 코드와 복구</a> · <a href="${url('reference/schemas')}${bodyName ? `#${e(bodyName)}` : ''}">타입과 필드</a></p></section>`
    return result
  }).join('')
}
function homeContent() {
  const card = (id, title, description, icon) => `<a class="doc-card" href="${url(id)}"><strong>${e(title)} <span class="card-icon" aria-hidden="true">${icon}</span></strong><p>${e(description)}</p></a>`
  return `<section id="recent"><h2>최근 본 문서 <button class="info-button" type="button" title="이 브라우저에서 읽은 문서 제목만 저장합니다." aria-label="최근 본 문서 안내">i</button></h2><button class="clear-recent" type="button">기록 삭제</button><div class="recent-docs" aria-live="polite"><p>최근에 본 문서가 없습니다.</p></div></section><section id="start"><h2>시작하기</h2><div class="doc-cards">${card('guide/overview', '서비스 이해하기', '리본의 대상과 다음 할 일을 안내하는 흐름', '▤')}${card('guide/quickstart', '개발 환경', 'FE·BE 실행과 설정을 확인하는 방법', '⌘')}${card('results/rest-api', 'REST API', '실제 계약에 맞춘 요청과 응답', '↗')}${card('reference/tests', '테스트', '정상·예외·경계·복구의 검증 방법', '✓')}</div></section><section id="features"><h2>가게 상태와 판단</h2><div class="doc-cards">${card('case/common', '상황 진단', '가게에 필요한 질문을 받아 Case 생성', '▦')}${card('results/common', '결과 알려주기', '현실의 답을 받아 상태와 계획 검토', '↻')}${card('conflicts/common', '충돌 확인', '기존값과 다른 사실 후보를 사용자에게 확인', '⇄')}${card('roadmap/common', '로드맵', '5단계의 작업과 진행 상태 확인', '≡')}${card('logs/common', '작업 기록', '입력과 판단·작업 이력 다시 보기', '◷')}</div></section><section id="documents"><h2>서류</h2><div class="doc-cards">${card('documents/common', '서류함과 점검', '서류 종류·값 확인, 누락과 금액 대조', '▧')}${card('documents/rest-api', '서류 API', '업로드·확인·점검·ZIP 다운로드 계약', '{ }')}</div></section><section id="integration"><h2>카카오 연동과 기술</h2><div class="doc-cards">${card('auth/common', '카카오 로그인', '공식 문서와 리본 인증 흐름의 연결', 'Login')}${card('agent/architecture', 'AI 실행 구조', 'Procedure·Info·Supervisor·Review', '◇')}${card('operations/common', '실패와 복구', '접수·판단·재시작과 복구 경로', '↺')}</div></section><section id="updates"><h2>문서 갱신</h2>${paragraph('2026년 11월 11일까지 서비스 변경 시 문서도 함께 확인합니다. API 표·타입과 작업 목록은 코드에서 생성하고, 기능 설명과 화면은 변경 근거를 대조해 갱신합니다.')}<div class="home-links"><a href="/safety/">운영철학과 안심 이용 →</a><a href="${url('reference/changes')}">변경 이력 →</a><a href="${url('reference/maintenance')}">갱신 절차 →</a><a href="/developers/downloads/service-guide.pdf">2026.11.07 설명서 PDF ↗</a></div></section>`
}

function navigation(active) {
  return `<a class="sidebar-home${active === 'home' ? ' active' : ''}" href="${url('home')}">문서 홈</a>${groups.map(g => `<section class="nav-group"><h2>${e(g.title)}</h2>${g.items.map(([id, title]) => {
    if (byId.has(id)) return `<a class="nav-leaf${active === id ? ' active' : ''}" href="${url(id)}"${active === id ? ' aria-current="page"' : ''}>${e(title)}</a>`
    const children = allPages.filter(p => p.family === id).sort((a, b) => Number(a.id.endsWith('rest-api')) - Number(b.id.endsWith('rest-api')))
    return `<details class="nav-category"${children.some(p => p.id === active) ? ' open' : ''}><summary>${e(title)}<span class="chevron" aria-hidden="true"></span></summary><div>${children.map(p => `<a class="nav-leaf${p.id === active ? ' active' : ''}" href="${url(p.id)}"${p.id === active ? ' aria-current="page"' : ''}>${p.id.endsWith('common') ? '이해하기' : p.id.endsWith('settings') ? '설정하기' : 'REST API'}</a>`).join('')}</div></details>`
  }).join('')}</section>`).join('')}`
}

const built = new Map()
const search = []
for (const page of allPages) {
  let body
  if (page.home) body = homeContent()
  else if (page.api) body = apiContent(page)
  else if (page.schemas) body = Object.entries(schemas).sort(([a], [b]) => a.localeCompare(b)).map(([name, schema]) => `<section id="${e(name)}"><h2>${e(name)}</h2>${schema.description ? paragraph(schema.description) : ''}${schema.enum ? table(['값', '설명'], schema.enum.map(value => [e(value), '계약에 정의된 허용 값'])) : fieldTable(schema)}</section>`).join('')
  else body = renderSections(page.sections)
  const familyTabs = page.family ? `<nav class="doc-tabs" aria-label="${e(page.title)} 문서 종류">${allPages.filter(p => p.family === page.family).map(p => `<a href="${url(p.id)}"${p.id === page.id ? ' aria-current="page"' : ''}>${p.id.endsWith('common') ? '이해하기' : p.id.endsWith('settings') ? '설정하기' : 'REST API'}</a>`).join('')}<a href="${url('reference/errors')}">에러 코드</a></nav>` : ''
  const toc = page.home ? [['recent', '최근 본 문서'], ['start', '시작하기'], ['features', '가게 상태와 판단'], ['documents', '서류'], ['integration', '카카오 연동과 기술'], ['updates', '문서 갱신']] : page.api ? page.api.operations.map((key, i) => [`operation-${i + 1}`, operationNotes[key].title]) : page.schemas ? Object.keys(schemas).sort().map(name => [name, name]) : page.sections.map(s => [s.id, s.title])
  const sourceLinks = page.sources.map(file => contract.source_hashes[file] ? `<a href="https://github.com/kakaotechcampus-4/ktc4-kangwon-4/blob/${contract.source_revision}/${e(file)}" target="_blank" rel="noopener noreferrer">${e(file)}</a>` : `<span>${e(file)}</span>`).join(' · ')
  const idx = allPages.indexOf(page)
  const previous = allPages[idx - 1], next = allPages[idx + 1]
  const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="${e(page.description)}"><title>${e(page.title)} - 리본 개발 문서</title><link rel="icon" type="image/svg+xml" href="/developers/assets/reborn-hammer.svg"><link rel="stylesheet" href="/developers/assets/docs.css"><script src="/developers/assets/docs.js" defer></script></head><body data-page="${e(page.id)}"><a class="skip-link" href="#main">본문 바로가기</a><header class="global-header"><a class="wordmark" href="${url('home')}"><img src="/developers/assets/reborn-hammer.svg" width="25" height="25" alt=""><span>reborn<span class="thin"> developers</span></span></a><nav class="global-nav" aria-label="주 메뉴"><a href="/">서비스</a><a class="current" href="${url('home')}">문서</a><a href="${url('results/rest-api')}">API</a><a href="https://github.com/kakaotechcampus-4/ktc4-kangwon-4" target="_blank" rel="noopener noreferrer">GitHub</a><a href="/safety/">안심가이드</a></nav><button class="search-open" aria-haspopup="dialog"><svg width="17" height="17" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.4"/><path d="m12.5 12.5 5 5" stroke="currentColor" stroke-width="1.4"/></svg><span>검색어를 입력해 주세요.</span><kbd>⌘ K</kbd></button><a class="service-button" href="/">서비스로</a></header><div class="breadcrumb-bar"><button class="menu-toggle" aria-controls="sidebar" aria-expanded="false" aria-label="사이드 메뉴 열기">☰</button><a href="${url('home')}">문서</a>${page.id !== 'home' ? `<span>›</span><span>${e(page.title)}</span>` : ''}</div><div class="page-layout"><aside class="sidebar" id="sidebar" aria-label="사이드 메뉴">${navigation(page.id)}<div class="sidebar-meta">RE:BORN · 카카오테크 캠퍼스<br>코드 ${e(contract.source_revision.slice(0, 7))}<br>확인 ${e(contract.checked_at.slice(0, 10))}</div></aside><div class="doc-layout${page.home ? ' home-layout' : ''}"><main id="main" tabindex="-1"><header class="doc-header"><h1>${e(page.title)}</h1><p>${e(page.description)}</p>${page.home ? '' : `<div class="doc-meta">코드 기준 ${e(contract.source_revision.slice(0, 7))} <span>·</span> 확인 ${e(contract.checked_at.slice(0, 10))}</div>`}</header>${familyTabs}${stale.length ? callout('코드 확인 필요', '기준 이후 코드 변경이 감지됐습니다. 문서 갱신 절차로 설명과 계약을 다시 확인하세요.', 'warning') : ''}${body}<footer class="doc-footer">${sourceLinks ? `<div class="source-links"><strong>구현 근거</strong>${sourceLinks}</div>` : ''}<div class="page-switch">${previous ? `<a href="${url(previous.id)}"><small>이전</small><span>← ${e(previous.title)}</span></a>` : '<span></span>'}${next ? `<a href="${url(next.id)}"><small>다음</small><span>${e(next.title)} →</span></a>` : ''}</div><p>이 문서는 RE:BORN 프로젝트의 구현을 설명합니다. <a href="https://developers.kakao.com/docs/ko/documentation-guideline/notation" target="_blank" rel="noopener noreferrer">카카오디벨로퍼스의 공개 문서 구성·표기</a>를 참고했습니다.</p><div class="footer-meta"><span>© RE:BORN Team</span><a href="/safety/">운영철학·안심 이용</a><a href="${url('reference/maintenance')}">문서 갱신 기준</a><a href="/developers/openapi.json" download>OpenAPI JSON</a></div></footer></main>${page.home ? '' : `<aside class="page-toc" aria-label="이 문서의 목차"><strong>${e(page.title)}</strong>${toc.map(([id, title]) => `<a href="#${e(id)}">${e(title)}</a>`).join('')}<button type="button" class="to-top">맨 위로 ↑</button></aside>`}</div></div><dialog class="search-dialog" aria-label="문서 검색"><div class="search-input-row"><label for="doc-search">문서 검색</label><input id="doc-search" type="search" placeholder="기능, API 또는 에러 코드를 검색하세요" autocomplete="off"><button class="search-close" aria-label="검색 닫기">Esc</button></div><div id="search-status" role="status" aria-live="polite"></div><ul id="search-results" aria-label="검색 결과"></ul></dialog><div class="toast" role="status" hidden></div></body></html>`
  built.set(`ko/${page.id}/index.html`, html)
  search.push({ id: page.id, title: page.title, description: page.description, url: url(page.id), text: body.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').slice(0, 120000) })
}
for (const [file, html] of built) {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1])
  if (new Set(ids).size !== ids.length) throw new Error(`문서 앵커가 중복됩니다: ${file}`)
  for (const match of html.matchAll(/href="(\/developers\/ko\/[^"#]+)(?:#([^"]+))?"/g)) {
    const target = match[1].replace('/developers/ko/', '').replace(/\/$/, '')
    if (!byId.has(target)) throw new Error(`연결되지 않은 문서: ${match[1]}`)
    if (match[2] && !built.get(`ko/${target}/index.html`).includes(`id="${match[2]}"`)) throw new Error(`연결되지 않은 앵커: ${match[1]}#${match[2]}`)
  }
}
for (const id of imageIds) if (!existsSync(resolve(source, screenshots[id].file))) throw new Error(`캡처 파일이 없습니다: ${id}`)
for (const file of ['리본_서비스_전체_설명서.pdf', '테스트_케이스.csv']) if (!existsSync(join(root, 'docs/final-guide', file))) throw new Error(`다운로드 파일이 없습니다: ${file}`)
buildSafety({ check, contract, documentationIds: new Set(byId.keys()), documentationPages: built })
if (check) {
  console.log(`문서 검사 통과: ${allPages.length}개 문서, API ${operations.length}개, 작업 ${contract.roadmap.length}개, 소스 ${Object.keys(contract.source_hashes).length}개.`)
  process.exit(0)
}

rmSync(destination, { recursive: true, force: true })
mkdirSync(join(destination, 'assets/screens'), { recursive: true })
mkdirSync(join(destination, 'downloads'), { recursive: true })
for (const [file, content] of built) { const output = join(destination, file); mkdirSync(dirname(output), { recursive: true }); writeFileSync(output, content) }
for (const file of ['docs.css', 'docs.js']) copyFileSync(join(source, file), join(destination, 'assets', file))
copyFileSync(join(root, 'frontend/src/assets/brand/reborn-hammer.svg'), join(destination, 'assets/reborn-hammer.svg'))
for (const id of imageIds) copyFileSync(resolve(source, screenshots[id].file), join(destination, `assets/screens/${id}.png`))
const downloads = [['리본_서비스_전체_설명서.pdf', 'service-guide.pdf'], ['테스트_케이스.csv', 'test-cases.csv']]
for (const [from, to] of downloads) copyFileSync(join(root, 'docs/final-guide', from), join(destination, 'downloads', to))
writeFileSync(join(destination, 'search-index.json'), JSON.stringify(search))
writeFileSync(join(destination, 'openapi.json'), JSON.stringify(spec, null, 2))
writeFileSync(join(destination, 'manifest.json'), JSON.stringify({ source_revision: contract.source_revision, checked_at: contract.checked_at, maintain_through: contract.maintain_through, pages: allPages.map(p => ({ id: p.id, title: p.title, url: url(p.id) })), api_operations: operations.length, roadmap_tasks: contract.roadmap.length }, null, 2))
writeFileSync(join(destination, 'index.html'), '<!doctype html><html lang="ko"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/developers/ko/home/"><title>리본 개발 문서</title><a href="/developers/ko/home/">문서 홈으로 이동</a></html>')
console.log(`문서 생성 완료: ${allPages.length}개 페이지 → frontend/public/developers/`)
