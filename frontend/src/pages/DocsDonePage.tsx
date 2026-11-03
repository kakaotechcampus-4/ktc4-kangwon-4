import { IconBoxFlapLine, IconCheckmarkCircleFill, IconXmarkLine } from '@karrotmarket/react-monochrome-icon'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { Button } from '../components/ui/Button'
import { InfoBox } from '../components/ui/InfoBox'
import { useDocuments } from '../hooks/useDocuments'

/**
 * 정산 제출 파일 (시안 M07). 점검을 통과한 서류를 ZIP 한 개로 받는다.
 *
 * 서버는 점검이 `COMPLETE` 일 때만 파일을 준다(그 밖에는 422, #159). 그래서 이 화면도 통과한
 * 점검이 있을 때만 그리고, 아니면 점검 화면으로 돌려보낸다 — 받기 버튼을 눌러야 실패를 알게 하지
 * 않는다.
 *
 * 시안의 "정산 서류 6종을 확인했고", "다음 할 일: 가게 돌려주고 보증금 정산받기"는 넣지 않았다.
 * 몇 종인지는 서버가 정하고, 다음 할 일은 로드맵 판단이 정한다.
 *
 * TODO(#159): `GET /cases/documents/settlement.zip` 을 받아 내려받게 한다. 로그인 헤더를 실어야 해서
 * 링크로 열 수 없고, 받아 온 파일을 브라우저 내려받기로 넘긴다. 그 전에는 Mock 에서 버튼을 꺼 둔다 —
 * 가짜 파일을 진짜 제출 파일처럼 내려주면 안 된다.
 */
export function DocsDonePage() {
  const navigate = useNavigate()
  const { search } = useLocation()
  const { query } = useDocuments()

  if (query.status !== 'READY' || query.view.check?.status !== 'COMPLETE') {
    return <Navigate to={{ pathname: '/docs/check', search }} replace />
  }

  const count = query.view.documents.length

  return (
    <div className="mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <header className="flex h-14 shrink-0 items-center px-1">
        <button
          type="button"
          aria-label="닫기"
          onClick={() => navigate({ pathname: '/docs', search }, { replace: true })}
          className="grid size-12 cursor-pointer place-items-center rounded-lg text-fg-neutral active:bg-bg-transparent-pressed"
        >
          <IconXmarkLine size={24} aria-hidden="true" />
        </button>
      </header>

      <main className="flex flex-1 flex-col gap-6 px-4 pt-2 pb-8">
        <div className="flex flex-col items-center gap-4 pt-2 text-center">
          <IconCheckmarkCircleFill size={64} className="text-fg-brand" aria-hidden="true" />
          <div>
            <h1 className="text-26 font-bold">
              정산 제출 파일을
              <br />
              만들었어요
            </h1>
            <p className="mt-2 text-17 text-fg-neutral-muted">서류 점검을 마쳤고 남은 확인 사항은 없어요.</p>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-2xl p-4 ring-1 ring-stroke-neutral-weak ring-inset">
          <span
            aria-hidden="true"
            className="grid size-11 shrink-0 place-items-center rounded-xl bg-bg-brand-weak text-fg-brand"
          >
            <IconBoxFlapLine size={22} />
          </span>
          <div className="min-w-0">
            <p className="text-17 font-bold">정산 제출 파일 (ZIP)</p>
            <p className="mt-0.5 text-14 text-fg-neutral-muted">서류 {count}개 · 점검 결과</p>
          </div>
        </div>

        <InfoBox>리본은 대신 제출하지 않아요. 이 파일로 소상공인24에서 사장님이 직접 제출해요.</InfoBox>

        <div className="mt-auto flex gap-2">
          <Button variant="outline" className="flex-1" onClick={() => navigate({ pathname: '/case', search })}>
            홈으로
          </Button>
          <Button className="flex-2" disabled>
            파일 받기
          </Button>
        </div>
      </main>
    </div>
  )
}
