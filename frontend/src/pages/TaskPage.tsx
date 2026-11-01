import { IconExclamationmarkCircleLine } from '@karrotmarket/react-monochrome-icon'
import type { ReactNode } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { HammerLoader } from '../components/ui/HammerLoader'
import { TopBar } from '../components/ui/TopBar'
import { useCase } from '../hooks/useCase'

/**
 * 할 일 상세. 홈의 할 일 카드에서 들어온다.
 *
 * 사장님이 막히는 지점은 "임대인에게 연락해야지"가 아니라 "뭐라고 말하지"다. 그래서
 * 서버가 준 "이렇게 물어보세요"(`questions_to_ask`)를 번호를 붙여 크게 보여준다.
 *
 * 홈과 같은 `GET /cases`를 다시 묻는다. 홈에서 받은 값을 넘겨받으면 히스토리에 남아,
 * 이미 지난 할 일이 지금 할 일인 척 다시 뜬다.
 *
 * 시안에는 "계약서에서 찾아뒀어요" 같은 리본이 찾아둔 근거 상자가 있다. 서버가 근거를 주지
 * 않아 그 자리에 할 일의 이유(`reason`)를 둔다.
 * TODO(API): 할 일 근거가 오면 시안의 주황 상자로 보여준다.
 */
export function TaskPage() {
  const { search } = useLocation()
  const navigate = useNavigate()
  const { query, refresh, refreshing } = useCase()

  if (query.status === 'EMPTY') return <Navigate to={{ pathname: '/start', search }} replace />

  if (query.status === 'LOADING') {
    return (
      <TaskFrame>
        <div className="flex flex-1 items-center justify-center">
          <HammerLoader size={48} label="할 일을 불러오는 중" />
        </div>
      </TaskFrame>
    )
  }

  if (query.status === 'LOAD_FAILED') {
    return (
      <TaskFrame>
        <EmptyState
          icon={<IconExclamationmarkCircleLine size={32} />}
          title="할 일을 불러오지 못했어요"
          description="연결 상태를 확인하고 다시 불러와 주세요."
          action={
            <Button onClick={refresh} disabled={refreshing}>
              다시 불러오기
            </Button>
          }
        />
      </TaskFrame>
    )
  }

  // 할 일이 없는 상태(판단 중·추가 질문·실패 등)는 홈이 안내한다. 여기서 같은 안내를 또 만들지 않는다
  const { judgment } = query.view
  if (judgment.status !== 'DONE') return <Navigate to={{ pathname: '/case', search }} replace />

  const { title, reason, questions = [] } = judgment.nextAction
  const hasQuestions = questions.length > 0

  return (
    <TaskFrame>
      <main className="flex flex-col gap-6 px-4 pt-2 pb-8">
        <div>
          <h1 className="text-26 font-bold text-pretty">{title}</h1>
          {reason && <p className="mt-2 text-17 text-pretty text-fg-neutral-muted">{reason}</p>}
        </div>

        {hasQuestions && (
          <section className="flex flex-col gap-3">
            <h2 className="text-15 font-bold text-fg-neutral-muted">이렇게 물어보세요</h2>
            <ol className="flex flex-col gap-3">
              {questions.map((question, index) => (
                <li key={question} className="flex items-start gap-3.5 rounded-2xl bg-bg-neutral-weak p-4.5">
                  <span
                    aria-hidden="true"
                    className="grid size-7 shrink-0 place-items-center rounded-full bg-bg-neutral-solid text-15 font-bold text-fg-on-brand-solid"
                  >
                    {index + 1}
                  </span>
                  <span className="text-18 font-medium">{question}</span>
                </li>
              ))}
            </ol>
          </section>
        )}

        {/* 버튼은 내용 바로 아래에 둔다. 화면 맨 아래에 붙이면 내용이 짧을 때 가운데가 텅 빈다 */}
        <div className="flex flex-col gap-1">
          <Button onClick={() => navigate({ pathname: '/results', search })}>
            {hasQuestions ? '답을 들었어요' : '결과 알려주기'}
          </Button>
          {hasQuestions && (
            <button
              type="button"
              onClick={() => navigate({ pathname: '/case', search })}
              className="h-12 cursor-pointer rounded-14 text-16 font-bold text-fg-neutral-muted active:bg-bg-transparent-pressed"
            >
              아직 못 물어봤어요
            </button>
          )}
        </div>
      </main>
    </TaskFrame>
  )
}

/** 탭 없는 화면의 틀. 뒤로 버튼만 두고 제목은 화면 안의 할 일 제목이 맡는다 */
function TaskFrame({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar />
      {children}
    </div>
  )
}
