import { IconCheckmarkCircleFill } from '@karrotmarket/react-monochrome-icon'
import { type ReactNode, useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { toResultSteps, toSubmitOutcome } from '../adapters/results'
import { Button } from '../components/ui/Button'
import { HammerLoader } from '../components/ui/HammerLoader'
import { InfoBox } from '../components/ui/InfoBox'
import { ProcessSteps } from '../components/ui/ProcessSteps'
import { TopBar } from '../components/ui/TopBar'
import { ApiError, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { MOCK_SWITCH_ENABLED, readMockKey } from '../lib/mockSwitch'
import { fetchResultStatus } from '../lib/resultSubmit'
import { noChangeReplan, updatedReplan } from '../mocks/resultFlow'
import type { ReplanView } from '../types/view'

const MOCKS: Record<string, ReplanView> = {
  'no-change': noChangeReplan,
}

/** 서버에 물은 결과 */
type ReplanQuery =
  | { status: 'LOADING' }
  | { status: 'READY'; view: ReplanView }
  /** 이 결과 뒤로 새 판단이 생겼다(409). 지난 결과를 지금 것처럼 보여주지 않는다 */
  | { status: 'SUPERSEDED' }
  | { status: 'LOAD_FAILED' }

/**
 * 주소의 판단 번호. 숫자 글자로만 된 양의 정수가 아니면 `null`.
 *
 * `Number()` 는 `''`·`'1e3'`·`' 12 '` 도 숫자로 바꿔 주므로 글자부터 본다.
 */
function parseHistoryId(search: string): number | null {
  const raw = new URLSearchParams(search).get('history')
  if (raw === null || !/^\d+$/.test(raw)) return null
  const id = Number(raw)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

/**
 * ⑤ 반영 결과.
 *
 * **주소의 판단 번호(`?history=`)로 서버에 다시 묻는다.** 앞 화면이 넘겨준 결과를 그대로 그리면
 * 라우터 state 가 히스토리에 남아, 루프를 더 돈 뒤 뒤로 가기·새로고침을 했을 때 지난 판단이
 * "지금 할 일"이라는 얼굴로 다시 뜬다. 판단 번호로 물으면 서버가 그 뒤로 새 판단이 생겼는지
 * 알려준다(409).
 *
 * 반영된 결과(`UPDATED`·`NO_CHANGE`)만 그린다. 아직 판단 중이거나 다른 결과면 이 화면이 보여줄
 * 것이 아니라 지금 상황(`/case`)으로 보낸다.
 *
 * Mock 은 물을 서버가 없어 앞 화면이 넘겨준 결과나 `?mock=` 으로 그린다.
 */
export function ReplanPage() {
  const { search, state } = useLocation()
  const usesMock = usesMockData(search)

  if (usesMock) {
    const fallback = Object.hasOwn(MOCKS, readMockKey(search))
      ? MOCKS[readMockKey(search)]
      : MOCK_SWITCH_ENABLED
        ? updatedReplan
        : null
    const view = (state as ReplanView | null) ?? fallback
    if (!view) return <Navigate to={{ pathname: '/', search }} replace />
    return <Replanned view={view} search={search} />
  }

  const historyId = parseHistoryId(search)
  // 번호가 없거나 이상하면 물어볼 것이 없다. 요청을 보내지 않고 지금 상황으로 보낸다
  if (historyId === null) return <Navigate to="/case" replace />
  // 번호가 바뀌면 새로 그린다. 앞 번호의 결과가 잠깐이라도 남아 보이지 않게 한다
  return <ServerReplan key={historyId} historyId={historyId} />
}

function ServerReplan({ historyId }: { historyId: number }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState<ReplanQuery>({ status: 'LOADING' })
  /** 다시 불러오기를 누를 때마다 올려 조회를 다시 돌린다 */
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    // 떠났거나 번호가 바뀐 뒤 늦게 온 응답은 버린다
    let current = true

    fetchResultStatus(historyId).then(
      (body) => {
        if (!current) return
        const outcome = toSubmitOutcome(body)
        // 판단 중·되물음·충돌·실패·읽지 못함은 이 화면이 보여줄 것이 아니다
        if (outcome.kind !== 'REPLAN') return navigate('/case', { replace: true })
        setQuery({ status: 'READY', view: outcome.view })
      },
      (error: unknown) => {
        if (!current) return
        if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })
        if (error instanceof ApiError && error.status === 409) return setQuery({ status: 'SUPERSEDED' })
        // 그 번호의 기록이 없다
        if (error instanceof ApiError && error.status === 404) return navigate('/case', { replace: true })
        setQuery({ status: 'LOAD_FAILED' })
      },
    )

    return () => {
      current = false
    }
  }, [historyId, attempt, navigate])

  switch (query.status) {
    case 'LOADING':
      return (
        <ReplanFrame>
          <div className="flex flex-1 items-center justify-center">
            <HammerLoader size={48} label="반영 결과를 불러오는 중" />
          </div>
        </ReplanFrame>
      )

    case 'SUPERSEDED':
      return (
        <ReplanFrame>
          <main className="px-4 pt-2 pb-8">
            <InfoBox
              title="이 결과 뒤로 새 판단이 나왔어요."
              action={{ label: '지금 상황 보기', onClick: () => navigate('/case') }}
            >
              지금 상황에서 최신 할 일을 확인해 주세요.
            </InfoBox>
          </main>
        </ReplanFrame>
      )

    case 'LOAD_FAILED':
      return (
        <ReplanFrame>
          <main className="px-4 pt-2 pb-8">
            <InfoBox
              title="반영 결과를 불러오지 못했어요."
              action={{
                label: '다시 불러오기',
                onClick: () => {
                  setQuery({ status: 'LOADING' })
                  setAttempt((count) => count + 1)
                },
              }}
            >
              연결 상태를 확인하고 다시 불러와 주세요.
            </InfoBox>
          </main>
        </ReplanFrame>
      )

    case 'READY':
      return <Replanned view={query.view} search="" />
  }
}

/**
 * 반영된 결과 (시안 M05c 완료).
 *
 * 처리 중 화면과 같은 단계 줄을 모두 끝난 모양으로 다시 보여준다. 보내고 기다리던 화면에서
 * 이어지는 것으로 읽히게 하려는 것이다.
 *
 * 시안의 "새로 생긴 할 일 3개"는 서버에 없다. 서버는 바뀐 칸과 다음 할 일 하나를 주므로
 * 그 둘을 같은 회색 상자로 보여준다. 막힌 것(Blocker)은 홈과 같은 기준으로 그리지 않는다.
 */
function Replanned({ view, search }: { view: ReplanView; search: string }) {
  const navigate = useNavigate()
  const { changes, nextAction } = view
  const changed = changes.length > 0

  return (
    <ReplanFrame>
      <main className="flex flex-col gap-6 px-4 pt-2 pb-8">
        <div className="flex flex-col items-center pt-2 text-center">
          <IconCheckmarkCircleFill aria-hidden="true" className="size-16 text-fg-brand" />
          <h1 className="mt-4 text-26 font-bold">
            {changed ? '말씀하신 내용을 반영했어요' : '가게 정보에 바뀐 내용은 없어요'}
          </h1>
          <p className="mt-2 text-17 text-fg-neutral-muted">
            {changed ? '다음 할 일을 다시 정했어요.' : '말씀하신 내용을 반영해 다음 할 일을 다시 정했어요.'}
          </p>
        </div>

        <ProcessSteps steps={toResultSteps('DONE')} />

        {changed && (
          <section className="flex flex-col gap-3 rounded-2xl bg-bg-layer-default-pressed px-4.5 py-4">
            <h2 className="text-15 font-bold text-fg-neutral-muted">바뀐 내용</h2>
            <ul className="flex flex-col gap-3">
              {changes.map((change) => (
                <li key={change.key}>
                  <p className="text-15 text-fg-neutral-muted">{change.label}</p>
                  <p className="mt-0.5 text-17">
                    <span className="text-fg-neutral-subtle">{change.previousValue ?? '미확인'}</span>
                    <span aria-hidden="true" className="mx-1.5 text-fg-neutral-subtle">
                      →
                    </span>
                    <span className="sr-only">에서</span>
                    <span className="font-bold">{change.newValue ?? '미확인'}</span>
                    <span className="sr-only">(으)로 바뀜</span>
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {nextAction ? (
          <section className="flex flex-col gap-1 rounded-2xl bg-bg-layer-default-pressed p-4">
            <h2 className="text-15 font-bold text-fg-neutral-muted">다음 할 일</h2>
            <p className="text-18 font-bold">{nextAction.title}</p>
            {nextAction.reason && <p className="text-15 text-fg-neutral-muted">{nextAction.reason}</p>}
          </section>
        ) : (
          <InfoBox title="다음 할 일을 정하려면 확인이 더 필요해요.">
            지금 상황에서 어떤 항목이 비어 있는지 확인해 주세요.
          </InfoBox>
        )}

        <Button onClick={() => navigate({ pathname: '/case', search })}>홈으로</Button>
      </main>
    </ReplanFrame>
  )
}

/** 탭 없는 화면의 틀. 시안처럼 머리에 제목을 두지 않고 화면 안의 큰 제목이 맡는다 */
function ReplanFrame({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar />
      {children}
    </div>
  )
}
