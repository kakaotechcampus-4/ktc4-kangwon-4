import { vi } from 'vitest'

import type { DocumentListResponse, DocumentResponse } from '../types/api'

/**
 * 서류 API(#159) 테스트용 가짜 서버. 서류함·점검·정산 파일 화면 테스트가 같이 쓴다(테스트 전용, 화면은 쓰지 않는다).
 *
 * 화면이 쓰는 데이터는 테스트가 들고 있는다(FE CLAUDE.md "테스트"). 여기 있는 것은 서버 모양의
 * 응답을 만드는 도구뿐이고, 어떤 서류를 줄지는 테스트마다 정한다.
 */

export const serverDocument = (overrides: Partial<DocumentResponse> = {}): DocumentResponse => ({
  document_id: 'doc-1',
  filename: 'transfer.pdf',
  kind: 'TRANSFER',
  kind_label: '이체확인증',
  needs_confirmation: false,
  fields: [{ name: 'amount', value: '3,300,000원', page: 1 }],
  confirmed_fields: null,
  ...overrides,
})

export const serverList = (
  documents: DocumentResponse[],
  check: DocumentListResponse['check'] = null,
): DocumentListResponse => ({ documents, check })

export const completeCheck: DocumentListResponse['check'] = {
  status: 'COMPLETE',
  steps: [{ name: '빠진 서류 찾기', status: 'DONE' }],
  issues: [],
  checked_at: '2026-11-04T10:00:00+09:00',
}

export const issuesCheck: DocumentListResponse['check'] = {
  status: 'ISSUES',
  steps: [{ name: '빠진 서류 찾기', status: 'NEEDS_CONFIRMATION' }],
  issues: [{ code: 'MISSING_TRANSFER', document_ids: [], message: '정산 점검 목록에서 빠진 서류: 이체확인증' }],
  checked_at: '2026-11-04T10:00:00+09:00',
}

export type Answer = (init?: RequestInit) => Response | Promise<Response>

export const json =
  (body: unknown): Answer =>
  () =>
    new Response(JSON.stringify(body), { status: 200 })

export const status =
  (code: number): Answer =>
  () =>
    new Response(null, { status: code })

/** 답을 주지 않다가, 요청이 끊기면(제한 시간) 그 이유로 거부한다 — 실제 `fetch` 와 같다 */
export const hanging: Answer = (init) =>
  new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))
  })

/**
 * 요청마다 차례로 답한다. 목록이 끝나면 마지막 답을 계속 준다.
 * 보낸 요청은 `calls` 로 주소·방법·본문을 읽는다.
 */
export function serve(...answers: Answer[]) {
  let count = 0
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => answers[Math.min(count++, answers.length - 1)](init))
  vi.stubGlobal('fetch', fetchMock)
  return {
    fetchMock,
    calls: () =>
      fetchMock.mock.calls.map(([url, init]) => ({
        url: url as string,
        method: (init as RequestInit | undefined)?.method ?? 'GET',
        body: (init as RequestInit | undefined)?.body,
      })),
  }
}
