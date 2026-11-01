import {
  IconExclamationmarkCircleFill,
  IconExclamationmarkCircleLine,
  IconPersonLine,
  IconSparkle2Fill,
} from '@karrotmarket/react-monochrome-icon'
import type { ReactNode } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { Button } from '../components/ui/Button'
import { HomeBanner } from '../components/ui/HomeBanner'
import { HomeStageCard } from '../components/ui/HomeStageCard'
import { TaskCard } from '../components/ui/TaskCard'
import { useCase } from '../hooks/useCase'
import type { FailureNotice, JudgmentView } from '../types/view'

/**
 * 홈(현재 Case). 사용자가 돌아올 곳이고, 이 제품에서 유일하게 "지금 상황"을 보여주는 화면이다.
 *
 * 그래서 들어올 때마다 서버에 다시 묻는다. 앞 화면에서 받은 값을 들고 오면 편하지만,
 * 그 값이 히스토리에 남아 오래된 Case가 지금 상황인 척 다시 뜬다.
 *
 * **조회와 판단은 다른 축이다.** 서버를 잘 불렀어도 판단은 아직 안 끝날 수 있다.
 * 사장님 입장에서 기다려야 하는 상황과 답해야 하는 상황은 할 일이 전혀 다르다.
 *
 * 어느 상태에서도 **누를 것이 하나는 있어야 한다.** 할 일이 없다는 이유로 버튼까지
 * 사라지면 사장님은 화면만 보다 나가게 된다.
 *
 * 가게 정보 목록(업종·직원 수 등)은 시안 홈에 없어 뺐다. 들어갈 자리는 로드맵·기록(7번 PR)이다.
 */
export function CurrentCasePage() {
  const { search } = useLocation()
  const { query, refresh, refreshing, waitedTooLong } = useCase()

  /**
   * 아직 Case를 만들지 않은 사용자가 주소로 직접 들어온 경우다.
   * 빈 화면을 보여주는 대신 만들러 보낸다.
   */
  if (query.status === 'EMPTY') return <Navigate to={{ pathname: '/start', search }} replace />

  if (query.status === 'LOADING') {
    return (
      <HomeFrame headline="조금만 기다려 주세요">
        <LoadingCard />
      </HomeFrame>
    )
  }

  if (query.status === 'LOAD_FAILED') {
    return (
      <HomeFrame headline="가게 상황을 불러오지 못했어요">
        <TaskCard
          tone="neutral"
          icon={<IconExclamationmarkCircleLine size={40} />}
          badge="불러오기 실패"
          title="연결 상태를 확인해 주세요"
          description="입력하신 내용은 그대로 있어요."
          actions={
            <Button size="lg" onClick={refresh} disabled={refreshing}>
              다시 불러오기
            </Button>
          }
        />
      </HomeFrame>
    )
  }

  const { view, stale } = query
  const card = judgmentCard(view.judgment, waitedTooLong)
  const recheck = (
    <Button variant="neutral" size={card.main ? 'md' : 'lg'} onClick={refresh} disabled={refreshing}>
      상태 다시 확인
    </Button>
  )

  return (
    <HomeFrame headline={card.headline}>
      {/*
        마지막으로 받은 내용을 그대로 두고 알리기만 한다. 지우면 사장님은 적어낸 것이
        날아간 줄 알고, 조용히 두면 지난 판단을 지금 것으로 읽는다.
      */}
      {stale && (
        <p role="status" className="rounded-14 bg-bg-neutral-weak px-4 py-3 text-15">
          <strong className="font-bold">최신 상태를 확인하지 못했어요.</strong> 아래는 마지막으로
          받은 내용이에요.
        </p>
      )}

      <TaskCard
        {...card.props}
        actions={
          <>
            {card.main?.(stale)}
            {recheck}
          </>
        }
      />
    </HomeFrame>
  )
}

/** 시안 홈의 뼈대: 리본이 해둔 일 띠 · 머리 문구 · 할 일 카드 · 단계 카드 */
function HomeFrame({ headline, children }: { headline: string; children: ReactNode }) {
  return (
    <>
      <HomeBanner />
      <div className="flex flex-1 flex-col gap-3 px-4 pt-6 pb-4">
        <h1 className="mb-1 text-24 font-bold text-pretty">{headline}</h1>
        {children}
        <HomeStageCard />
      </div>
    </>
  )
}

/**
 * 처음 불러오는 동안 할 일 카드 자리를 채우는 회색 막대.
 * 글자 대신 모양을 먼저 보여줘서, 다 불러왔을 때 화면이 덜 흔들린다.
 */
function LoadingCard() {
  const bar = 'block rounded-md bg-bg-neutral-weak animate-skeleton-pulse motion-reduce:animate-none'

  return (
    <section
      role="status"
      className="flex flex-col gap-3 rounded-20 bg-bg-layer-default px-5 pt-6 pb-5 shadow-raised"
    >
      <span className="sr-only">가게 상황을 불러오고 있어요</span>
      <span aria-hidden="true" className={`${bar} size-18 rounded-20`} />
      <span aria-hidden="true" className={`${bar} mt-2 h-4 w-1/4`} />
      <span aria-hidden="true" className={`${bar} h-7 w-4/5`} />
      <span aria-hidden="true" className={`${bar} h-5 w-3/5`} />
    </section>
  )
}

interface JudgmentCard {
  headline: string
  props: Omit<Parameters<typeof TaskCard>[0], 'actions'>
  /**
   * 회색 "상태 다시 확인" 위에 놓을 주 버튼. `stale`이면 잠근다.
   * 없으면 "상태 다시 확인"이 카드의 큰 버튼이 된다.
   */
  main?: (stale: boolean) => ReactNode
}

const CRITICAL_ICON = <IconExclamationmarkCircleFill size={40} />
const NEUTRAL_ICON = <IconExclamationmarkCircleLine size={40} />

/**
 * 판단 상태에 맞는 머리 문구와 할 일 카드.
 *
 * 여섯 갈래를 전부 적는다. `switch`가 아니라 `if`로 흘려두면 새 상태가 늘었을 때
 * 아무 화면도 안 나오고 조용히 빈 자리가 생긴다.
 *
 * 색은 사장님이 할 일이 있는지로 나눈다. 할 일이면 주황, 사장님이 답하거나 골라야 하면 빨강,
 * 우리 쪽에서 멈춘 것이면 회색이다. 우리 쪽 문제를 빨강으로 칠하면 사장님 탓으로 읽힌다.
 */
function judgmentCard(judgment: JudgmentView, waitedTooLong: boolean): JudgmentCard {
  switch (judgment.status) {
    /*
      막힌 것(`blocker`)은 홈에 그리지 않는다. 카드 안에 한 줄로 넣어 봤는데, 할 일의 이유와
      겹쳐 읽혀 빼기로 했다(11/01). 할 일 상세(4번 PR)에서 다시 정한다.
    */
    case 'DONE': {
      const { nextAction } = judgment
      return {
        headline: '오늘 하실 일은 하나예요',
        props: {
          tone: 'brand',
          icon: <IconPersonLine size={40} />,
          badge: '사장님 할 일',
          title: nextAction.title,
          description: nextAction.reason,
        },
        main: (stale) => (
          <TaskButton hasQuestions={(nextAction.questions?.length ?? 0) > 0} locked={stale} />
        ),
      }
    }

    /*
      오래 기다린 문구를 따로 둔다. 판단 도중 서버가 다시 뜨면 그 Case 는 계속
      `PENDING` 으로 남아(#40) 끝나지 않는데, 그때까지 "곧 됩니다" 라고 말하면
      사장님은 언제까지 기다려야 하는지 모른 채 화면만 붙들고 있게 된다.
    */
    case 'PENDING':
      return {
        headline: '지금은 리본이 일하고 있어요',
        props: {
          tone: 'brand',
          icon: <IconSparkle2Fill size={40} />,
          badgeIcon: <IconSparkle2Fill size={16} aria-hidden="true" />,
          badge: 'AI 처리 중',
          ...(waitedTooLong
            ? {
                title: '판단이 오래 걸리고 있어요',
                description:
                  '가게 정보는 그대로 있어요. 지금은 저희 쪽에서 더 확인이 필요한 상태라, 창을 닫으셨다가 나중에 다시 들러 주세요.',
              }
            : {
                title: '다음 할 일을 정하고 있어요',
                description:
                  '가게 정보는 저장됐어요. 시간이 조금 걸릴 수 있으니 나중에 다시 오셔도 됩니다.',
              }),
        },
      }

    /*
      답을 보내는 길은 서버에 이미 있다(`POST /cases/results`). 연결은 결과 입력을 새로 만드는
      4번 PR에서 한다. 그때까지 버튼 자리만 두고 꺼 둔다.
    */
    case 'NEEDS_MORE_INFO':
      return {
        headline: '확인하실 일이 있어요',
        props: {
          tone: 'critical',
          icon: CRITICAL_ICON,
          badge: '확인 필요',
          title: '이 내용을 알려주세요',
          // 질문이 곧 설명이라 설명 문단을 따로 두지 않는다. 둘 다 두면 카드가 글로 꽉 찬다
          children: (
            <ul className="flex flex-col gap-2 rounded-14 bg-bg-neutral-weak px-4 py-3 text-16">
              {judgment.questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          ),
        },
        // TODO(4번 PR): 결과 입력 화면에 잇는다
        main: () => (
          <Button size="lg" disabled>
            답하러 가기
          </Button>
        ),
      }

    /*
      어긋난 항목이 응답에 없어서(#66) 무엇과 무엇이 다른지는 아직 못 보여준다.
      `/confirm` 으로 보내는 버튼은 달지 않는다. 어긋난 목록을 받아올 API 가 없어서
      그 화면이 빈손으로 열리고 `/` 로 튕긴다 — 되지 않는 일을 버튼으로 약속하지 않는다.
    */
    case 'CONFLICT':
      return {
        headline: '확인하실 일이 있어요',
        props: {
          tone: 'critical',
          icon: CRITICAL_ICON,
          badge: '확인 필요',
          title: '확인이 필요한 내용이 있어요',
          description:
            '알려주신 내용이 저장된 기록과 달라서, 어느 쪽이 맞는지 여쭤봐야 해요. 확인하시는 화면을 준비하고 있습니다.',
        },
      }

    /*
      "잠시 후 다시" 라고 말하지 않는다. 실패한 Case 를 다시 판단하는 수단이 아직 없어서
      (#57) 몇 번을 눌러도 같은 실패가 돌아온다.

      이유마다 문구만 갈리고 **누를 것은 다섯 갈래 모두 재조회 하나다.**
    */
    case 'FAILED': {
      const { askOwner, title, description } = failureCard(judgment.notice)
      return askOwner
        ? {
            headline: '확인하실 일이 있어요',
            props: { tone: 'critical', icon: CRITICAL_ICON, badge: '확인 필요', title, description },
          }
        : {
            headline: '할 일 정리가 멈췄어요',
            props: { tone: 'neutral', icon: NEUTRAL_ICON, badge: '판단 멈춤', title, description },
          }
    }

    /*
      서버가 우리가 모르는 상태를 보냈거나 내용이 비어서 온 경우다. "정보가 부족합니다"로
      바꿔 보여주지 않는다 — 서버가 틀린 것을 사장님이 덜 적어낸 탓으로 읽게 된다.
    */
    case 'UNRECOGNIZED':
      return {
        headline: '할 일 정리가 멈췄어요',
        props: {
          tone: 'neutral',
          icon: NEUTRAL_ICON,
          badge: '불러오기 실패',
          title: '판단 내용을 불러오지 못했어요',
          description: '가게 정보는 그대로 있어요. 잠시 후 다시 확인해 주세요.',
        },
      }

    default: {
      // 상태가 늘면 여기서 컴파일이 막힌다
      const unhandled: never = judgment
      return unhandled
    }
  }
}

/**
 * 할 일 상세(`/task`)로 가는 버튼. 최신 상태를 확인하지 못했으면 잠근다 — 지난 할 일을
 * 지금 할 일처럼 열어 보고 그 결과를 보내게 된다.
 *
 * 이름은 시안의 "물어볼 내용 보기"를 따르되, 물어볼 말이 없는 할 일에서는 거짓말이 되어
 * "자세히 보기"로 둔다.
 */
function TaskButton({ hasQuestions, locked }: { hasQuestions: boolean; locked: boolean }) {
  const navigate = useNavigate()
  const { search } = useLocation()

  return (
    <>
      <Button size="lg" disabled={locked} onClick={() => navigate({ pathname: '/task', search })}>
        {hasQuestions ? '물어볼 내용 보기' : '자세히 보기'}
      </Button>
      {locked && (
        <p className="text-center text-14 text-fg-neutral-muted">
          최신 상태를 확인한 뒤에 볼 수 있어요
        </p>
      )}
    </>
  )
}

/**
 * 다시 알아야 할 항목을 한 문장으로.
 *
 * **조사를 붙이지 않는다.** "업종을" 과 "범위를" 은 받침에 따라 갈리는데, 그걸 맞추는
 * 규칙을 넣기에는 이 문구 자체가 임시다. 항목을 문장 끝에 떼어 두면 조사가 필요 없다.
 */
function requestedText({ fields, partial }: { fields: string[]; partial: boolean }): string {
  if (fields.length === 0) return '어떤 내용이 더 필요한지는 아직 확인되지 않았어요.'

  return `이 내용을 더 알아야 해요 — ${fields.join(', ')}${partial ? ' 등' : ''}.`
}

/**
 * 실패 이유에 맞는 안내.
 *
 * TODO(#55): 문구는 PM 이 정한다. 지금은 **상황을 사실대로 적기만 한** 초안이다.
 *
 * 아직 지켜야 할 것 둘:
 *   - **못 하는 일을 약속하지 않는다.** 실패한 Case 를 다시 판단시키는 수단이 없고(#57)
 *     결과를 다시 알려주는 입력 경로도 아직 없다
 *   - **"상태 다시 확인" 을 재판단으로 읽히게 쓰지 않는다.** 그 버튼은 저장된 상태를 다시
 *     읽을 뿐이다
 *
 * `askOwner`는 사장님이 알려줘야 풀리는 실패인지다. 이것만 빨강 "확인 필요"로 칠한다.
 */
function failureCard(notice: FailureNotice): {
  askOwner: boolean
  title: string
  description: string
} {
  switch (notice.kind) {
    /*
      서버가 다시 해볼 수 있다고 분류했을 뿐, 원인이 일시적이라는 뜻은 아니다.
      그래서 "잠시 후 다시" 도 "곧 됩니다" 도 쓰지 않는다.
    */
    case 'RETRY_AVAILABLE':
      return {
        askOwner: false,
        title: '다음 할 일을 정하지 못했어요',
        description: '가게 정보는 그대로 있어요. 다시 판단해 드리는 기능을 준비하고 있습니다.',
      }

    /*
      **사장님이 잘못 적었다는 뜻이 아니라** 아직 모르는 것이 있다는 뜻이라,
      문구가 탓하는 말로 읽히지 않게 쓴다.
    */
    case 'NEEDS_DETAIL':
      return {
        askOwner: true,
        title: '추가 확인이 필요해요',
        description: `${requestedText(notice)} 알려주시는 자리는 준비하고 있습니다.`,
      }

    case 'SERVICE_SIDE':
      return {
        askOwner: false,
        title: '서비스에서 확인이 필요한 문제가 생겼어요',
        description: '가게 정보는 그대로 있어요. 이 건은 저희 쪽에서 봐야 하는 문제예요.',
      }

    /*
      **"이번 판단" 으로 범위를 좁혀 쓴다.** 그냥 "하실 수 있는 일이 없다" 고 하면 폐업
      절차 전체에 할 일이 없다는 말로 읽힌다.
    */
    case 'NO_RECOVERY':
      return {
        askOwner: false,
        title: '다음 할 일을 정하지 못했어요',
        description: '가게 정보는 그대로 있어요. 이번 판단에 대해서는 더 해 보실 수 있는 것이 없어요.',
      }

    /*
      이유를 못 알아들었다. `NO_RECOVERY` 와 같은 문구를 쓰지 않는다 — 저쪽은 서버가
      "할 것이 없다" 고 말한 것이고, 여기는 우리가 못 읽은 것이다.
    */
    case 'UNKNOWN_CAUSE':
      return {
        askOwner: false,
        title: '다음 할 일을 정하지 못했어요',
        description: '가게 정보는 그대로 있어요. 자세한 이유는 확인되지 않았어요.',
      }
  }
}
