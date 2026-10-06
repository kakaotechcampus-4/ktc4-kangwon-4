import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { toCaseCreateRequest } from '../adapters/case'
import { AppShell } from '../components/AppShell'
import { CaseCreateForm } from '../components/CaseCreateForm'
import { NoticeCard } from '../components/NoticeCard'
import { PendingCard } from '../components/PendingCard'
import { ApiError, request, UnauthorizedError } from '../lib/api'
import { usesMockData } from '../lib/auth'
import type { CaseDraft } from '../types/view'

const EMPTY_DRAFT: CaseDraft = {
  businessType: '',
  franchiseStatus: null,
  leaseStatus: null,
  employeeCount: '',
  plannedClosureDate: '',
}

/**
 * 기다리는 동안 보여줄 문구.
 *
 * 서버는 **저장만 하고 바로 응답한다.** 판단은 뒤에서 따로 돌고, 그것을 기다리는 일은
 * `/case` 가 맡는다. 여기서 "절차를 살펴보는 중" 같은 말을 하면 하지도 않는 일을
 * 하는 척하게 되고, 금방 끝나는 저장을 괜히 길어 보이게 만든다.
 */
const PENDING_MESSAGES = ['가게 상황을 저장하고 있습니다']

type SubmitState = 'IDLE' | 'PENDING' | 'FAILED'

/**
 * Case 생성. 입력값을 들고 있고, 그리는 일은 폼에 맡긴다.
 *
 * 만들고 나면 `/case`로 바로 보낸다. 진입 분기를 한 번 더 거칠 이유가 없다 —
 * 방금 Case를 만들었으니 갈 곳이 이미 정해져 있다.
 *
 * `?mock=` 을 이어주지 않는 유일한 이동이다. 여기까지 오는 길이 `?mock=no-case`
 * 였는데 그대로 들고 가면 방금 만든 Case가 없는 척하게 된다.
 */
export function CaseCreatePage() {
  const navigate = useNavigate()
  const { search } = useLocation()
  const [draft, setDraft] = useState<CaseDraft>(EMPTY_DRAFT)
  const [submit, setSubmit] = useState<SubmitState>('IDLE')

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

  function handleSubmit() {
    const body = toCaseCreateRequest(draft)
    // 폼이 이미 막고 있다. 여기서 한 번 더 거르는 것은 잘못된 요청을 서버까지 보내지 않으려는 것
    if (body === null) return

    setSubmit('PENDING')

    /**
     * 가짜 세션은 서버에 없는 사용자라 401이 온다. `?mock=` 을 따라온 경우도 마찬가지로
     * 서버를 부르지 않는다 — 다른 화면이 전부 Mock 인데 여기서만 진짜 Case 를 만들면,
     * 회원당 하나라 지울 수도 없는 Case 가 남는다.
     */
    if (usesMockData(search)) {
      navigate('/case', { replace: true })
      return
    }

    request('/cases', { method: 'POST', body })
      .then(() => {
        if (!alive.current) return
        navigate('/case', { replace: true })
      })
      .catch((error: unknown) => {
        // 떠난 화면에서 이동을 실행하면, 사용자가 보고 있던 다른 화면에서 끌려 나온다
        if (!alive.current) return
        if (error instanceof UnauthorizedError) return navigate('/login', { replace: true })

        /**
         * 회원당 Case는 하나다. 두 탭에서 동시에 만들거나, 요청이 오래 걸리다 끊겨
         * 다시 눌렀을 때 온다. 이미 만들어졌다는 뜻이므로 실패가 아니라 도착이다.
         */
        if (error instanceof ApiError && error.status === 409) {
          return navigate('/case', { replace: true })
        }

        setSubmit('FAILED')
      })
  }

  return (
    <AppShell title="가게 상황 알려주기" subtitle="다섯 가지만 여쭤봅니다">
      {submit === 'PENDING' && <PendingCard messages={PENDING_MESSAGES} />}

      {submit === 'FAILED' && (
        <NoticeCard
          tone="NEUTRAL"
          title="저장하지 못했습니다."
          description="잠시 후 다시 시도해 주세요. 입력하신 내용은 그대로 있습니다."
        />
      )}

      {/*
        기다리는 동안에도 폼을 감추지 않고 잠근다. 적어 넣은 값이 눈앞에 남아 있어야
        무엇을 보내는 중인지 알 수 있고, 실패해서 돌아왔을 때 화면이 흔들리지 않는다.
      */}
      <CaseCreateForm
        value={draft}
        onChange={setDraft}
        onSubmit={handleSubmit}
        disabled={submit === 'PENDING'}
      />
    </AppShell>
  )
}
