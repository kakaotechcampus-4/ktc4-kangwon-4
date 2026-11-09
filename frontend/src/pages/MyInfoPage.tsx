import { IconExclamationmarkCircleLine, IconStoreLine } from '@karrotmarket/react-monochrome-icon'
import { type ReactNode, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { HammerLoader } from '../components/ui/HammerLoader'
import { TopBar } from '../components/ui/TopBar'
import { useCase } from '../hooks/useCase'
import { logOutFromServer } from '../lib/api'
import { isMockSession, logOut } from '../lib/auth'
import { useDiagnosisStore } from '../stores/useDiagnosisStore'
import type { Fact } from '../types/view'

/**
 * 내 정보. 탭 화면 머리말의 사람 버튼으로 들어온다.
 *
 * 전에는 이 자리가 알림이었다. 알림 API가 없어 빈 화면만 있었고, 화면 쪽 알림(#311)은
 * 써 보니 흐름에 보탬이 적어 접었다. 대신 비어 있던 두 가지 — 저장된 가게 정보를 다시 볼 곳과
 * 로그아웃 — 를 여기 둔다.
 *
 * **가게 정보는 읽기만 한다.** 여기서 고치게 하면 서버 판단을 거치지 않고 기록이 바뀐다.
 * 바뀐 게 있으면 할 일 결과로 알려 주게 안내한다 — 서버가 기존 기록과 비교해 반영하거나 되묻는다.
 *
 * Case가 없을 때도 진단으로 바로 보내지 않고 이 화면에서 안내한다. 로그아웃은 Case가 없는
 * 사람도 할 수 있어야 한다.
 */
export function MyInfoPage() {
  const { search } = useLocation()
  const navigate = useNavigate()
  const { query, refresh, refreshing } = useCase()
  const [loggingOut, setLoggingOut] = useState(false)

  /**
   * 서버에 알린 뒤 브라우저 쪽을 지우고 로그인으로 간다. 확인 창은 두지 않는다 — 다시 로그인하면
   * 그대로 돌아오는 동작이다.
   *
   * **서버가 실패해도 화면에서는 로그아웃시킨다.** 누른 사장님이 그대로 남아 있으면 안 된다.
   * 가짜 세션만 서버를 부르지 않는다 — 서버가 모르는 토큰이다. `?mock=` 으로 화면만 Mock 을 보고
   * 있어도 로그인은 진짜일 수 있어서, 그때는 서버의 Refresh 토큰도 지워야 한다.
   *
   * 진단 답(`useDiagnosisStore`)도 지운다. 같은 탭에 남아 있으면 다음에 로그인한 계정이
   * 앞 사람의 대출 · 직원 답을 이어받는다. `replace` 로 가서 뒤로 가기로 이 화면에 돌아오지 않는다.
   */
  async function handleLogOut() {
    setLoggingOut(true)
    if (!isMockSession()) {
      try {
        await logOutFromServer()
      } catch {
        // 서버가 못 받았어도 화면에서는 로그아웃시킨다(위 설명)
      }
    }
    logOut()
    useDiagnosisStore.getState().reset()
    navigate('/login', { replace: true })
  }

  // 주 버튼이 아니라 글자 버튼이다. 이 화면에서 자주 누를 것이 아니고, 넓은 버튼으로 두면
  // 가게 정보보다 먼저 눈에 띈다. 누르는 영역은 높이 44px 로 둔다
  const logOutButton = (
    <button
      type="button"
      onClick={handleLogOut}
      disabled={loggingOut}
      className="-mx-1 min-h-11 cursor-pointer rounded-md px-1 text-15 text-fg-neutral-muted underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-stroke-brand-solid active:bg-bg-transparent-pressed disabled:cursor-not-allowed disabled:text-fg-disabled"
    >
      로그아웃
    </button>
  )

  if (query.status === 'LOADING') {
    return (
      <MyInfoFrame>
        <div className="flex flex-1 items-center justify-center">
          <HammerLoader size={48} label="내 정보를 불러오는 중" />
        </div>
      </MyInfoFrame>
    )
  }

  if (query.status === 'LOAD_FAILED') {
    return (
      <MyInfoFrame>
        <EmptyState
          icon={<IconExclamationmarkCircleLine size={32} />}
          title="가게 정보를 불러오지 못했어요"
          description="연결 상태를 확인하고 다시 불러와 주세요."
          action={
            <Button onClick={refresh} disabled={refreshing}>
              다시 불러오기
            </Button>
          }
        />
        <div className="flex justify-end px-4 pb-8">{logOutButton}</div>
      </MyInfoFrame>
    )
  }

  if (query.status === 'EMPTY') {
    return (
      <MyInfoFrame>
        <EmptyState
          icon={<IconStoreLine size={32} />}
          title="아직 등록된 가게가 없어요"
          description="상황 진단을 마치면 여기서 가게 정보를 볼 수 있어요."
          action={<Button onClick={() => navigate({ pathname: '/cases/new', search })}>상황 진단하기</Button>}
        />
        <div className="flex justify-end px-4 pb-8">{logOutButton}</div>
      </MyInfoFrame>
    )
  }

  return (
    <MyInfoFrame>
      <main className="flex flex-col gap-3 px-4 pt-2 pb-8">
        <section aria-labelledby="my-store">
          <h2 id="my-store" className="text-20 font-bold">
            내 가게
          </h2>
          <p className="mt-1.5 text-15 text-pretty text-fg-neutral-muted">
            리본이 판단할 때 쓰는 정보예요. 바뀐 게 있으면 할 일 결과를 알려 주실 때 말씀해 주세요.
          </p>
          <dl className="mt-3 flex flex-col">
            {query.view.facts.map((fact) => (
              <FactRow key={fact.key} fact={fact} />
            ))}
          </dl>
        </section>
        <div className="mt-4 flex justify-end">{logOutButton}</div>
      </main>
    </MyInfoFrame>
  )
}

/**
 * 가게 정보 한 줄. 서버가 확정하지 않은 값은 빈칸으로 숨기지 않고 "확인 필요"로 흐리게 둔다
 * (FE 규칙 6) — 비어 있으면 사장님은 답한 것이 사라진 줄 안다.
 */
function FactRow({ fact }: { fact: Fact }) {
  const known = fact.status === 'CONFIRMED' && fact.value !== undefined

  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-stroke-neutral-muted py-3.5 last:border-b-0">
      <dt className="shrink-0 text-15 text-fg-neutral-muted">{fact.label}</dt>
      <dd className={`text-right text-15 ${known ? 'font-bold' : 'text-fg-neutral-subtle'}`}>
        {known ? fact.value : '확인 필요'}
      </dd>
    </div>
  )
}

/** 탭 없는 화면의 틀. 뒤로 버튼과 제목을 둔다 */
function MyInfoFrame({ children }: { children: ReactNode }) {
  return (
    <div className="screen-frame mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar title="내 정보" />
      {children}
    </div>
  )
}
