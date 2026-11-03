import type { DocumentsView, DocumentView } from '../types/view'

/**
 * 서류함 Mock 데이터. Preview 의 가짜 로그인과 `?mock=` 으로 볼 때만 쓴다.
 *
 * 서버 응답(#159)을 어댑터로 바꾼 뒤의 모양이다. 종류 이름·확인 필요 여부·빠진 서류 문구는
 * 서버가 정하는 값이라, 여기서도 서버가 낼 법한 값만 둔다. 시안의 "6종 중 n종" 같은 셈은 넣지
 * 않는다 — 그런 셈을 서버가 하지 않는다.
 */
const DOCUMENTS: DocumentView[] = [
  {
    id: 'mock-construction',
    filename: '철거공사내역서.pdf',
    kind: 'CONSTRUCTION_STATEMENT',
    kindLabel: '철거공사내역서',
    needsConfirmation: false,
    fields: [
      { name: 'supplier', label: '공급자', value: '그린철거' },
      { name: 'amount', label: '금액', value: '3,300,000원' },
    ],
  },
  {
    id: 'mock-invoice',
    filename: '전자세금계산서.pdf',
    kind: 'TAX_INVOICE',
    kindLabel: '전자세금계산서',
    needsConfirmation: false,
    fields: [
      { name: 'supply_amount', label: '공급가액', value: '3,000,000원' },
      { name: 'tax_amount', label: '세액', value: '300,000원' },
    ],
  },
  {
    id: 'mock-before-photo',
    filename: 'IMG_0412.jpg',
    kind: 'BEFORE_PHOTO',
    kindLabel: '철거 전 사진',
    needsConfirmation: true,
    fields: [],
  },
  {
    id: 'mock-closure-certificate',
    filename: '폐업사실증명원.pdf',
    kind: 'CLOSURE_CERTIFICATE',
    kindLabel: '폐업사실증명원',
    needsConfirmation: false,
    fields: [{ name: 'closure_date', label: '폐업일', value: '2026-10-31' }],
  },
]

/** `?mock=docs-issues`: 점검에서 빠진 서류가 나온 상태 */
export const mockDocumentsWithIssues: DocumentsView = {
  documents: DOCUMENTS,
  check: {
    status: 'ISSUES',
    steps: [
      { name: '서류 종류 나누기', status: 'DONE' },
      { name: '빠진 서류 찾기', status: 'NEEDS_CONFIRMATION' },
    ],
    issues: ['정산 점검 목록에서 빠진 서류: 이체확인증'],
  },
}

/** 기본: 서류를 모았고 아직 점검하지 않은 상태 */
export const mockDocuments: DocumentsView = { documents: DOCUMENTS, check: null }

/** 가짜 올리기가 걸리는 시간. 실제로는 서류 한 장에 수십 초가 걸릴 수 있다(#159) */
export const MOCK_UPLOAD_MS = 1_500

/** 가짜 올리기. 고른 파일 이름으로 "종류 확인 필요" 서류 한 장을 더한다 */
export function simulateUpload(view: DocumentsView, file: File): Promise<DocumentsView> {
  const added: DocumentView = {
    id: `mock-upload-${Date.now()}`,
    filename: file.name,
    kind: 'UNKNOWN',
    kindLabel: '종류 확인 필요',
    needsConfirmation: true,
    fields: [],
  }
  return new Promise((resolve) => {
    // 서버처럼 서류가 바뀌면 지난 점검은 지운다
    window.setTimeout(() => resolve({ documents: [...view.documents, added], check: null }), MOCK_UPLOAD_MS)
  })
}
