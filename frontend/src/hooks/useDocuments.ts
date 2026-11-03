import { useCallback, useRef, useState } from 'react'
import { useLocation } from 'react-router'

import { DOCUMENT_KINDS } from '../adapters/documents'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import {
  mockDocuments,
  mockDocumentsComplete,
  mockDocumentsWithIssues,
  simulateCheck,
  simulateUpload,
} from '../mocks/documents'
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

/** 점검을 보내는 중인지. 점검 결과 자체는 `view.check` 에 담긴다 */
export type CheckAction = 'IDLE' | 'RUNNING' | 'FAILED'

/**
 * 서류함 데이터와 올리기 · 빼기.
 *
 * TODO(#159): 서류 API 가 머지되면 `GET /cases/documents` 로 불러오고, 올리기는
 * `POST /cases/documents`(파일, 긴 제한 시간), 빼기는 `DELETE` 로 잇는다. 그 전에는 실서버에서
 * `UNAVAILABLE` 이고, Mock(`?mock=`)으로 볼 때만 예시 서류와 가짜 올리기가 돈다.
 * `?mock=docs-issues` 면 점검에서 빠진 서류가 나온 상태다.
 */
export function useDocuments() {
  const { search, pathname } = useLocation()
  const usesMock = usesMockData(search)
  const mockKey = readMockKey(search)

  const [mockView, setMockView] = useState<DocumentsView>(() =>
    mockKey === 'docs-issues'
      ? mockDocumentsWithIssues
      : // 정산 파일 화면은 Mock 이 화면마다 새로 시작해도 통과한 점검에서 연다. 점검 화면에서 넘어온 흐름이 끊기지 않게
        mockKey === 'docs-complete' || pathname === '/docs/done'
        ? mockDocumentsComplete
        : mockDocuments,
  )
  const [checking, setChecking] = useState<CheckAction>('IDLE')
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

  /**
   * 사장님이 종류와 값을 확인했다. `values` 는 확인 시트에 보인 칸 전부다 — 서버는 받은 값만
   * 확인한 것으로 저장해서, 빠진 칸은 점검에서 값이 없는 것으로 본다(#159).
   *
   * TODO(#159): `POST /cases/documents/{id}/confirm` `{kind, confirmed_fields}` 로 잇는다.
   */
  const confirm = useCallback(
    (id: string, kind: string, values: Record<string, string>) => {
      if (!usesMock) return
      const kindLabel = DOCUMENT_KINDS.find((option) => option.kind === kind)?.label ?? kind
      setMockView((view) => ({
        documents: view.documents.map((document) =>
          document.id !== id
            ? document
            : {
                ...document,
                kind,
                kindLabel,
                needsConfirmation: false,
                fields: document.fields.map((field) => ({ ...field, value: values[field.name] ?? field.value })),
              },
        ),
        check: null,
      }))
    },
    [usesMock],
  )

  /**
   * 정산 서류 점검. 신청인 이름은 이체확인증의 보낸 사람과, 실제 폐업일은 폐업사실증명원과 맞춰 본다.
   * 폐업일을 비우면 서버가 "폐업일 미확인"으로 점검을 끝내지 않는다(#159). 이름·날짜는 점검에만
   * 쓰이고 Case 에는 남지 않는다.
   *
   * TODO(#159): `POST /cases/documents/check` `{applicant_name, closure_date}` 로 잇는다.
   */
  const runCheck = useCallback(
    async (applicantName: string, closureDate: string | null) => {
      void applicantName
      void closureDate
      if (!usesMock) return
      setChecking('RUNNING')
      setMockView(await simulateCheck(mockView))
      setChecking('IDLE')
    },
    [usesMock, mockView],
  )

  const query: DocumentsQuery = usesMock ? { status: 'READY', view: mockView } : { status: 'UNAVAILABLE' }
  return { query, action, upload, remove, confirm, checking, runCheck }
}
