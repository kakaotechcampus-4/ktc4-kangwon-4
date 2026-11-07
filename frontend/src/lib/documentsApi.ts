import { toDocumentsView } from '../adapters/documents'
import type {
  DocumentCheckRequest,
  DocumentConfirmRequest,
  DocumentFieldName,
  DocumentKind,
  DocumentListResponse,
} from '../types/api'
import type { DocumentsView } from '../types/view'
import { ApiError, request } from './api'

/**
 * 서류 API(#159). 목록·올리기·확인·빼기·점검은 모두 같은 목록 모양을 돌려주고, 여기서 화면 모양으로
 * 바꿔 돌려준다. 받은 모양을 읽지 못하면 `ApiError` 로 끊는다 — 깨진 목록을 빈 서류함으로 그리면
 * 사장님은 올린 서류가 사라진 줄 안다.
 *
 * 실패 응답은 `ApiError`(401 은 `UnauthorizedError`)로 올라간다. 404 Case 없음, 422 받을 수 없는
 * 파일·요청(문서 Tool 의 거절 사유), 502 서류를 읽지 못함(모델·글자 인식 실패, 올리기에서만).
 */

/**
 * 올리기 제한 시간. 서버가 서류를 다 읽을 때까지 답을 붙잡고 있어 수십 초가 걸린다(#159).
 *
 * **Vercel이 끊기 전에 FE가 먼저 끊는다.** 배포 화면은 Vercel(`/api`)을 거치는데, Vercel은 120초 안에
 * 첫 응답이 없으면 502(`ROUTER_EXTERNAL_TARGET_ERROR`)로 끊는다(#170 현석님). 그 502는 서버의
 * "서류를 읽지 못함"(502)과 구별되지 않아, 아직 읽는 중인 서류에 "다시 찍어 주세요"가 뜬다.
 * 그래서 120초보다 조금 짧게 두어 "다시 올려 주세요" 안내가 나오게 한다. 10초는 응답이 오가는 여유다.
 *
 * 끊겨도 서버는 읽기를 마치고 저장해 두어, 같은 파일을 다시 올리면 그 결과를 쓴다(#159).
 * 한 장에 최대 몇 초 걸리는지는 정해진 값이 없다. 배포 화면에서 실제 서류로 재 보고 고친다.
 */
export const UPLOAD_TIMEOUT_MS = 110_000

async function readList(response: Response): Promise<DocumentsView> {
  const view = toDocumentsView((await response.json()) as DocumentListResponse | null)
  if (view === null) throw new ApiError(response.status, '서류 목록을 읽지 못했습니다.')
  return view
}

export async function fetchDocuments(): Promise<DocumentsView> {
  return readList(await request('/cases/documents'))
}

/** 파일 한 장을 올린다. 종류는 서버(문서 Tool)가 나눈다 */
export async function uploadDocument(file: File): Promise<DocumentsView> {
  const form = new FormData()
  form.append('file', file, file.name)
  return readList(await request('/cases/documents', { method: 'POST', body: form, timeoutMs: UPLOAD_TIMEOUT_MS }))
}

/** 사장님이 확인한 종류와 값 전부를 보낸다. 빠진 칸은 서버가 "값 없음"으로 저장한다 */
export async function confirmDocument(id: string, kind: string, values: Record<string, string>): Promise<DocumentsView> {
  const body: DocumentConfirmRequest = {
    kind: kind as DocumentKind,
    confirmed_fields: values as Partial<Record<DocumentFieldName, string>>,
  }
  return readList(await request(`/cases/documents/${encodeURIComponent(id)}/confirm`, { method: 'POST', body }))
}

export async function removeDocument(id: string): Promise<DocumentsView> {
  return readList(await request(`/cases/documents/${encodeURIComponent(id)}`, { method: 'DELETE' }))
}

export async function checkDocuments(storeName: string, applicantName: string, closureDate: string | null): Promise<DocumentsView> {
  const body: DocumentCheckRequest = { store_name: storeName, applicant_name: applicantName, closure_date: closureDate }
  return readList(await request('/cases/documents/check', { method: 'POST', body }))
}

/**
 * 정산 제출 파일(ZIP)을 받는다. 점검이 통과했을 때만 서버가 준다(그 밖에는 422).
 *
 * 로그인 헤더를 실어야 해서 링크로 열 수 없다. 받은 파일을 브라우저 내려받기로 넘긴다.
 *
 * 제한 시간은 올리기와 같다(`UPLOAD_TIMEOUT_MS`). 기본 15초는 응답을 다 받는 것까지 세는데, ZIP 에는 한 장에
 * 20MB까지인 사진·내역서가 여러 장 들어가 휴대폰 연결로는 받는 도중 끊긴다.
 */
export async function downloadSettlement(): Promise<Blob> {
  const response = await request('/cases/documents/settlement.zip', { timeoutMs: UPLOAD_TIMEOUT_MS })
  return response.blob()
}
