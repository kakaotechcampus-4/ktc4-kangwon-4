import { Navigate, useLocation } from 'react-router'

import { AppShell } from '../components/AppShell'
import { BlockerCard } from '../components/BlockerCard'
import { FactList } from '../components/FactList'
import { FollowUpQuestionCard } from '../components/FollowUpQuestionCard'
import { NextActionCard } from '../components/NextActionCard'
import { NoticeCard } from '../components/NoticeCard'
import { useCase } from '../hooks/useCase'
import type { JudgmentView } from '../types/view'

/**
 * 현재 Case. 사용자가 돌아올 곳이고, 이 제품에서 유일하게 "지금 상황"을 보여주는 화면이다.
 *
 * 그래서 들어올 때마다 서버에 다시 묻는다. 앞 화면에서 받은 값을 들고 오면 편하지만,
 * 그 값이 히스토리에 남아 오래된 Case가 지금 상황인 척 다시 뜬다.
 *
 * **조회와 판단은 다른 축이다.** 서버를 잘 불렀어도 판단은 아직 안 끝날 수 있다.
 * 전에는 "다음 할 일이 없다" 하나로 판단 중·물어볼 게 있음·실패를 다 덮었는데,
 * 사장님 입장에서 기다려야 하는 상황과 답해야 하는 상황은 할 일이 전혀 다르다.
 *
 * 어느 상태에서도 **누를 것이 하나는 있어야 한다.** 할 일이 없다는 이유로 버튼까지
 * 사라지면 사장님은 화면만 보다 나가게 된다.
 */
export function CurrentCasePage() {
  const { search } = useLocation()
  const { query, refresh, refreshing, waitedTooLong } = useCase()

  if (query.status === 'LOADING') {
    return (
      <AppShell title="내 폐업 준비" width="wide">
        <section className="rounded-2xl bg-white p-5" role="status" aria-live="polite">
          <p className="text-base leading-relaxed text-gray-600">가게 상황을 불러오고 있어요.</p>
        </section>
      </AppShell>
    )
  }

  /**
   * 아직 Case를 만들지 않은 사용자가 주소로 직접 들어온 경우다.
   * 빈 화면을 보여주는 대신 만들러 보낸다.
   */
  if (query.status === 'EMPTY') return <Navigate to={{ pathname: '/start', search }} replace />

  if (query.status === 'LOAD_FAILED') {
    return (
      <AppShell title="내 폐업 준비" width="wide">
        <NoticeCard
          tone="NEUTRAL"
          title="가게 상황을 불러오지 못했어요."
          description="연결 상태를 확인하고 다시 시도해 주세요. 입력하신 내용은 그대로 있습니다."
          action={{ label: '다시 불러오기', onClick: refresh, disabled: refreshing }}
        />
      </AppShell>
    )
  }

  const { view, stale } = query
  const { facts, judgment } = view

  const confirmed = facts.filter((fact) => fact.status === 'CONFIRMED')
  const pending = facts.filter((fact) => fact.status !== 'CONFIRMED')

  return (
    <AppShell title="내 폐업 준비" width="wide">
      {/*
        마지막으로 받은 내용을 그대로 두고 알리기만 한다. 지우면 사장님은 적어낸 것이
        날아간 줄 알고, 조용히 두면 지난 판단을 지금 것으로 읽는다.
      */}
      {stale && (
        <NoticeCard
          tone="NEUTRAL"
          title="최신 상태를 확인하지 못했어요."
          description="아래는 마지막으로 받은 내용이에요."
          action={{ label: '다시 확인', onClick: refresh, disabled: refreshing }}
        />
      )}

      {/*
        DOM 순서가 곧 읽는 순서다. 넓은 화면에서 가게 정보가 옆으로 가더라도
        order 로 순서를 바꾸지 않는다 — 화면 낭독기는 이 순서를 따른다.
      */}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-8">
        <div className="flex min-w-0 flex-col gap-4">
          <JudgmentSection
            judgment={judgment}
            locked={stale}
            waitedTooLong={waitedTooLong}
            onRefresh={refresh}
            refreshing={refreshing}
          />
        </div>

        <aside className="flex min-w-0 flex-col gap-4">
          <FactList
            title="내 가게 상황"
            caption={`확인 ${confirmed.length} · 미확인 ${pending.length}`}
            facts={confirmed}
          />

          <FactList title="아직 확인 안 된 것" caption="순서대로 하나씩" facts={pending} />
        </aside>
      </div>
    </AppShell>
  )
}

interface JudgmentSectionProps {
  judgment: JudgmentView
  /** 지금 들고 있는 판단이 최신인지 확신할 수 없다 */
  locked: boolean
  /** 판단을 기다린 지 상한을 넘겨 자동 조회가 멈췄다 */
  waitedTooLong: boolean
  onRefresh: () => void
  refreshing: boolean
}

/**
 * 판단 상태에 맞는 안내와 행동.
 *
 * 여섯 갈래를 전부 적는다. `switch`가 아니라 `if`로 흘려두면 새 상태가 늘었을 때
 * 아무 화면도 안 나오고 조용히 빈 자리가 생긴다.
 */
function JudgmentSection({
  judgment,
  locked,
  waitedTooLong,
  onRefresh,
  refreshing,
}: JudgmentSectionProps) {
  const recheck = { label: '상태 다시 확인', onClick: onRefresh, disabled: refreshing }

  switch (judgment.status) {
    /*
      오래 기다린 화면을 따로 둔다. 판단 도중 서버가 다시 뜨면 그 Case 는 계속
      `PENDING` 으로 남아(#40) 끝나지 않는데, 그때까지 "곧 됩니다" 라고 말하면
      사장님은 언제까지 기다려야 하는지 모른 채 화면만 붙들고 있게 된다.
    */
    case 'PENDING':
      return waitedTooLong ? (
        <NoticeCard
          tone="NEUTRAL"
          title="판단이 오래 걸리고 있어요."
          description="가게 정보는 그대로 있어요. 지금은 저희 쪽에서 더 확인이 필요한 상태라, 창을 닫으셨다가 나중에 다시 들러 주세요."
          action={recheck}
        />
      ) : (
        <NoticeCard
          tone="NEUTRAL"
          title="다음 할 일을 정하고 있어요."
          description="가게 정보는 저장됐어요. 시간이 조금 걸릴 수 있으니 나중에 다시 오셔도 됩니다."
          action={recheck}
        />
      )

    /*
      여기만 안내 카드가 아니라 할 일 카드가 주인공이라, 조회 버튼을 따로 둔다.
      `locked` 로 결과 제출이 막힌 상태에서 이 버튼까지 없으면 빠져나갈 길이 사라진다.
    */
    case 'DONE':
      return (
        <>
          <NextActionCard nextAction={judgment.nextAction} locked={locked} />
          <BlockerCard blocker={judgment.blocker} />

          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="min-h-13 w-full rounded-xl border border-gray-300 bg-white text-base font-bold text-gray-700 disabled:text-gray-400"
          >
            {recheck.label}
          </button>
        </>
      )

    /*
      답을 보내는 기능은 아직 없다. 저장되지 않는 입력칸을 두면 사장님이 적어 넣고
      사라지는 것을 겪는다 — 버튼이 없는 것보다 나쁘다.
    */
    case 'NEEDS_MORE_INFO':
      return (
        <>
          <FollowUpQuestionCard
            questions={judgment.questions}
            label="추가 확인 필요"
            title="이 내용을 알려주세요."
            description="다음 할 일을 정하려면 몇 가지 확인이 필요해요."
          />
          <NoticeCard
            tone="NEUTRAL"
            title="답변을 보내는 기능은 준비 중이에요."
            description="확인하신 내용은 곧 여기서 바로 알려주실 수 있게 하겠습니다."
            action={recheck}
          />
        </>
      )

    /*
      어긋난 항목이 응답에 없어서(#66) 무엇과 무엇이 다른지는 아직 못 보여준다.
      그래도 "불러오지 못했어요" 로 두는 것보다 낫다 — 사장님이 해야 할 일이 기다리는
      것인지 답하는 것인지가 달라진다.

      `/confirm` 으로 보내는 버튼은 달지 않는다. 어긋난 목록을 받아올 API 가 없어서
      그 화면이 빈손으로 열리고 `/` 로 튕긴다. `NEEDS_MORE_INFO` 에서 입력칸을 안 두는
      것과 같다 — 되지 않는 일을 버튼으로 약속하지 않는다.
    */
    case 'CONFLICT':
      return (
        <NoticeCard
          tone="NEUTRAL"
          title="확인이 필요한 내용이 있어요."
          description="알려주신 내용이 저장된 기록과 달라서, 어느 쪽이 맞는지 여쭤봐야 해요. 확인하시는 화면을 준비하고 있습니다."
          action={recheck}
        />
      )

    /*
      "잠시 후 다시" 라고 말하지 않는다. 실패한 Case 를 다시 판단하는 수단이 아직 없어서
      (#57) 몇 번을 눌러도 같은 실패가 돌아온다. 기다리면 된다고 하면 사장님은 언제
      되는지 모른 채 계속 들어와 보게 된다.

      TODO(기획): 실패 원인별 문구와 버튼은 #55 에서 정한다. 그때까지는 상태를 있는
      그대로 알리고, 되지 않는 일을 약속하지 않는다.
    */
    case 'FAILED':
      return (
        <NoticeCard
          tone="NEUTRAL"
          title="다음 할 일을 정하지 못했어요."
          description="가게 정보는 그대로 있어요. 다시 판단해 드리는 기능을 준비하고 있습니다."
          action={recheck}
        />
      )

    /*
      서버가 우리가 모르는 상태를 보냈거나 내용이 비어서 온 경우다. "정보가 부족합니다"로
      바꿔 보여주지 않는다 — 서버가 틀린 것을 사장님이 덜 적어낸 탓으로 읽게 된다.
    */
    case 'UNRECOGNIZED':
      return (
        <NoticeCard
          tone="NEUTRAL"
          title="판단 내용을 불러오지 못했어요."
          description="가게 정보는 그대로 있어요. 잠시 후 다시 확인해 주세요."
          action={recheck}
        />
      )

    default: {
      // 상태가 늘면 여기서 컴파일이 막힌다
      const unhandled: never = judgment
      return unhandled
    }
  }
}
