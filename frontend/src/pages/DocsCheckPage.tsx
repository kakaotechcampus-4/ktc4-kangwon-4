import {
  IconCheckmarkCircleFill,
  IconExclamationmarkCircleFill,
  IconSparkle2Fill,
} from '@karrotmarket/react-monochrome-icon'
import { type ReactNode, useId, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { BottomSheet } from '../components/ui/BottomSheet'
import { Button } from '../components/ui/Button'
import { HammerLoader } from '../components/ui/HammerLoader'
import { InfoBox } from '../components/ui/InfoBox'
import { ProcessSteps, type StepStatus } from '../components/ui/ProcessSteps'
import { TopBar } from '../components/ui/TopBar'
import { useDocuments } from '../hooks/useDocuments'
import { useEntersForward } from '../lib/viewTransition'
import type { DocumentCheckView } from '../types/view'

/** 서버 점검 단계 상태 → 단계 줄 모양. 확인 필요·멈춤은 끝난 것이 아니라 "기다림"으로 둔다 */
const STEP_STATUS: Record<DocumentCheckView['steps'][number]['status'], StepStatus> = {
  WAITING: 'wait',
  RUNNING: 'run',
  DONE: 'done',
  NEEDS_CONFIRMATION: 'wait',
  ERROR: 'wait',
}

/**
 * AI 서류 점검 (시안 M06). 서류함의 정산 서류를 서버 점검 규칙으로 맞춰 본다.
 *
 * 점검은 서버(#159 `POST /cases/documents/check`)가 한다. 화면은 결과 상태(통과·확인할 것 있음·
 * 멈춤)와 서버가 쓴 단계 이름·문제 문구를 그대로 보여준다.
 *
 * 점검 직전에 가게 이름·신청인 이름과 실제 폐업일을 묻는다. 서비스에 사장님 이름 칸이 없고, 예상 달만
 * 정한 Case 에는 폐업일이 없어서다(#159). 시안에 없는 장면이라 아래 시트로 둔다(11/03 시우님).
 *
 * 시안 아래쪽 "글자 인식(OCR)과 기관 연동은 쓰지 않아요"는 뺐다. 서버 문서 Tool 은 OCR 을 쓴다(#159).
 */
export function DocsCheckPage() {
  const navigate = useNavigate()
  // 점검 결과의 줄들이 차례로 올라온다. 뒤로 돌아와 이미 결과가 있으면 올리지 않는다
  const rise = useEntersForward() ? 'rise-children' : ''
  // ?mock= 을 다음 화면에도 이어 준다. 빠지면 Mock 으로 보던 흐름이 실서버 화면으로 바뀐다
  const { search } = useLocation()
  const { query, reload, checking, runCheck } = useDocuments()
  const [asking, setAsking] = useState(false)

  if (query.status === 'LOADING') {
    return (
      <CheckFrame>
        <div className="flex flex-1 items-center justify-center">
          <HammerLoader size={48} label="서류함을 불러오는 중" />
        </div>
      </CheckFrame>
    )
  }

  if (query.status === 'LOAD_FAILED') {
    return (
      <CheckFrame>
        <main className="flex flex-col gap-6 px-4 pt-2 pb-8">
          <InfoBox title="서류함을 불러오지 못했어요." action={{ label: '다시 불러오기', onClick: reload }}>
            연결 상태를 확인하고 다시 불러와 주세요.
          </InfoBox>
        </main>
      </CheckFrame>
    )
  }

  // 점검을 보내지 못했으면 지난 결과는 그대로라, 어느 화면에서든 위에 알린다
  const sendNotice = checking === 'FAILED' && (
    <InfoBox tone="critical" title="점검을 보내지 못했어요.">
      연결이 불안정했을 수 있어요. 다시 점검해 주세요.
    </InfoBox>
  )

  const { documents, check } = query.view

  if (checking === 'RUNNING') {
    return (
      <CheckFrame>
        <Header icon={<HammerLoader size={64} label="서류를 점검하는 중" />} title="리본이 서류를 보고 있어요" sub="사장님이 하실 일은 없어요." />
        <div className="px-4 pb-8">
          <Button disabled>점검 중이에요</Button>
        </div>
      </CheckFrame>
    )
  }

  const startCheck = () => setAsking(true)
  const askSheet = (
    <ApplicantSheet
      open={asking}
      initialStoreName={query.view.storeName}
      onClose={() => setAsking(false)}
      onSubmit={(storeName, name, date) => {
        setAsking(false)
        void runCheck(storeName, name, date)
      }}
    />
  )

  // 점검할 서류가 없으면 점검을 열지 않는다. 빈 서류함으로 점검하면 모든 서류가 빠졌다고만 나온다
  if (documents.length === 0) {
    return (
      <CheckFrame>
        <main className="flex flex-col gap-6 px-4 pt-2 pb-8">
          <InfoBox title="아직 점검할 서류가 없어요." action={{ label: '서류함으로 가기', onClick: () => navigate({ pathname: '/docs', search }) }}>
            서류함에 정산 서류를 올리면 여기서 점검할 수 있어요.
          </InfoBox>
        </main>
      </CheckFrame>
    )
  }

  if (check === null) {
    return (
      <CheckFrame>
        <Header
          icon={<span className="grid size-16 place-items-center rounded-full bg-bg-brand-weak text-fg-brand"><IconSparkle2Fill size={32} /></span>}
          title="정산 서류를 점검할게요"
          sub={`서류함에 있는 서류 ${documents.length}개를 그대로 써요.`}
        />
        {sendNotice && <div className="px-4">{sendNotice}</div>}
        <div className="mt-auto px-4 pb-8">
          <Button onClick={startCheck}>점검 시작하기</Button>
        </div>
        {askSheet}
      </CheckFrame>
    )
  }

  const steps = check.steps.map((step) => ({ label: step.name, status: STEP_STATUS[step.status] }))

  switch (check.status) {
    case 'COMPLETE':
      return (
        <CheckFrame>
          <Header
            icon={<IconCheckmarkCircleFill size={64} className="text-fg-brand motion-safe:animate-pop" aria-hidden="true" />}
            title="서류 점검을 마쳤어요"
            sub="남은 확인 사항이 없어요."
          />
          <main className={`flex flex-col gap-6 px-4 pb-8 ${rise}`}>
            {sendNotice}
            <ProcessSteps steps={steps} />
            <Button onClick={() => navigate({ pathname: '/docs/done', search }, { viewTransition: true })}>결과 보기</Button>
          </main>
        </CheckFrame>
      )

    case 'ISSUES':
      return (
        <CheckFrame>
          <Header
            icon={<IconExclamationmarkCircleFill size={64} className="text-fg-critical" aria-hidden="true" />}
            title={`확인하실 일이 ${check.issues.length}개 있어요`}
            sub="서류를 더하거나 고친 뒤 다시 점검해 주세요."
          />
          <main className={`flex flex-col gap-6 px-4 pb-8 ${rise}`}>
            {sendNotice}
            <ProcessSteps steps={steps} />
            <InfoBox tone="critical" title="점검에서 찾은 것">
              <ul className="flex flex-col gap-1">
                {check.issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            </InfoBox>
            <div className="flex flex-col gap-2">
              <Button onClick={() => navigate({ pathname: '/docs', search })}>서류함으로 가기</Button>
              <Button variant="outline" onClick={startCheck}>
                다시 점검하기
              </Button>
            </div>
          </main>
          {askSheet}
        </CheckFrame>
      )

    case 'ERROR':
      return (
        <CheckFrame>
          <Header
            icon={<IconExclamationmarkCircleFill size={64} className="text-fg-critical" aria-hidden="true" />}
            title="점검이 중간에 멈췄어요"
            sub="서류함은 그대로예요. 다시 점검해 주세요."
          />
          <main className={`flex flex-col gap-6 px-4 pb-8 ${rise}`}>
            {sendNotice}
            <ProcessSteps steps={steps} />
            <Button onClick={startCheck}>다시 점검하기</Button>
          </main>
          {askSheet}
        </CheckFrame>
      )
  }
}

/** 위쪽 상태 그림 · 제목 · 한 줄 */
function Header({ icon, title, sub }: { icon: ReactNode; title: string; sub: string }) {
  return (
    <div className="flex flex-col items-center gap-4 px-4 pt-6 pb-6 text-center">
      {icon}
      <div>
        <h1 className="text-24 font-bold">{title}</h1>
        <p className="mt-2 text-17 text-fg-neutral-muted">{sub}</p>
      </div>
    </div>
  )
}

/**
 * 점검 직전에 가게 이름·신청인 이름과 실제 폐업일을 묻는 시트.
 *
 * 이름은 이체확인증의 보낸 사람과, 폐업일은 폐업사실증명원과 맞춰 본다(#159). 이름은 꼭 받고
 * (서버가 1~50자만 받음), 폐업일은 모르면 비워도 된다 — 비우면 서버가 "폐업일 미확인"으로 알려 준다.
 */
export function ApplicantSheet({
  open,
  initialStoreName,
  onClose,
  onSubmit,
}: {
  open: boolean
  initialStoreName: string | null
  onClose: () => void
  onSubmit: (storeName: string, name: string, closureDate: string | null) => void
}) {
  const [storeName, setStoreName] = useState(initialStoreName ?? '')
  const [name, setName] = useState('')
  const [date, setDate] = useState('')
  const storeNameId = useId()
  const nameId = useId()
  const dateId = useId()
  const trimmed = name.trim()
  const trimmedStore = storeName.trim()
  const valid = trimmedStore.length > 0 && [...trimmedStore].length <= 50 && trimmed.length > 0 && [...trimmed].length <= 50

  return (
    <BottomSheet open={open} onClose={onClose} title="점검 전에 알려 주세요" description="서류에 적힌 것과 맞춰 볼게요.">
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (!valid) return
          onSubmit(trimmedStore, trimmed, date === '' ? null : date)
        }}
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor={storeNameId} className="text-15 font-medium text-fg-neutral-muted">
            가게 이름
          </label>
          <input
            id={storeNameId}
            value={storeName}
            maxLength={50}
            autoComplete="organization"
            onChange={(event) => setStoreName(event.target.value)}
            className="h-13 rounded-xl px-3 text-17 ring-1 ring-stroke-neutral-weak ring-inset"
          />
          <p className="text-14 text-fg-neutral-muted">상호를 확인하고 가게 정보에 저장해요. 신청인 이름과 구분해 주세요.</p>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={nameId} className="text-15 font-medium text-fg-neutral-muted">
            신청인 이름
          </label>
          <input
            id={nameId}
            value={name}
            maxLength={50}
            autoComplete="name"
            onChange={(event) => setName(event.target.value)}
            className="h-13 rounded-xl px-3 text-17 ring-1 ring-stroke-neutral-weak ring-inset"
          />
          <p className="text-14 text-fg-neutral-muted">이체확인증의 보낸 사람과 같아야 해요.</p>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={dateId} className="text-15 font-medium text-fg-neutral-muted">
            실제 폐업일 (선택)
          </label>
          <input
            id={dateId}
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
            className="h-13 rounded-xl px-3 text-17 ring-1 ring-stroke-neutral-weak ring-inset"
          />
          <p className="text-14 text-fg-neutral-muted">폐업사실증명원에 적힌 날짜예요. 모르면 비워 두세요.</p>
        </div>
        <Button type="submit" disabled={!valid}>
          점검하기
        </Button>
      </form>
    </BottomSheet>
  )
}

/** 탭 없는 화면의 틀. 뒤로 버튼과 화면 이름을 둔다 */
function CheckFrame({ children }: { children: ReactNode }) {
  return (
    <div className="screen-frame mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar title="AI 서류 점검" />
      {children}
    </div>
  )
}
