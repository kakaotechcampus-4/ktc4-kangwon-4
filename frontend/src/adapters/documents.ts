import type {
  DocumentCheckStatus,
  DocumentCheckView,
  DocumentFieldView,
  DocumentsView,
  DocumentView,
} from '../types/view'
import { isReadableText } from './case'

/**
 * 서류 API(#159)의 목록 응답을 서류함 모양으로 바꾼다.
 *
 * 종류 이름(`kind_label`)·확인 필요 여부(`needs_confirmation`)·빠진 서류 문구(`issues[].message`)는
 * 서버가 정해서 준다. 화면은 그대로 옮기기만 한다 — 어떤 서류가 정산에 필요한지 FE가 셈하면
 * 점검 규칙이 두 곳에 생긴다(FE 규칙 1).
 *
 * 응답 모양은 `types/api.ts` 의 `DocumentListResponse`(#159)다. 그래도 `unknown` 으로 받아 칸마다 본다 —
 * `check.status` 처럼 서버가 글자로 열어 둔 칸이 있고, 깨진 목록을 빈 서류함으로 그리면 안 된다.
 */

/**
 * 서류에서 꺼낸 값 이름 → 화면 말.
 *
 * 서버가 값마다 이름(`label`)을 주기로 했지만(#159 리뷰, 승준님 동의) 아직 들어가지 않았다.
 * 서버가 주면 그것을 쓰고, 없을 때만 이 표를 쓴다. 표에도 없으면 그 값은 보여주지 않는다 —
 * 영어 칸 이름을 사장님께 보여줄 수 없다.
 */
const FIELD_LABEL: Record<string, string> = {
  business_name: '상호',
  supplier: '공급자',
  buyer: '공급받는 자',
  sender: '보낸 사람',
  recipient: '받는 사람',
  account_holder: '예금주',
  amount: '금액',
  supply_amount: '공급가액',
  tax_amount: '세액',
  date: '날짜',
  closure_date: '폐업일',
  restoration_clause: '원상복구 조항',
}

/**
 * 사장님이 고를 수 있는 서류 종류. 서버 `DOCUMENT_LABELS`(#128 문서 Tool)와 같은 순서·이름이다.
 *
 * 종류를 모르는(`UNKNOWN`) 서류는 사장님이 여기서 골라 확인한다. 서버가 종류 목록을 응답에 싣기로
 * 했지만(#159 리뷰, 승준님 동의) 아직 들어가지 않아 FE가 들고 있다. 서버가 주게 되면 그쪽으로
 * 바꾼다. "종류 확인 필요"(`UNKNOWN`)는 고를 것이 아니라 뺐다.
 */
export const DOCUMENT_KINDS: readonly { kind: string; label: string }[] = [
  { kind: 'LEASE', label: '임대차계약서' },
  { kind: 'BUSINESS_REGISTRATION', label: '사업자등록 자료' },
  { kind: 'BUSINESS_LICENSE', label: '영업신고증' },
  { kind: 'CONSTRUCTION_STATEMENT', label: '철거공사내역서' },
  { kind: 'TAX_INVOICE', label: '전자세금계산서' },
  { kind: 'BEFORE_PHOTO', label: '철거 전 사진' },
  { kind: 'AFTER_PHOTO', label: '철거 후 사진' },
  { kind: 'TRANSFER', label: '이체확인증' },
  { kind: 'CLOSURE_CERTIFICATE', label: '폐업사실증명원' },
  { kind: 'BANK_COPY', label: '통장 사본' },
  { kind: 'CLOSURE_RECEIPT', label: '폐업신고 접수증' },
  { kind: 'CARD_SALES', label: '카드 매출 내역' },
  { kind: 'CASH_SALES', label: '현금영수증 매출' },
  { kind: 'PURCHASE_INVOICE', label: '매입 세금계산서' },
  { kind: 'DEPOSIT_STATEMENT', label: '보증금 공제 내역' },
]

const CHECK_STATUSES: readonly DocumentCheckStatus[] = ['COMPLETE', 'ISSUES', 'ERROR']
const STEP_STATUSES = ['WAITING', 'RUNNING', 'DONE', 'NEEDS_CONFIRMATION', 'ERROR'] as const

type Row = Record<string, unknown>
const asRow = (value: unknown): Row | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : null

/**
 * 꺼낸 값들. 사장님이 확인한 값이 있으면 그것이 맞는 값이라 그쪽을 쓴다.
 * 서버가 같은 칸을 여러 쪽에서 꺼냈으면(여러 페이지) 처음 것만 둔다.
 */
function toFields(fields: unknown, confirmed: unknown): DocumentFieldView[] | null {
  if (!Array.isArray(fields)) return null

  const values = new Map<string, { value: string; label?: string }>()
  for (const item of fields) {
    const row = asRow(item)
    if (row === null || !isReadableText(row.name) || typeof row.value !== 'string') return null
    if (!values.has(row.name)) {
      values.set(row.name, { value: row.value, label: isReadableText(row.label) ? row.label : undefined })
    }
  }

  const confirmedRow = asRow(confirmed)
  if (confirmedRow !== null) {
    values.clear()
    for (const [name, value] of Object.entries(confirmedRow)) {
      if (typeof value === 'string') values.set(name, { value })
    }
  }

  // 이름을 모르는 칸도 버리지 않는다. 화면에는 안 보이지만, 확인할 때 원래 값 그대로 같이 보내야
  // 서버가 그 칸을 "값 없음"으로 저장하지 않는다(#159: 받은 값만 확인한 값으로 남긴다)
  return [...values].map(([name, { value, label }]) => ({ name, label: label ?? FIELD_LABEL[name] ?? null, value }))
}

function toDocument(value: unknown): DocumentView | null {
  const row = asRow(value)
  if (row === null) return null

  const { document_id, filename, kind, kind_label, needs_confirmation } = row
  const fields = toFields(row.fields, row.confirmed_fields)
  if (
    !isReadableText(document_id) ||
    typeof filename !== 'string' ||
    !isReadableText(kind) ||
    !isReadableText(kind_label) ||
    typeof needs_confirmation !== 'boolean' ||
    fields === null
  ) {
    return null
  }

  return { id: document_id, filename, kind, kindLabel: kind_label, needsConfirmation: needs_confirmation, fields }
}

function toCheck(value: unknown): DocumentCheckView | null | undefined {
  if (value === null) return null
  const row = asRow(value)
  if (row === null || !CHECK_STATUSES.includes(row.status as DocumentCheckStatus)) return undefined
  if (!Array.isArray(row.steps) || !Array.isArray(row.issues)) return undefined

  const steps: DocumentCheckView['steps'] = []
  for (const item of row.steps) {
    const step = asRow(item)
    if (step === null || !isReadableText(step.name) || !STEP_STATUSES.includes(step.status as never)) return undefined
    steps.push({ name: step.name, status: step.status as DocumentCheckView['steps'][number]['status'] })
  }

  const issues: string[] = []
  for (const item of row.issues) {
    const message = asRow(item)?.message
    if (!isReadableText(message)) return undefined
    issues.push(message)
  }

  return { status: row.status as DocumentCheckStatus, steps, issues }
}

/**
 * 목록 응답을 서류함으로. 받을 수 없는 모양이면 `null`(화면이 "불러오지 못했어요"로 그린다).
 *
 * **한 장이라도 깨져 있으면 통째로 버린다.** 깨진 서류만 빼고 보여주면 사장님은 올린 서류가
 * 사라진 줄 알고 다시 올리고, 점검 결과의 "빠진 서류"와도 어긋난다.
 */
export function toDocumentsView(body: unknown): DocumentsView | null {
  const row = asRow(body)
  if (row === null || !Array.isArray(row.documents)) return null

  const documents: DocumentView[] = []
  for (const item of row.documents) {
    const document = toDocument(item)
    if (document === null) return null
    documents.push(document)
  }

  const check = toCheck(row.check ?? null)
  if (check === undefined) return null

  return { documents, check }
}
