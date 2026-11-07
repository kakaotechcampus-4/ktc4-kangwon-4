import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { DOCUMENT_KINDS } from '../adapters/documents'
import { ApiError, TimeoutError, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import {
  checkDocuments,
  confirmDocument,
  fetchDocuments,
  removeDocument,
  uploadDocument,
} from '../lib/documentsApi'
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
  | { status: 'LOADING' }
  | { status: 'READY'; view: DocumentsView }
  /** 연결이 끊겼거나 서버가 답을 못 했거나, 받은 목록을 읽지 못했다 */
  | { status: 'LOAD_FAILED' }

/**
 * 올리기 · 확인 · 빼기의 결과. 실패했으면 화면이 안내를 띄운다.
 *
 *   TOO_LARGE      20MB 를 넘어 올리지 않았다
 *   TIMED_OUT      올리는 사이 기다림이 끊겼다. 서버는 읽기를 마치고 저장해 두니 같은 파일을 다시 올리면 된다
 *   UNREADABLE     서버가 서류를 읽지 못했다(502, 모델·글자 인식 실패)
 *   REJECTED       서버가 받지 않는 파일·요청이다(422)
 *   SAFETY_BLOCKED 안전 검사가 처리할 수 없는 내용으로 판정했다(422, AGENT_SAFETY_REFUSE). 같은 파일은 다시 올려도 같다
 *   CRISIS_SUPPORT 안전 검사가 위기 신호로 판정했다(422, AGENT_SAFETY_CRISIS_SUPPORT). 다시 올리라 하지 않고 상담 창구를 알린다
 *   UPLOAD_FAILED  연결이 끊기는 등 올리지 못했다
 *   CHANGE_FAILED  확인·빼기를 저장하지 못했다
 */
export type DocumentAction =
  | 'IDLE'
  | 'UPLOADING'
  | 'TOO_LARGE'
  | 'TIMED_OUT'
  | 'UNREADABLE'
  | 'REJECTED'
  | 'SAFETY_BLOCKED'
  | 'CRISIS_SUPPORT'
  | 'UPLOAD_FAILED'
  | 'CHANGE_FAILED'

/** 점검을 보내는 중인지. 점검 결과 자체는 `view.check` 에 담긴다 */
export type CheckAction = 'IDLE' | 'RUNNING' | 'FAILED'

/** 빈 서류함. Case 가 없으면(404) 서류도 없다 */
const EMPTY: DocumentsView = { documents: [], check: null }

/**
 * 서류함 데이터와 올리기 · 확인 · 빼기 · 점검(#159). 서류함 · 점검 · 정산 파일 화면이 같이 쓴다.
 *
 * 화면에 들어올 때 목록을 한 번 묻고, 바꾸는 요청마다 서버가 돌려준 목록으로 바꾼다. 저장이 끝나기
 * 전에는 목록을 바꾸지 않는다(FE 규칙 2). 401 은 로그인으로 보낸다.
 *
 * Mock(`?mock=`)으로 볼 때는 서버를 부르지 않고 예시 서류와 가짜 동작이 돈다. `?mock=docs-issues` 면
 * 점검에서 빠진 서류가 나온 상태, `?mock=docs-complete` 면 점검을 통과한 상태다.
 */
export function useDocuments() {
  const { search, pathname } = useLocation()
  const navigate = useNavigate()
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
  const [serverQuery, setServerQuery] = useState<DocumentsQuery>({ status: 'LOADING' })
  const [attempt, setAttempt] = useState(0)
  const [checking, setChecking] = useState<CheckAction>('IDLE')
  const [action, setAction] = useState<DocumentAction>('IDLE')
  /** 한 번에 한 장만. 올리는 동안 또 고르면 두 장이 서로의 결과를 덮는다 */
  const busy = useRef(false)
  /** 떠난 화면이 늦게 온 응답으로 상태를 바꾸지 않게 한다 */
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  useEffect(() => {
    if (usesMock) return
    let current = true
    fetchDocuments().then(
      (view) => {
        if (current) setServerQuery({ status: 'READY', view })
      },
      (error: unknown) => {
        if (!current) return
        if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })
        if (error instanceof ApiError && error.status === 404) return setServerQuery({ status: 'READY', view: EMPTY })
        setServerQuery({ status: 'LOAD_FAILED' })
      },
    )
    return () => {
      current = false
    }
  }, [usesMock, attempt, navigate])

  const reload = useCallback(() => {
    setServerQuery({ status: 'LOADING' })
    setAttempt((count) => count + 1)
  }, [])

  /** 서버가 돌려준 목록으로 바꾼다. 떠난 뒤 온 응답은 버린다 */
  const show = useCallback((view: DocumentsView) => {
    if (alive.current) setServerQuery({ status: 'READY', view })
  }, [])

  /** 401 이면 로그인으로 보내고 `true` */
  const leftForLogin = useCallback(
    (error: unknown) => {
      if (!(error instanceof UnauthorizedError)) return false
      navigate('/login', { replace: true })
      return true
    },
    [navigate],
  )

  const upload = useCallback(
    async (file: File) => {
      if (busy.current) return
      if (file.size > MAX_UPLOAD_BYTES) return setAction('TOO_LARGE')

      busy.current = true
      setAction('UPLOADING')
      try {
        if (usesMock) setMockView(await simulateUpload(mockView, file))
        else show(await uploadDocument(file))
        if (alive.current) setAction('IDLE')
      } catch (error: unknown) {
        if (!alive.current || leftForLogin(error)) return
        setAction(
          error instanceof TimeoutError
            ? 'TIMED_OUT'
            : error instanceof ApiError && error.code === 'AGENT_SAFETY_CRISIS_SUPPORT'
              ? 'CRISIS_SUPPORT'
              : error instanceof ApiError && error.code === 'AGENT_SAFETY_REFUSE'
                ? 'SAFETY_BLOCKED'
                : error instanceof ApiError && error.status === 502
                  ? 'UNREADABLE'
                  : error instanceof ApiError && error.status >= 400 && error.status < 500
                    ? 'REJECTED'
                    : 'UPLOAD_FAILED',
        )
      } finally {
        busy.current = false
      }
    },
    [usesMock, mockView, show, leftForLogin],
  )

  /**
   * 확인 · 빼기처럼 목록을 바꾸는 요청. 실패하면 목록은 그대로 두고 알린다.
   *
   * **올리는 중이면 그 표시를 지우지 않는다.** 올리기는 수십 초 걸려서, 그사이 다른 서류를 빼거나 확인할 수
   * 있다. 여기서 "올리는 중"을 지우면 [서류 올리기]가 다시 켜지는데, 올리기가 끝나기 전에 고른 파일은
   * 아무 말 없이 버려진다(`upload` 는 한 번에 하나만 받는다). 올리기가 끝나면 올리기가 상태를 정한다.
   */
  const change = useCallback(
    async (send: () => Promise<DocumentsView>) => {
      setAction((current) => (current === 'UPLOADING' ? current : 'IDLE'))
      try {
        show(await send())
      } catch (error: unknown) {
        if (alive.current && !leftForLogin(error)) {
          setAction((current) => (current === 'UPLOADING' ? current : 'CHANGE_FAILED'))
        }
      }
    },
    [show, leftForLogin],
  )

  const remove = useCallback(
    (id: string) => {
      if (usesMock) {
        // 서류가 바뀌면 지난 점검은 지운다(서버와 같음)
        setMockView((view) => ({ documents: view.documents.filter((document) => document.id !== id), check: null }))
        return
      }
      void change(() => removeDocument(id))
    },
    [usesMock, change],
  )

  /**
   * 사장님이 종류와 값을 확인했다. `values` 는 확인 시트에 보인 칸과 안 보인 칸 전부다 — 서버는 받은
   * 값만 확인한 것으로 저장해서, 빠진 칸은 점검에서 값이 없는 것으로 본다(#159).
   */
  const confirm = useCallback(
    (id: string, kind: string, values: Record<string, string>) => {
      if (!usesMock) {
        void change(() => confirmDocument(id, kind, values))
        return
      }
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
    [usesMock, change],
  )

  /**
   * 정산 서류 점검. 신청인 이름은 이체확인증의 보낸 사람과, 실제 폐업일은 폐업사실증명원과 맞춰 본다.
   * 폐업일을 비우면 서버가 "폐업일 미확인"으로 점검을 끝내지 않는다(#159). 이름·날짜는 점검에만
   * 쓰이고 Case 에는 남지 않는다.
   */
  const runCheck = useCallback(
    async (applicantName: string, closureDate: string | null) => {
      setChecking('RUNNING')
      try {
        if (usesMock) setMockView(await simulateCheck(mockView))
        else show(await checkDocuments(applicantName, closureDate))
        if (alive.current) setChecking('IDLE')
      } catch (error: unknown) {
        if (alive.current && !leftForLogin(error)) setChecking('FAILED')
      }
    },
    [usesMock, mockView, show, leftForLogin],
  )

  const query: DocumentsQuery = usesMock ? { status: 'READY', view: mockView } : serverQuery
  return { query, reload, action, upload, remove, confirm, checking, runCheck }
}
