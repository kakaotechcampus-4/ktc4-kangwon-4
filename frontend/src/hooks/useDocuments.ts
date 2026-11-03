import { useCallback, useRef, useState } from 'react'
import { useLocation } from 'react-router'

import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import { mockDocuments, mockDocumentsWithIssues, simulateUpload } from '../mocks/documents'
import type { DocumentsView } from '../types/view'

/**
 * 서버가 받는 가장 큰 파일(#159 `MAX_UPLOAD_BYTES`, 20MB). 넘으면 서버가 422 로 막는다.
 *
 * 업무 판단이 아니라 서버가 거절하는 경계라 여기 둔다(`MAX_EMPLOYEE_COUNT`와 같은 이유).
 * 고르는 순간 막아, 큰 사진을 수십 초 올린 뒤에야 거절당하지 않게 한다.
 */
export const MAX_UPLOAD_BYTES = 20_000_000

/** 서류함을 불러온 상태 */
export type DocumentsQuery =
  /** 서류 API 가 아직 없다(#159 머지 전). 실서버에서만 */
  | { status: 'UNAVAILABLE' }
  | { status: 'READY'; view: DocumentsView }

/** 올리기 · 빼기의 결과. 실패했으면 화면이 안내를 띄운다 */
export type DocumentAction = 'IDLE' | 'UPLOADING' | 'TOO_LARGE' | 'FAILED'

/**
 * 서류함 데이터와 올리기 · 빼기.
 *
 * TODO(#159): 서류 API 가 머지되면 `GET /cases/documents` 로 불러오고, 올리기는
 * `POST /cases/documents`(파일, 긴 제한 시간), 빼기는 `DELETE` 로 잇는다. 그 전에는 실서버에서
 * `UNAVAILABLE` 이고, Mock(`?mock=`)으로 볼 때만 예시 서류와 가짜 올리기가 돈다.
 * `?mock=docs-issues` 면 점검에서 빠진 서류가 나온 상태다.
 */
export function useDocuments() {
  const { search } = useLocation()
  const usesMock = usesMockData(search)
  const mockKey = readMockKey(search)

  const [mockView, setMockView] = useState<DocumentsView>(() =>
    mockKey === 'docs-issues' ? mockDocumentsWithIssues : mockDocuments,
  )
  const [action, setAction] = useState<DocumentAction>('IDLE')
  /** 한 번에 한 장만. 올리는 동안 또 고르면 두 장이 서로의 결과를 덮는다 */
  const busy = useRef(false)

  const upload = useCallback(
    async (file: File) => {
      if (busy.current) return
      if (file.size > MAX_UPLOAD_BYTES) return setAction('TOO_LARGE')

      busy.current = true
      setAction('UPLOADING')
      try {
        if (usesMock) setMockView(await simulateUpload(mockView, file))
        setAction('IDLE')
      } catch {
        setAction('FAILED')
      } finally {
        busy.current = false
      }
    },
    [usesMock, mockView],
  )

  const remove = useCallback(
    (id: string) => {
      if (!usesMock) return
      // 서류가 바뀌면 지난 점검은 지운다(서버와 같음)
      setMockView((view) => ({ documents: view.documents.filter((document) => document.id !== id), check: null }))
    },
    [usesMock],
  )

  const query: DocumentsQuery = usesMock ? { status: 'READY', view: mockView } : { status: 'UNAVAILABLE' }
  return { query, action, upload, remove }
}
