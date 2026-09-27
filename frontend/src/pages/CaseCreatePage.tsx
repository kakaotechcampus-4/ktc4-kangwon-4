import { useState } from 'react'
import { useNavigate } from 'react-router'

import { AppShell } from '../components/AppShell'
import { CaseCreateForm } from '../components/CaseCreateForm'
import { markCaseCreated } from '../lib/caseState'
import type { CaseDraft } from '../types/view'

const EMPTY_DRAFT: CaseDraft = {
  businessType: '',
  franchiseStatus: null,
  leaseStatus: null,
  employeeCount: '',
  plannedClosureDate: '',
}

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
  const [draft, setDraft] = useState<CaseDraft>(EMPTY_DRAFT)
  const [isSubmitting, setIsSubmitting] = useState(false)

  function handleSubmit() {
    setIsSubmitting(true)

    /**
     * TODO(API): `POST /cases`로 보낸다. 빈 문자열은 `null`로 바꿔 보낸다 —
     * 서버에서 `employee_count`와 `planned_closure_date`가 nullable이다.
     * 이미 Case가 있으면 409가 오는데, 그때도 `/case`로 보내면 된다.
     * 두 탭에서 동시에 만들거나 뒤로가기로 폼에 되돌아온 경우다.
     */
    markCaseCreated()
    navigate('/case', { replace: true })
  }

  return (
    <AppShell title="가게 상황 알려주기" subtitle="다섯 가지만 여쭤봅니다">
      <CaseCreateForm
        value={draft}
        onChange={setDraft}
        onSubmit={handleSubmit}
        disabled={isSubmitting}
      />
    </AppShell>
  )
}
