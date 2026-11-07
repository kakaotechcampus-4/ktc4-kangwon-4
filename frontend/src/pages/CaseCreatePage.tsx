import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { MAX_EMPLOYEE_COUNT, toCaseCreateRequest } from '../adapters/case'
import briefcaseUrl from '../assets/emoji/briefcase.svg'
import calendarUrl from '../assets/emoji/calendar.svg'
import clipboardUrl from '../assets/emoji/clipboard.svg'
import coffeeUrl from '../assets/emoji/coffee.svg'
import franchiseUrl from '../assets/emoji/franchise.svg'
import hospitalUrl from '../assets/emoji/hospital.svg'
import keyUrl from '../assets/emoji/key.svg'
import moneyUrl from '../assets/emoji/money.svg'
import noodleUrl from '../assets/emoji/noodle.svg'
import olderPersonUrl from '../assets/emoji/older-person.svg'
import pageUrl from '../assets/emoji/page.svg'
import phoneUrl from '../assets/emoji/phone.svg'
import safetyVestUrl from '../assets/emoji/safety-vest.svg'
import searchUrl from '../assets/emoji/search.svg'
import staffUrl from '../assets/emoji/staff.svg'
import { QuestionScreen } from '../components/ui/QuestionScreen'
import { HammerLoader } from '../components/ui/HammerLoader'
import { InfoBox } from '../components/ui/InfoBox'
import { useCase } from '../hooks/useCase'
import { ApiError, request, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import { diagnosisSteps, isStepAnswered, reachableStep, type DiagnosisStep } from '../lib/diagnosisSteps'
import { useDiagnosisStore } from '../stores/useDiagnosisStore'
import type { DiagnosisAnswers } from '../types/view'

type QuestionProps = Omit<Parameters<typeof QuestionScreen>[0], 'position' | 'onBack' | 'onPrevious' | 'notice'>

/** 여럿 고르는 질문의 아래 버튼. 하나도 안 골랐으면 회색으로 "없다"를 고르게 한다 */
function multiAction(count: number, noneLabel: string, onClick: () => void): QuestionProps['action'] {
  return count > 0
    ? { label: `${count}개 선택 완료`, onClick }
    : { label: noneLabel, onClick, variant: 'neutral' }
}

const toggle = <T,>(list: T[] | null, value: T): T[] =>
  (list ?? []).includes(value) ? (list ?? []).filter((item) => item !== value) : [...(list ?? []), value]

/**
 * 질문 하나의 문구와 보기.
 *
 * 시안(M01)에 있는 다섯 질문은 시안 문구 그대로다. 한 곳만 고쳤다: 직원 수의 "왜 여쭤보냐면"에서
 * 시안의 "30일 전에 알리고"를 뺐다. 기한은 서버가 판단할 몫이다(FE 규칙 7).
 *
 * 시안에 없는 네 질문(프랜차이즈·월세·예전 직원·4대보험)은 #119·#133에서 정한 값을 받으려고
 * 더했다. 문구는 11/03 시우님 확인.
 *
 * `next`는 고른 답을 반영한 뒤 다음 질문으로 넘긴다. 여럿 고르는 질문은 아무것도 안 고르고
 * 넘어가도 "없음"이라는 답이라, 넘길 때 빈 목록을 답으로 남긴다.
 */
function questionOf(
  step: DiagnosisStep,
  answers: DiagnosisAnswers,
  setAnswers: (patch: Partial<DiagnosisAnswers>) => void,
  next: (patch?: Partial<DiagnosisAnswers>) => void,
): QuestionProps {
  const plainNext = { label: '다음', onClick: () => next(), disabled: !isStepAnswered(step, answers) }

  switch (step) {
    case 'biz':
      return {
        title: { pre: '', highlight: '어떤 가게', post: '를\n정리하시나요?' },
        sub: '업종마다 신고할 곳이 달라요',
        input: {
          type: 'list',
          options: [
            { value: 'PERSONAL_CAFE', label: '개인 카페', sub: '직접 차려서 운영해요', emoji: coffeeUrl },
            { value: 'FRANCHISE_CAFE', label: '프랜차이즈 카페', sub: '본사와 가맹 계약이 있어요', emoji: franchiseUrl },
            { value: 'RESTAURANT', label: '다른 음식점', sub: '식당, 분식, 빵집 등', emoji: noodleUrl },
          ],
          selected: answers.business,
          onSelect: (value) => setAnswers({ business: value as DiagnosisAnswers['business'] }),
        },
        action: plainNext,
      }

    case 'franchise':
      return {
        title: { pre: '', highlight: '프랜차이즈', post: ' 가게인가요?' },
        sub: '본사와 가맹 계약이 있으면 프랜차이즈예요',
        // "잘 모르겠어요"는 두지 않는다. 서버가 프랜차이즈 여부를 확정값으로만 받는다(#132)
        input: {
          type: 'pills',
          options: [
            { value: 'YES', label: '네, 프랜차이즈예요' },
            { value: 'NO', label: '아니요, 직접 차렸어요' },
          ],
          selected: answers.franchise === null ? null : answers.franchise ? 'YES' : 'NO',
          onSelect: (value) => setAnswers({ franchise: value === 'YES' }),
        },
        action: plainNext,
      }

    case 'situ': {
      const situations = answers.situations ?? []
      return {
        title: { pre: '가게에 ', highlight: '해당하는 것', post: '을\n모두 골라주세요' },
        sub: '고르신 것만 할 일에 넣어요',
        input: {
          type: 'grid',
          options: [
            { value: 'LEASE', label: '가게 자리를\n빌려서 써요', emoji: keyUrl },
            { value: 'STAFF', label: '같이 일하는\n직원이 있어요', emoji: staffUrl },
            { value: 'LOAN', label: '사업 대출이\n남아 있어요', emoji: moneyUrl },
            { value: 'CONTRACT', label: '배달앱·카드기\n계약이 있어요', emoji: phoneUrl },
          ],
          selected: situations,
          onToggle: (value) =>
            setAnswers({ situations: toggle(answers.situations, value as (typeof situations)[number]) }),
        },
        action: multiAction(situations.length, '해당하는 게 없어요', () => next({ situations })),
      }
    }

    case 'rent':
      return {
        title: { pre: '가게 ', highlight: '월세', post: '를 내고 계신가요?' },
        sub: '가족 가게나 무상으로 빌린 곳이면 "아니요"를 골라주세요',
        input: {
          type: 'pills',
          options: [
            { value: 'YES', label: '네, 내고 있어요' },
            { value: 'NO', label: '아니요, 안 내요' },
          ],
          selected: answers.paysRent === null ? null : answers.paysRent ? 'YES' : 'NO',
          onSelect: (value) => setAnswers({ paysRent: value === 'YES' }),
        },
        action: plainNext,
      }

    case 'restore':
      return {
        title: { pre: '계약서에 ', highlight: '원상복구 조항', post: '이\n있나요?' },
        sub: '가게를 원래대로 돌려놓기로 한 약속이에요',
        box: {
          label: '찾아볼 곳',
          items: [
            { emoji: pageUrl, title: '임대차계약서 특약사항', description: '보통 계약서 마지막 장에 있어요' },
            // 계약서는 가입 뒤 서류함에 올린다(진단 안에서 올리는 길은 없다). 시안 문구를 그대로 둔다(11/03 시우님)
            { emoji: searchUrl, title: '모르시면 리본이 찾아요', description: '계약서 사진만 올려주시면 돼요' },
          ],
        },
        input: {
          type: 'pills',
          options: [
            { value: 'EXISTS', label: '네, 있어요' },
            { value: 'NOT_EXISTS', label: '아니요, 없어요' },
            { value: 'UNKNOWN', label: '잘 모르겠어요' },
          ],
          selected: answers.restorationClause,
          onSelect: (value) =>
            setAnswers({ restorationClause: value as DiagnosisAnswers['restorationClause'] }),
        },
        action: plainNext,
      }

    case 'staff': {
      const full = answers.fullTimeCount
      const part = answers.partTimeCount
      // 서버가 받는 상한에서 더하기를 잠근다. 넘겨 보내면 422로 막힌다
      const atMax = full + part >= MAX_EMPLOYEE_COUNT
      return {
        title: { pre: '직원은 ', highlight: '몇 명', post: '인가요?' },
        sub: '지금 같이 일하는 분만 세어 주세요',
        box: {
          label: '왜 여쭤보냐면',
          items: [
            {
              emoji: clipboardUrl,
              title: '4대보험에 가입한 직원',
              description: '직원이 있으면 미리 알리고, 4대보험도 정리해야 해요',
            },
          ],
        },
        input: {
          type: 'stepper',
          rows: [
            {
              label: '정직원',
              sub: '주 15시간 이상 일해요',
              value: full,
              onDecrease: () => setAnswers({ fullTimeCount: Math.max(0, full - 1) }),
              onIncrease: () => setAnswers({ fullTimeCount: full + 1 }),
              increaseDisabled: atMax,
            },
            {
              label: '아르바이트',
              sub: '짧게 일하는 분',
              value: part,
              onDecrease: () => setAnswers({ partTimeCount: Math.max(0, part - 1) }),
              onIncrease: () => setAnswers({ partTimeCount: part + 1 }),
              increaseDisabled: atMax,
            },
          ],
        },
        action: plainNext,
      }
    }

    case 'hadStaff':
      return {
        title: { pre: '예전에 ', highlight: '직원을 둔 적', post: '이 있나요?' },
        sub: '그만둔 직원도 정리할 일이 남아 있을 수 있어요',
        input: {
          type: 'pills',
          options: [
            { value: 'YES', label: '네, 있어요' },
            { value: 'NO', label: '아니요, 없어요' },
            // 모르는 사장님이 [아니요]를 누르면 직원 정산·보험 신고 할 일이 "해당 없음"으로 빠진다(#237)
            { value: 'UNKNOWN', label: '잘 모르겠어요' },
          ],
          selected:
            answers.hadEmployees === null
              ? null
              : answers.hadEmployees === 'UNKNOWN'
                ? 'UNKNOWN'
                : answers.hadEmployees
                  ? 'YES'
                  : 'NO',
          onSelect: (value) =>
            setAnswers({ hadEmployees: value === 'UNKNOWN' ? 'UNKNOWN' : value === 'YES' }),
        },
        action: plainNext,
      }

    case 'insurance': {
      // "잘 모르겠어요"를 골랐다가 돌아오면 아무것도 안 고른 모양에서 다시 고른다
      const insurances = Array.isArray(answers.insurances) ? answers.insurances : []
      return {
        // "가게 이름으로"를 강조한다. 혼자 하는 사장님도 개인으로는 국민연금·건강보험에 들어 있어,
        // 그냥 "가입했던 보험"이라고 물으면 사업장 보험이 아닌 것을 고르게 된다
        title: { pre: '', highlight: '가게 이름으로', post: ' 가입했던\n보험을 모두 골라주세요' },
        sub: '이미 탈퇴하거나 끝난 보험도 골라주세요',
        input: {
          type: 'grid',
          options: [
            { value: 'PENSION', label: '국민연금', emoji: olderPersonUrl },
            { value: 'HEALTH', label: '건강보험', emoji: hospitalUrl },
            { value: 'EMPLOYMENT', label: '고용보험', emoji: briefcaseUrl },
            { value: 'INDUSTRIAL_ACCIDENT', label: '산재보험', emoji: safetyVestUrl },
          ],
          selected: insurances,
          onToggle: (value) =>
            setAnswers({ insurances: toggle(insurances, value as (typeof insurances)[number]) }),
        },
        action: multiAction(insurances.length, '가입한 적 없어요', () => next({ insurances })),
        // 모르는 사장님이 [가입한 적 없어요]를 누르면 보험 신고 할 일이 "해당 없음"으로 빠진다(#156 다물님)
        secondary: { label: '잘 모르겠어요', onClick: () => next({ insurances: 'UNKNOWN' }) },
      }
    }

    case 'date':
      return {
        title: { pre: '', highlight: '언제', post: ' 문을 닫으실\n생각이세요?' },
        sub: '정하지 않으셨어도 괜찮아요',
        illustration: calendarUrl,
        input: {
          type: 'pills',
          options: [
            { value: 'THIS_MONTH', label: '이번 달 안에' },
            { value: 'NEXT_MONTH', label: '다음 달' },
            { value: 'UNDECIDED', label: '아직 안 정했어요' },
          ],
          selected: answers.closure,
          onSelect: (value) => setAnswers({ closure: value as DiagnosisAnswers['closure'] }),
        },
        action: { ...plainNext, label: '폐업 순서 만들기' },
      }
  }
}

type DiagnosisQuestionProps = Pick<
  Parameters<typeof QuestionScreen>[0],
  'position' | 'onBack' | 'onPrevious' | 'notice'
> & {
  step: DiagnosisStep
  answers: DiagnosisAnswers
  setAnswers: (patch: Partial<DiagnosisAnswers>) => void
  next: (patch?: Partial<DiagnosisAnswers>) => void
}

/**
 * 질문 하나를 그린다. `questionOf`의 문구·보기에 화면 위치와 뒤로가기를 붙인다.
 *
 * 따로 컴포넌트로 둔 것은 린트(`react-hooks/refs`) 때문이다. `next`는 보내기에서
 * `alive` ref를 쓰는데, 그리는 도중 함수 호출로 넘기면 "그리는 중에 ref를 읽을 수 있다"고
 * 막는다. 속성으로 넘기면 누를 때만 부른다는 것이 드러난다.
 */
function DiagnosisQuestion({ step, answers, setAnswers, next, ...screen }: DiagnosisQuestionProps) {
  return <QuestionScreen {...questionOf(step, answers, setAnswers, next)} {...screen} />
}

/**
 * 저장하는 동안 (시안 M01b).
 *
 * 시안은 0.75초마다 체크가 하나씩 켜지는 세 줄을 두지만 뺐다. 서버는 저장만 하고 금방
 * 답하고, 판단은 그 뒤에 따로 돈다 — 시간에 맞춰 켜는 체크는 하지 않은 일을 한 것처럼 보인다.
 * 실제 판단을 기다리는 일은 홈의 할 일 카드(판단 중)가 맡는다.
 */
function CreatingScreen() {
  return (
    <div className="screen-frame mx-auto flex h-dvh max-w-[402px] flex-col items-center justify-center gap-8 bg-bg-layer-default px-6 pb-24 text-center">
      <HammerLoader size={72} label="폐업 순서를 만들고 있어요" />
      <div>
        <p className="text-26 font-bold whitespace-pre-line">{'사장님 가게에 맞는\n폐업 순서를 만들고 있어요'}</p>
        <p className="mt-2.5 text-17 text-fg-neutral-muted">답해 주신 내용만 써요</p>
      </div>
    </div>
  )
}

type SubmitState = 'IDLE' | 'PENDING' | 'FAILED'

/** 앞 질문에서 [다음]으로 넘어온 기록에 붙이는 표시. 그 기록에서만 [뒤로]가 브라우저 뒤로가기다 */
const STEPPED = 'diagnosis-step'

/**
 * 상황 진단 (시안 M01 · M01b). 질문을 한 장씩 묻고, 마지막에 가입 요청을 보낸다.
 *
 * 질문마다 주소(`?step=`)가 다르다. 앞으로 넘길 때마다 기록을 쌓아서, 화면의 [뒤로]와
 * 브라우저 뒤로가기가 똑같이 앞 질문으로 간다. 앞 답을 고치려면 그 질문까지 뒤로 가야
 * 하므로, 쌓인 기록은 늘 지금 답과 맞는다. 주소를 직접 고쳐 맞지 않는 질문을 열면
 * `reachableStep`이 보여줄 질문으로 바꿔 끼운다.
 *
 * 답은 화면이 아니라 `useDiagnosisStore`에 둔다. 질문을 넘기거나 새로고침해도 남는다.
 *
 * Case가 이미 있으면 홈으로 보낸다. 가입한 뒤 뒤로가기로 이 화면에 닿으면 빈 진단이
 * 다시 열려 두 번째 Case를 만들려 든다 — 서버는 회원당 하나라 409로 막는다.
 * 묻는 동안에도 질문은 그린다. 내용이 고정이라 기다릴 이유가 없다. 서버를 못 불렀어도
 * 그대로 둔다. 처음 온 사장님이 아무것도 못 하게 되고, 보내면 서버가 409로 막아 준다.
 */
export function CaseCreatePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { query } = useCase()
  const answers = useDiagnosisStore((state) => state.answers)
  const setAnswers = useDiagnosisStore((state) => state.setAnswers)
  const resetAnswers = useDiagnosisStore((state) => state.reset)
  const [submit, setSubmit] = useState<SubmitState>('IDLE')

  /**
   * 홈으로 떠나는 중. 이때는 아무것도 그리지 않는다.
   *
   * 떠나면서 진단 답을 비우는데, 비우는 순간 이 화면이 한 번 더 그려진다. 그때 답이 비어
   * 있으니 아래 주소 맞추기가 첫 질문(`?step=biz`)으로 바꿔 끼우고, 그 이동이 홈 이동을 덮어쓴다.
   */
  const [leaving, setLeaving] = useState(false)

  /**
   * 기다리는 사이 화면을 떠날 수 있다. 떠난 화면의 상태를 바꾸지 않는다.
   *
   * 정리 함수만 두면 StrictMode의 이중 실행에서 첫 마운트가 곧바로 false가 되므로
   * 실행할 때마다 다시 true로 세운다.
   */
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  if (leaving) return null

  /*
    `?mock=creating`은 저장하는 동안의 화면을 바로 연다. Mock 에서는 서버를 부르지 않아
    이 화면이 스치지도 않고 지나가서, 눈으로 볼 길이 따로 필요하다. Case 있음 검사보다
    앞에 둔다 — 다른 Mock 키처럼 Case가 있는 것으로 보고 홈으로 보내 버리지 않게 한다.
  */
  if (submit === 'PENDING' || readMockKey(location.search) === 'creating') return <CreatingScreen />

  if (query.status === 'READY') {
    return <Navigate to={{ pathname: '/case', search: location.search }} replace />
  }

  const requested = new URLSearchParams(location.search).get('step')
  const step = reachableStep(requested, answers)

  /** `?mock=` 같은 다른 값은 그대로 두고 질문만 바꾼다 */
  const urlOf = (target: DiagnosisStep) => {
    const params = new URLSearchParams(location.search)
    params.set('step', target)
    return { pathname: '/cases/new', search: `?${params}` }
  }

  if (step !== requested) return <Navigate to={urlOf(step)} replace />

  /**
   * 가입 요청이 받아들여졌다. 홈으로 가고 진단 답을 비운다.
   *
   * 이미 Case가 있다는 409도 여기로 온다. 응답만 끊겨 다시 누른 경우라 사실상 성공이다.
   * 401(로그인 만료)과 실패에서는 비우지 않는다 — 다시 로그인하거나 다시 눌러 이어서 보낸다.
   *
   * `?mock=`을 이어주지 않는다. 여기까지 오는 길이 `?mock=no-case`였는데 그대로 들고
   * 가면 방금 만든 Case가 없는 척하게 된다.
   */
  function arrive() {
    setLeaving(true)
    navigate('/case', { replace: true })
    resetAnswers()
  }

  function handleSubmit() {
    const body = toCaseCreateRequest(answers, new Date())
    // 순서가 이미 막고 있다. 여기서 한 번 더 거르는 것은 빈 값을 서버까지 보내지 않으려는 것
    if (body === null) return

    /**
     * 가짜 세션은 서버에 없는 사용자라 401이 온다. `?mock=`을 따라온 경우도 마찬가지로
     * 서버를 부르지 않는다 — 다른 화면이 전부 Mock인데 여기서만 진짜 Case를 만들면,
     * 회원당 하나라 지울 수도 없는 Case가 남는다.
     */
    if (usesMockData(location.search)) return arrive()

    setSubmit('PENDING')

    request('/cases', { method: 'POST', body })
      .then(() => {
        if (alive.current) arrive()
      })
      .catch((error: unknown) => {
        // 떠난 화면에서 이동을 실행하면, 사용자가 보고 있던 다른 화면에서 끌려 나온다
        if (!alive.current) return
        if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })
        if (error instanceof ApiError && error.status === 409) return arrive()

        setSubmit('FAILED')
      })
  }

  /**
   * 앞 질문으로. 이 화면이 앞 질문에서 넘겨 온 기록이면 브라우저 뒤로가기와 같게 한다.
   *
   * 그렇지 않으면(주소로 바로 열었거나, 로그인 뒤 진입 분기가 주소를 바꿔 끼우며 들어왔으면)
   * 앞 질문으로 주소를 바꿔 끼운다. 그대로 뒤로 가면 카카오나 로그인 화면으로 나가 버린다.
   * `location.key`로는 가를 수 없다 — 진입 분기를 거쳐 들어와도 `'default'`가 아니다.
   */
  const steps = diagnosisSteps(answers)
  const index = steps.indexOf(step)
  const previous = steps[index - 1]
  const back =
    previous === undefined
      ? undefined
      : () => (location.state === STEPPED ? navigate(-1) : navigate(urlOf(previous), { replace: true }))

  /**
   * 다음 질문으로. 보기를 누를 때 답이 이미 저장소에 들어가 있어서, 지금 순서(`steps`)가
   * 곧 고른 답에 맞는 순서다 — "빌린 가게"를 고른 순간 월세 질문이 이미 들어 있다.
   *
   * `patch`는 여럿 고르는 질문에서 하나도 안 고르고 넘길 때만 쓴다. 안 고른 것도
   * "없음"이라는 답이라 빈 목록으로 남긴다. 순서는 바뀌지 않는다(빈 목록과 아직 안 고름을 같게 센다).
   */
  function next(patch?: Partial<DiagnosisAnswers>) {
    if (patch) setAnswers(patch)

    const following = steps[index + 1]
    if (following === undefined) return handleSubmit()
    navigate(urlOf(following), { state: STEPPED })
  }


  return (
    <DiagnosisQuestion
      step={step}
      answers={answers}
      setAnswers={setAnswers}
      next={next}
      position={{ current: index + 1, total: steps.length }}
      onBack={back}
      // 시안은 마지막 질문에만 아래 [이전]을 둔다
      onPrevious={step === 'date' ? back : undefined}
      // 보내는 곳은 마지막 질문이다. 앞 질문으로 돌아가서까지 실패를 띄우지 않는다
      notice={
        submit === 'FAILED' &&
        step === 'date' && (
          <InfoBox tone="critical" title="저장하지 못했어요">
            잠시 후 다시 눌러 주세요. 고르신 답은 그대로 있어요.
          </InfoBox>
        )
      }
    />
  )
}
