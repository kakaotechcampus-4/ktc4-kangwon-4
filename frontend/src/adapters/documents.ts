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
 * 깨진 목록을 빈 서류함으로 그리면 안 된다.
 */

/**
 * 서류에서 꺼낸 값 이름 → 화면 말.
 *
 * FE와 BE가 따로 반영되는 동안 예전 응답에 label 키가 없을 때만 쓴다(#159 후속).
 * 새 서버의 이름을 이 표로 덮지 않는다. 모르는 칸은 값을 보존하되 영어 이름을 화면에 내지 않는다.
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
 * document_kinds 키가 없는 예전 BE 응답과 Mock에만 쓴다. 새 서버의 선택 목록은 그대로 사용한다.
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
function toFields(fields: unknown, confirmed: unknown, legacy: boolean): DocumentFieldView[] | null {
  if (!Array.isArray(fields)) return null

  const values = new Map<string, { value: string; label: string | null }>()
  for (const item of fields) {
    const row = asRow(item)
    if (row === null || !isReadableText(row.name) || typeof row.value !== 'string') return null
    if (!legacy && !Object.hasOwn(row, 'label')) return null
    const label = Object.hasOwn(row, 'label') ? row.label : FIELD_LABEL[row.name] ?? null
    if (Object.hasOwn(row, 'label') && (!isReadableText(label) || !label.trim())) return null
    if (!values.has(row.name)) {
      values.set(row.name, { value: row.value, label: label as string | null })
    }
  }

  const confirmedRow = asRow(confirmed)
  if (confirmedRow !== null) {
    const labels = new Map([...values].map(([name, field]) => [name, field.label]))
    values.clear()
    for (const [name, value] of Object.entries(confirmedRow)) {
      if (typeof value === 'string') {
        values.set(name, { value, label: labels.get(name) ?? (legacy ? FIELD_LABEL[name] ?? null : null) })
      }
    }
  }

  // 이름을 모르는 칸도 버리지 않는다. 화면에는 안 보이지만, 확인할 때 원래 값 그대로 같이 보내야
  // 서버가 그 칸을 "값 없음"으로 저장하지 않는다(#159: 받은 값만 확인한 값으로 남긴다)
  return [...values].map(([name, { value, label }]) => ({ name, label, value }))
}

function toDocument(value: unknown, legacy: boolean): DocumentView | null {
  const row = asRow(value)
  if (row === null) return null

  const { document_id, filename, kind, kind_label, needs_confirmation } = row
  const fields = toFields(row.fields, row.confirmed_fields, legacy)
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

function toDocumentKinds(row: Row): DocumentsView['documentKinds'] | null {
  if (!Object.hasOwn(row, 'document_kinds')) return DOCUMENT_KINDS
  if (!Array.isArray(row.document_kinds)) return null
  const kinds: { kind: string; label: string }[] = []
  for (const value of row.document_kinds) {
    const item = asRow(value)
    if (item === null || !isReadableText(item.kind) || !item.kind.trim() || !isReadableText(item.label) || !item.label.trim() ||
        kinds.some((option) => option.kind === item.kind)) return null
    kinds.push({ kind: item.kind, label: item.label })
  }
  return kinds
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
  // FE와 BE가 따로 반영되는 동안 예전 응답이 올 수 있다(#251). 키가 없을 때만 이름을 비운다.
  const storeName = Object.hasOwn(row, 'store_name') ? row.store_name : null
  if (storeName !== null && typeof storeName !== 'string') return null
  const documentKinds = toDocumentKinds(row)
  if (documentKinds === null) return null

  const documents: DocumentView[] = []
  for (const item of row.documents) {
    const document = toDocument(item, !Object.hasOwn(row, 'document_kinds'))
    if (document === null) return null
    documents.push(document)
  }

  const check = toCheck(row.check ?? null)
  if (check === undefined) return null

  return { storeName, documentKinds, documents, check }
}
