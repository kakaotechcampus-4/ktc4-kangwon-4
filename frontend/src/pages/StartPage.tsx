import { Link, Navigate, useLocation } from 'react-router'

import { AppShell } from '../components/AppShell'
import { hasCase } from '../lib/caseState'

/**
 * 시작 화면. Case가 없는 사용자만 본다.
 *
 * 한 번 보고 다시 안 볼 화면이라 짧게 둔다. 여기서 설명을 길게 하면 정작 읽어야 할
 * "지금 할 일"을 읽을 힘이 남지 않는다.
 *
 * Case가 있는 사용자는 진입 분기에서 `/case`로 바로 간다. 이 화면을 매번 거치게 하면
 * 할 일 하나를 보기까지 버튼을 한 번 더 눌러야 한다.
 *
 * 그래도 여기서 한 번 더 확인하는 이유는 뒤로가기 때문이다. Case를 만들고 `/case`에서
 * 뒤로 누르면 이 화면이 다시 나오는데, 그때 "시작하기"가 살아 있으면 두 번째 Case를
 * 만들려 든다 — 서버에서는 회원당 하나라 409로 막힌다.
 *
 * TODO(기획): 문구는 PM 확인이 필요하다. 지금 것은 제품 원칙(얽힌 조건을 대신 풀어준다,
 * 한 번에 하나만 보여준다)에서 뽑은 초안이다.
 */
export function StartPage() {
  // ?mock= 을 이어준다. 예외 화면을 링크만으로 따라갈 수 있어야 리뷰가 된다
  const { search } = useLocation()

  if (hasCase(search)) return <Navigate to={{ pathname: '/case', search }} replace />

  return (
    <AppShell title="폐업 준비 시작하기">
      <section className="rounded-2xl bg-white p-5">
        <p className="text-base leading-relaxed text-gray-700">
          임대차, 원상복구, 철거, 지원금, 세무 — 하나가 풀려야 다음이 정해지는 일들입니다.
        </p>
        <p className="mt-3 text-base leading-relaxed text-gray-700">
          가게 상황을 알려주시면 순서를 대신 맞춰 드리고,{' '}
          <strong className="font-bold text-gray-900">지금 할 일 하나씩만</strong> 알려드립니다.
        </p>
      </section>

      <section className="rounded-2xl bg-gray-900 p-5 text-white">
        <h2 className="text-sm font-bold tracking-wide text-gray-400">먼저 할 일</h2>
        <p className="mt-3 text-2xl font-bold">가게 상황을 알려주세요.</p>
        <p className="mt-3 text-base leading-relaxed text-gray-300">
          다섯 가지만 여쭤봅니다. 모르는 것은 비워두셔도 됩니다.
        </p>

        <Link
          to={{ pathname: '/cases/new', search }}
          className="mt-4 flex min-h-13 w-full items-center justify-center rounded-xl bg-white text-base font-bold text-gray-900"
        >
          시작하기
        </Link>
      </section>
    </AppShell>
  )
}
