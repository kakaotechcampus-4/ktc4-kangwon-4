import { IconCheckmarkCircleFill } from '@karrotmarket/react-monochrome-icon'
import { type ReactNode, useEffect, useId, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate, useParams } from 'react-router'

import { BottomSheet } from '../components/ui/BottomSheet'
import { Button } from '../components/ui/Button'
import { HammerLoader } from '../components/ui/HammerLoader'
import { InfoBox } from '../components/ui/InfoBox'
import { TopBar } from '../components/ui/TopBar'
import { useCase } from '../hooks/useCase'
import { useRoadmap } from '../hooks/useRoadmap'
import { ApiError, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { embedPostcode, loadPostcode, toRoadAddress } from '../lib/postcode'
import { saveChecklist, saveClosureReport, saveDepositReturn, saveSupportApproval } from '../lib/roadmapActions'
import { taskFlowOf } from '../lib/taskFlows'
import type { ClosureReason, DepositReturnResult } from '../types/api'
import type { ClosureReportView, CurrentCaseView, RoadmapTaskView } from '../types/view'

/** 저장 상태. 저장이 끝나기 전에는 화면의 체크·결과를 바꾸지 않는다(FE 규칙 2) */
type SaveState = 'IDLE' | 'SAVING' | 'FAILED' | 'REJECTED'

/**
 * 로드맵 할 일 하나 (시안 M09 할 일 흐름). 할 일마다 어떤 장면을 열지는 `taskFlowOf` 가 고른다.
 *
 * 시안의 세부 체크 줄("조건 네 줄", "퇴직 후 14일 안에")은 넣지 않는다. 서버가 줄 목록을 주지 않고,
 * FE가 들고 있으면 무엇을 확인할지를 FE가 정하게 된다(FE 규칙 1·7, 승준님 #149). 할 일 하나를
 * 통째로 체크하고, 검수한 설명이 있으면 그것을 보여준다.
 */
export function TaskFlowPage() {
  const { taskId = '' } = useParams()
  const { search } = useLocation()
  const { query: roadmap, reload } = useRoadmap()

  // 할 일 상태는 로드맵이 정한다. 로드맵을 받아야 어떤 장면을 열지 안다
  if (roadmap.status === 'EMPTY') return <Navigate to={{ pathname: '/cases/new', search }} replace />

  if (roadmap.status === 'LOADING') {
    return (
      <TaskFrame>
        <div className="flex justify-center pt-16">
          <HammerLoader size={48} label="할 일을 불러오는 중" />
        </div>
      </TaskFrame>
    )
  }

  if (roadmap.status === 'LOAD_FAILED') {
    return (
      <TaskFrame>
        <InfoBox title="할 일을 불러오지 못했어요." action={{ label: '다시 불러오기', onClick: reload }}>
          연결 상태를 확인하고 다시 불러와 주세요.
        </InfoBox>
      </TaskFrame>
    )
  }

  const task = roadmap.view.stages.flatMap((stage) => stage.tasks).find((item) => item.id === taskId)
  // 없는 할 일이거나, 이 가게에 해당하지 않는 할 일이다. 순서 화면에서 다시 고르게 한다
  if (!task || task.status === 'NOT_APPLICABLE') return <Navigate to={{ pathname: '/roadmap', search }} replace />

  switch (taskFlowOf(task)) {
    case 'DOCUMENT_CHECK':
      return <Navigate to={{ pathname: '/docs/check', search }} replace />
    case 'CHECK':
      return <CheckFlow task={task} />
    case 'ATTACH':
      return <CheckFlow task={task} attach />
    case 'SUPPORT_RESULT':
      return <SupportResultFlow task={task} />
    case 'REPORT_RESULT':
      return <ReportResultFlow task={task} />
    case 'CLOSURE_REPORT':
      return <WithSavedCase task={task}>{(view) => <ClosureReportFlow task={task} initial={view?.closureReport ?? null} />}</WithSavedCase>
    case 'DEPOSIT':
      return <WithSavedCase task={task}>{(view) => <DepositFlow task={task} initial={view?.depositReturn ?? null} />}</WithSavedCase>
    case 'INFO':
      return <InfoFlow task={task} />
  }
}

/**
 * 저장해 둔 값(`GET /cases`)을 받은 뒤에 장면을 연다. 폐업 신고·보증금처럼 다시 열 수 있는 장면이
 * 쓴다 — 칸의 처음 값은 장면이 처음 그려질 때 한 번만 정해져서, 받기 전에 열면 빈 칸으로 굳는다.
 *
 * 받지 못했으면(불러오기 실패·Case 없음) 빈 칸에서 연다. 다시 저장하면 덮어쓰니, 저장된 값을 몰라도
 * 사장님이 할 일은 막히지 않는다.
 */
function WithSavedCase({ task, children }: { task: RoadmapTaskView; children: (view: CurrentCaseView | null) => ReactNode }) {
  const { query } = useCase()

  if (query.status === 'LOADING') {
    return (
      <TaskFrame>
        <TaskHeader task={task} />
        <p role="status" className="sr-only">
          저장해 둔 내용을 불러오고 있어요
        </p>
      </TaskFrame>
    )
  }
  return children(query.status === 'READY' ? query.view : null)
}

/**
 * 입력을 고쳤을 때의 저장 상태. 거절(`REJECTED`)만 풀고 나머지는 그대로 둔다.
 *
 * 거절은 "이 값은 받지 않는다"는 뜻이라, 값을 고치면 다시 보내 볼 수 있어야 한다. 입력이 없는 체크 장면은
 * 고칠 것이 없어 거절을 풀지 않는다.
 */
function retryAfterEdit(current: SaveState): SaveState {
  return current === 'REJECTED' ? 'IDLE' : current
}

/** 저장 실패를 화면 상태로. 401 은 로그인으로 보낸다 */
function useSaveErrors() {
  const navigate = useNavigate()
  return (error: unknown): SaveState | null => {
    if (error instanceof UnauthorizedError) {
      navigate('/login', { replace: true })
      return null
    }
    // 이 가게에서 받지 않는 항목이거나 Case 가 없다. 다시 눌러도 같다
    if (error instanceof ApiError && error.status >= 400 && error.status < 500) return 'REJECTED'
    return 'FAILED'
  }
}

/**
 * 체크 장면. 서류가 필요한 할 일(`attach`)은 서류함에 올리는 길을 먼저 둔다 — 올린 서류가 정산
 * 점검에 쓰인다. 체크는 사장님이 "했다"고 알리는 것이고, 할 일 상태는 로드맵이 다시 계산한다.
 *
 * 서버가 "확인 필요"(`NEEDS_CONFIRMATION`)로 준 할 일은 [다 했어요]를 처음부터 끈다. 서버가 체크를
 * 422 로 받지 않는다(#181) — 예를 들어 철거비 심사 결과를 모르면 정산 항목이 그렇다. 무엇이 확인돼야
 * 하는지는 서버가 주지 않아 지어내지 않는다. 서버가 준 상태로 가르는 것이지 FE 판단이 아니다(규칙 1).
 * 막는 것은 [다 했어요]뿐이다. 체크해 둔 것을 푸는 [완료 취소하기]는 따로 두어 막지 않는다(서버도 풀기는 늘 받는다).
 */
export function CheckFlow({ task, attach = false }: { task: RoadmapTaskView; attach?: boolean }) {
  const navigate = useNavigate()
  const { search } = useLocation()
  const usesMock = usesMockData(search)
  const toSaveState = useSaveErrors()
  // 처음은 서버가 준 상태다. 저장하면 저장된 값으로 바꾼다
  const [checked, setChecked] = useState(task.status === 'COMPLETED')
  const [save, setSave] = useState<SaveState>('IDLE')
  const waiting = task.status === 'NEEDS_CONFIRMATION'

  async function toggle() {
    const next = !checked
    setSave('SAVING')
    try {
      // Mock 은 서버가 없다. 저장된 것으로 둔다
      setChecked(usesMock ? next : await saveChecklist(task.id, next))
      setSave('IDLE')
    } catch (error: unknown) {
      const state = toSaveState(error)
      if (state) setSave(state)
    }
  }

  return (
    <TaskFrame>
      <TaskHeader task={task} />
      {attach && (
        <InfoBox
          title="서류를 서류함에 올려 주세요."
          action={{ label: '서류함에 올리기', onClick: () => navigate({ pathname: '/docs', search }) }}
        >
          올린 서류는 정산 서류 점검에 쓰여요.
        </InfoBox>
      )}
      {checked && save !== 'SAVING' && (
        <p className="flex items-center gap-2 text-17 font-bold">
          <IconCheckmarkCircleFill size={22} className="text-fg-brand motion-safe:animate-pop" aria-hidden="true" />
          마치셨다고 기록했어요
        </p>
      )}
      {waiting && (
        <InfoBox title="아직 기록할 수 없는 할 일이에요.">필요한 내용이 확인되면 기록할 수 있어요.</InfoBox>
      )}
      <SaveNotice save={save} />
      <div className="mt-auto flex flex-col gap-2">
        {checked ? (
          <Button variant="outline" disabled={save === 'SAVING' || save === 'REJECTED'} onClick={toggle}>
            완료 취소하기
          </Button>
        ) : (
          <Button disabled={waiting || save === 'SAVING' || save === 'REJECTED'} onClick={toggle}>
            다 했어요
          </Button>
        )}
      </div>
    </TaskFrame>
  )
}

const SUPPORT_OPTIONS: { value: boolean | null; label: string }[] = [
  { value: true, label: '승인됐어요' },
  { value: false, label: '안 됐어요' },
  { value: null, label: '아직 몰라요' },
]

/**
 * 철거비 1차 적격심사 결과 (시안 "승인 결과"). 사장님이 소상공인24에서 본 결과를 남긴다.
 *
 * 시안은 고른 보기마다 "정산 단계는 건너뛰어요" 같은 안내를 다는데 넣지 않는다. 다음에 무엇을 할지는
 * 로드맵 판단이 정한다(FE 규칙 1). 처음에는 아무것도 골라 두지 않는다 — 서버가 지금 값을 돌려주지 않아,
 * 짐작해 골라 두면 사장님이 확인하지 않고 넘긴다.
 */
export function SupportResultFlow({ task }: { task: RoadmapTaskView }) {
  const { search } = useLocation()
  const usesMock = usesMockData(search)
  const toSaveState = useSaveErrors()
  const [picked, setPicked] = useState<number | null>(null)
  const [saved, setSaved] = useState<boolean | null | undefined>(undefined)
  const [save, setSave] = useState<SaveState>('IDLE')

  async function submit() {
    if (picked === null) return
    const value = SUPPORT_OPTIONS[picked].value
    setSave('SAVING')
    try {
      setSaved(usesMock ? value : await saveSupportApproval(value))
      setSave('IDLE')
    } catch (error: unknown) {
      const state = toSaveState(error)
      if (state) setSave(state)
    }
  }

  const savedLabel = saved === undefined ? null : SUPPORT_OPTIONS.find((option) => option.value === saved)?.label

  return (
    <TaskFrame>
      <TaskHeader task={task} sub="소상공인24에서 확인한 결과를 알려 주세요." />
      <div role="radiogroup" aria-label="1차 적격심사 결과" className="flex flex-col gap-2">
        {SUPPORT_OPTIONS.map((option, index) => (
          <button
            key={option.label}
            type="button"
            role="radio"
            aria-checked={picked === index}
            onClick={() => {
              setPicked(index)
              // 다른 답을 고르면 거절을 푼다. 고른 값은 받을 수 있는데 버튼이 꺼진 채로 남지 않게
              setSave(retryAfterEdit)
            }}
            className={`flex min-h-14 cursor-pointer items-center rounded-14 px-4 text-17 font-medium ring-inset ${
              picked === index ? 'bg-bg-brand-weak ring-2 ring-stroke-brand-solid' : 'ring-1 ring-stroke-neutral-weak'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
      {savedLabel && save !== 'SAVING' && (
        <p className="flex items-center gap-2 text-17 font-bold">
          {/* "아직 몰라요"에는 완료 체크를 달지 않는다. 할 일은 확인 필요로 남는다(#237, ui-guidelines "모름은 모름으로") */}
          {saved !== null && (
            <IconCheckmarkCircleFill size={22} className="text-fg-brand motion-safe:animate-pop" aria-hidden="true" />
          )}
          &ldquo;{savedLabel}&rdquo;로 기록했어요
        </p>
      )}
      <SaveNotice save={save} />
      <div className="mt-auto">
        <Button disabled={picked === null || save === 'SAVING' || save === 'REJECTED'} onClick={submit}>
          기록하기
        </Button>
      </div>
    </TaskFrame>
  )
}

/**
 * 공식 절차. 사장님이 기관·임대인과 한 일을 결과 입력으로 알려 주면 판단이 다음 순서를 정한다.
 * 체크로 완료하지 않는다 — 절차가 끝났는지는 판단이 정하는 것이라서다.
 */
function ReportResultFlow({ task }: { task: RoadmapTaskView }) {
  const navigate = useNavigate()
  const { search } = useLocation()
  return (
    <TaskFrame>
      <TaskHeader task={task} />
      <InfoBox>이 일은 하신 결과를 알려 주시면 리본이 확인해 다음 순서를 정해요.</InfoBox>
      <div className="mt-auto">
        <Button onClick={() => navigate({ pathname: '/results', search }, { viewTransition: true })}>결과 알려주기</Button>
      </div>
    </TaskFrame>
  )
}

const DEPOSIT_OPTIONS: { value: DepositReturnResult; label: string }[] = [
  { value: 'FULL', label: '다 받았어요' },
  { value: 'PARTIAL', label: '일부 빼고 받았어요' },
  { value: 'NONE', label: '아직 못 받았어요' },
]

/**
 * 보증금 정산 기록 (시안 가게 반환 "보증금은 돌려받으셨나요?").
 *
 * [기록하기] 한 번으로 두 가지를 남긴다(11/03 시우님) — 보증금 결과(#168 `PUT /cases/deposit-return`)와
 * 로드맵의 "보증금 정산 기록" 체크(#149). 시안에서도 기록하기 한 번이 그 할 일을 끝낸다. 결과를 먼저
 * 저장하고, 성공한 뒤에 체크를 보낸다. 체크만 실패하면 결과는 남아 있으니 체크만 다시 보내게 한다.
 *
 * 시안은 "아직 못 받았어요"에 법률 상담 안내를 다는데 넣지 않는다. 무엇을 해야 할지는 판단이 정한다
 * (FE 규칙 1). 리본은 기록만 하고 판단하지 않는다는 시안 문구는 그대로 둔다.
 *
 * 기록해 둔 결과(`initial`)가 있으면 그것을 골라 둔 채 "~로 기록했어요"로 연다. 서버에 저장된 값이라
 * 미리 칠하는 것이 아니다(FE 규칙 2).
 */
export function DepositFlow({ task, initial = null }: { task: RoadmapTaskView; initial?: DepositReturnResult | null }) {
  const { search } = useLocation()
  const usesMock = usesMockData(search)
  const toSaveState = useSaveErrors()
  const [picked, setPicked] = useState<DepositReturnResult | null>(initial)
  const [saved, setSaved] = useState<DepositReturnResult | null>(initial)
  /** 결과는 저장했는데 체크를 못 했다. 체크만 다시 보낸다 */
  const [checkPending, setCheckPending] = useState(false)
  const [save, setSave] = useState<SaveState>('IDLE')

  async function markChecklist() {
    if (!usesMock) await saveChecklist(task.id, true)
    setCheckPending(false)
  }

  async function submit() {
    if (picked === null) return
    setSave('SAVING')
    try {
      setSaved(usesMock ? picked : await saveDepositReturn(picked))
    } catch (error: unknown) {
      const state = toSaveState(error)
      if (state) setSave(state)
      return
    }
    try {
      await markChecklist()
      setSave('IDLE')
    } catch (error: unknown) {
      setCheckPending(true)
      const state = toSaveState(error)
      if (state) setSave(state)
    }
  }

  async function retryChecklist() {
    setSave('SAVING')
    try {
      await markChecklist()
      setSave('IDLE')
    } catch (error: unknown) {
      const state = toSaveState(error)
      if (state) setSave(state)
    }
  }

  const savedLabel = DEPOSIT_OPTIONS.find((option) => option.value === saved)?.label

  return (
    <TaskFrame>
      <TaskHeader task={task} sub="리본은 기록만 하고 판단하지 않아요." />
      <div role="radiogroup" aria-label="보증금 돌려받았는지" className="flex flex-col gap-2">
        {DEPOSIT_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={picked === option.value}
            onClick={() => {
              setPicked(option.value)
              // 보증금 결과를 다시 고르면 거절을 푼다. 체크만 남은 경우(`checkPending`)는 고른 값과 상관없어 그대로 둔다
              if (!checkPending) setSave(retryAfterEdit)
            }}
            className={`flex min-h-14 cursor-pointer items-center rounded-14 px-4 text-17 font-medium ring-inset ${
              picked === option.value ? 'bg-bg-brand-weak ring-2 ring-stroke-brand-solid' : 'ring-1 ring-stroke-neutral-weak'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      {savedLabel && save !== 'SAVING' && !checkPending && (
        <p className="flex items-center gap-2 text-17 font-bold">
          <IconCheckmarkCircleFill size={22} className="text-fg-brand motion-safe:animate-pop" aria-hidden="true" />
          &ldquo;{savedLabel}&rdquo;로 기록했어요
        </p>
      )}
      {checkPending ? (
        <InfoBox
          tone="critical"
          title="보증금 결과는 저장했는데 할 일 체크는 못 했어요."
          action={{
            label: '체크만 다시 보내기',
            onClick: retryChecklist,
            // 서버가 받지 않는 항목이면 다시 보내도 같다
            disabled: save === 'SAVING' || save === 'REJECTED',
          }}
        >
          다시 보내면 폐업 전체 순서에 마친 것으로 남아요.
        </InfoBox>
      ) : (
        <SaveNotice save={save} />
      )}

      <div className="mt-auto">
        <Button disabled={picked === null || save === 'SAVING' || save === 'REJECTED' || checkPending} onClick={submit}>
          기록하기
        </Button>
      </div>
    </TaskFrame>
  )
}

const CLOSURE_REASONS: { value: ClosureReason; label: string }[] = [
  { value: 'BUSINESS_SLUMP', label: '사업 부진' },
  { value: 'PERSONAL', label: '개인 사정' },
  { value: 'OTHER', label: '기타' },
]

/**
 * 통합 폐업 신고 (시안 ④ "폐업 정보 확인" · "가게 주소 확인"). 신고에 적을 실제 폐업일·사유·주소를
 * 한 번에 저장한다(#168 `PUT /cases/closure-report`).
 *
 * 시안은 두 장으로 나눴지만 서버가 한 번에 받아서 한 장에 둔다 — 두 장이면 첫 장만 채우고 떠났을 때
 * 저장할 길이 없다. 시안의 날짜 칩(10월 31일 등)은 예시라 날짜 고르기로 받는다.
 *
 * 폐업일은 가입 때 정한 시기(예상 달)와 다른, 신고할 실제 날짜다. 처음에는 비워 두고 고르게 한다.
 * 폐업일·사유·도로명 주소는 꼭 받고, 상세 주소는 비워도 된다(단독 건물 등).
 *
 * 저장한 뒤에는 접수증을 서류함에 올리고 결과를 알려 달라고 안내한다. 통합 폐업 신고는 공식
 * 절차라 끝났는지는 판단이 정한다.
 *
 * 저장해 둔 값(`initial`, `GET /cases` 의 #168 칸)이 있으면 칸을 채우고 저장한 뒤 모양으로 연다.
 * 고쳐서 다시 저장하면 덮어쓴다.
 */
export function ClosureReportFlow({ task, initial = null }: { task: RoadmapTaskView; initial?: ClosureReportView | null }) {
  const navigate = useNavigate()
  const { search } = useLocation()
  const usesMock = usesMockData(search)
  const toSaveState = useSaveErrors()
  const [closureDate, setClosureDate] = useState(initial?.closureDate ?? '')
  const [reason, setReason] = useState<ClosureReason | null>(initial?.closureReason ?? null)
  const [roadAddress, setRoadAddress] = useState(initial?.roadAddress ?? '')
  const [detail, setDetail] = useState(initial?.addressDetail ?? '')
  const [finding, setFinding] = useState(false)
  const [save, setSave] = useState<SaveState>('IDLE')
  const [saved, setSaved] = useState(initial !== null)
  const dateId = useId()
  const detailId = useId()

  /*
    칸을 고치면 "저장했어요"를 내린다. 저장한 뒤 날짜나 주소를 고치고 [결과 알려주기]로 떠나면, 사장님은
    고친 내용까지 저장된 줄 안다. 서버에는 고치기 전 값이 남아 있다.
    서버가 거절한 것(`REJECTED`)도 푼다 — 고친 값은 받을 수 있는데 [저장하기]가 꺼진 채로 남으면 화면을
    나갔다 와야 한다
  */
  const edited =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      setSaved(false)
      setSave(retryAfterEdit)
      set(value)
    }

  const ready = closureDate !== '' && reason !== null && roadAddress !== ''

  async function submit() {
    if (!ready || reason === null) return
    const body = {
      closure_date: closureDate,
      closure_reason: reason,
      road_address: roadAddress,
      address_detail: detail.trim() === '' ? null : detail.trim(),
    }
    setSave('SAVING')
    try {
      if (!usesMock) await saveClosureReport(body)
      setSaved(true)
      setSave('IDLE')
    } catch (error: unknown) {
      const state = toSaveState(error)
      if (state) setSave(state)
    }
  }

  return (
    <TaskFrame>
      <TaskHeader task={task} sub="사업자등록증에 적힌 것과 같게 적어 주세요." />

      <div className="flex flex-col gap-1.5">
        <label htmlFor={dateId} className="text-15 font-medium text-fg-neutral-muted">
          폐업일
        </label>
        <input
          id={dateId}
          type="date"
          value={closureDate}
          onChange={(event) => edited(setClosureDate)(event.target.value)}
          className="h-13 rounded-xl px-3 text-17 ring-1 ring-stroke-neutral-weak ring-inset"
        />
      </div>

      <div role="radiogroup" aria-label="폐업 사유" className="flex flex-col gap-1.5">
        <span aria-hidden="true" className="text-15 font-medium text-fg-neutral-muted">
          폐업 사유
        </span>
        <div className="flex gap-2">
          {CLOSURE_REASONS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={reason === option.value}
              onClick={() => edited(setReason)(option.value)}
              className={`h-12 flex-1 cursor-pointer rounded-full text-16 font-medium ring-inset ${
                reason === option.value ? 'bg-bg-brand-weak ring-2 ring-stroke-brand-solid' : 'ring-1 ring-stroke-neutral-weak'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-15 font-medium text-fg-neutral-muted">가게 주소</span>
        {roadAddress !== '' && <p className="text-17 font-medium">{roadAddress}</p>}
        <Button variant="outline" onClick={() => setFinding(true)}>
          {roadAddress === '' ? '주소 찾기' : '주소 다시 찾기'}
        </Button>
        <label htmlFor={detailId} className="mt-2 text-15 font-medium text-fg-neutral-muted">
          상세 주소 (선택)
        </label>
        <input
          id={detailId}
          value={detail}
          maxLength={100}
          placeholder="예: 1층"
          onChange={(event) => edited(setDetail)(event.target.value)}
          className="h-13 rounded-xl px-3 text-17 ring-1 ring-stroke-neutral-weak ring-inset"
        />
      </div>

      {saved && save !== 'SAVING' && (
        <>
          <p className="flex items-center gap-2 text-17 font-bold">
            <IconCheckmarkCircleFill size={22} className="text-fg-brand motion-safe:animate-pop" aria-hidden="true" />
            신고 정보를 저장했어요
          </p>
          <InfoBox
            title="신고를 마치면 접수증을 서류함에 올려 주세요."
            action={{ label: '서류함에 올리기', onClick: () => navigate({ pathname: '/docs', search }) }}
          >
            신고한 결과는 결과 알려주기로 알려 주시면 리본이 다음 순서를 정해요.
          </InfoBox>
        </>
      )}
      <SaveNotice save={save} />

      <div className="mt-auto flex flex-col gap-2">
        {saved && (
          <Button variant="outline" onClick={() => navigate({ pathname: '/results', search }, { viewTransition: true })}>
            결과 알려주기
          </Button>
        )}
        <Button disabled={!ready || save === 'SAVING' || save === 'REJECTED'} onClick={submit}>
          {saved ? '다시 저장하기' : '저장하기'}
        </Button>
      </div>

      <AddressSheet
        open={finding}
        onClose={() => setFinding(false)}
        onSelect={(address) => {
          setFinding(false)
          edited(setRoadAddress)(address)
        }}
      />
    </TaskFrame>
  )
}

/**
 * 주소 찾기 시트. 다음 우편번호 찾기 창을 시트 안에 띄운다.
 *
 * 새 창(팝업)으로 열지 않는다. 휴대폰 브라우저는 팝업을 막거나 새 탭으로 열어, 고른 뒤 돌아오는 길을
 * 잃기 쉽다. 스크립트를 받지 못하면 다시 받을 수 있게 안내한다.
 */
export function AddressSheet({
  open,
  onClose,
  onSelect,
}: {
  open: boolean
  onClose: () => void
  onSelect: (roadAddress: string) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  // 고른 뒤 부를 함수는 늘 최신 것을 쓴다. 효과의 의존으로 두면 바깥 화면이 다시 그려질 때마다 찾기 창을
  // 새로 띄워, 사장님이 적던 검색어가 지워진다
  const latestSelect = useRef(onSelect)
  useEffect(() => {
    latestSelect.current = onSelect
  }, [onSelect])
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!open) return
    let current = true
    loadPostcode().then(
      () => {
        if (!current || !container.current) return
        container.current.replaceChildren()
        embedPostcode(container.current, (data) => latestSelect.current(toRoadAddress(data)))
      },
      () => {
        if (current) setFailed(true)
      },
    )
    return () => {
      current = false
    }
  }, [open, attempt])

  return (
    <BottomSheet open={open} onClose={onClose} title="가게 주소 찾기" description="도로명이나 건물 이름으로 찾아 주세요.">
      {failed ? (
        <InfoBox
          tone="critical"
          title="주소 찾기를 불러오지 못했어요."
          action={{
            label: '다시 불러오기',
            onClick: () => {
              setFailed(false)
              setAttempt((count) => count + 1)
            },
          }}
        >
          연결 상태를 확인하고 다시 불러와 주세요.
        </InfoBox>
      ) : (
        <div ref={container} className="h-[440px] overflow-hidden rounded-xl" />
      )}
    </BottomSheet>
  )
}

/**
 * 가게 정보로 정해지는 할 일(가입 때 정한 것 등). 정해져 있으면 따로 할 것이 없다.
 *
 * 확인 필요면 "할 것 없음"이라 하지 않는다. 폐업 날짜를 "아직 안 정했어요"로 고른 가게가 여기 온다.
 * 정해지면 결과 알려주기로 알려 주게 한다 — 판단이 가게 정보를 고친다(#237).
 */
export function InfoFlow({ task }: { task: RoadmapTaskView }) {
  const navigate = useNavigate()
  const { search } = useLocation()
  if (task.status !== 'NEEDS_CONFIRMATION') {
    return (
      <TaskFrame>
        <TaskHeader task={task} />
        <InfoBox>이 일은 여기서 따로 하실 것이 없어요. 리본이 가게 정보로 확인해요.</InfoBox>
      </TaskFrame>
    )
  }
  return (
    <TaskFrame>
      <TaskHeader task={task} />
      {/* TODO(#237): 문구는 PM 확인 전 임시 */}
      <InfoBox>아직 정해지지 않았어요. 정해지면 결과 알려주기로 알려 주세요.</InfoBox>
      <div className="mt-auto">
        <Button onClick={() => navigate({ pathname: '/results', search }, { viewTransition: true })}>결과 알려주기</Button>
      </div>
    </TaskFrame>
  )
}

/** 할 일 이름과 검수한 설명 */
function TaskHeader({ task, sub }: { task: RoadmapTaskView; sub?: string }) {
  return (
    <div>
      <h1 className="text-24 font-bold">{task.title}</h1>
      {sub && <p className="mt-2 text-17 text-fg-neutral-muted">{sub}</p>}
      {task.guidance && <p className="mt-3 text-15 text-fg-neutral-muted">{task.guidance}</p>}
    </div>
  )
}

function SaveNotice({ save }: { save: SaveState }) {
  if (save === 'FAILED') {
    return (
      <InfoBox tone="critical" title="저장하지 못했어요.">
        연결이 불안정했을 수 있어요. 다시 눌러 주세요.
      </InfoBox>
    )
  }
  if (save === 'REJECTED') {
    return (
      <InfoBox tone="critical" title="이 할 일은 지금 기록할 수 없어요.">
        폐업 전체 순서에서 다시 확인해 주세요.
      </InfoBox>
    )
  }
  return null
}

/** 탭 없는 화면의 틀 */
function TaskFrame({ children }: { children: ReactNode }) {
  return (
    <div className="screen-frame mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar title="할 일" />
      <main className="flex flex-1 flex-col gap-5 px-4 pt-2 pb-8">{children}</main>
    </div>
  )
}
