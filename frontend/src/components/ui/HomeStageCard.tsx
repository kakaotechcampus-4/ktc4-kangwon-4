import { IconChevronRightLine } from '@karrotmarket/react-monochrome-icon'
import { Link, useLocation } from 'react-router'

/** 시안의 폐업 단계 짧은 이름. 단계 번호 1~5 순서다 */
const STAGE_LABELS = ['준비', '철거', '신고', '정산', '세금']

interface HomeStageCardProps {
  /** 서버가 정한 지금 단계. 없으면 막대를 비우고 다섯 이름을 모두 흐리게 둔다 */
  stage?: { number: number; title: string } | null
}

/**
 * 홈 아래쪽의 폐업 단계 카드. 누르면 로드맵(폐업 전체 순서)으로 간다(시안과 같음).
 *
 * "지금은 원상복구·철거 단계"처럼 지금 단계를 굵게 칠한다. 지금 단계는 서버가 정한다 — 화면이
 * 할 일 상태로 짐작해 칠하면 서버가 정하지 않은 진행 상황을 확정된 것처럼 보여주게 된다.
 * 서버가 아직 주지 않으면 막대를 비워 둔다.
 *
 * 막대는 시안처럼 지금 단계의 가운데까지 채운다(`(단계 - 0.5) / 5`). 단계를 다 마쳤다는 뜻이 아니라
 * 그 단계에 와 있다는 뜻이다.
 */
export function HomeStageCard({ stage = null }: HomeStageCardProps) {
  const { search } = useLocation()
  const current = stage && stage.number >= 1 && stage.number <= STAGE_LABELS.length ? stage : null

  return (
    <Link
      to={{ pathname: '/roadmap', search }}
      className="flex shrink-0 flex-col gap-3 rounded-2xl bg-bg-layer-default px-5 py-4.5 shadow-card active:bg-bg-layer-default-pressed"
    >
      <span className="flex items-center gap-1">
        <span className="flex-1 text-17 font-bold">
          {current ? (
            <>
              지금은 <span className="text-fg-brand-contrast">{current.title}</span> 단계
            </>
          ) : (
            '폐업 단계'
          )}
        </span>
        <IconChevronRightLine size={20} aria-hidden="true" className="text-fg-neutral-subtle" />
      </span>
      <span aria-hidden="true" className="h-1.5 overflow-hidden rounded-full bg-bg-neutral-weak">
        {current && (
          <span
            className="block h-full rounded-full bg-bg-brand-solid"
            style={{ width: `${((current.number - 0.5) / STAGE_LABELS.length) * 100}%` }}
          />
        )}
      </span>
      <ol className="grid grid-cols-5">
        {STAGE_LABELS.map((label, index) => {
          const number = index + 1
          const tone = !current
            ? 'font-medium text-fg-neutral-subtle'
            : number === current.number
              ? 'font-bold text-fg-brand-contrast'
              : number < current.number
                ? 'font-medium text-fg-neutral-muted'
                : 'font-medium text-fg-neutral-subtle'
          return (
            <li key={label} className={`text-center text-13 ${tone}`}>
              {label}
            </li>
          )
        })}
      </ol>
      {!current && <span className="text-14 text-fg-neutral-muted">단계 정보는 곧 보여드릴게요</span>}
    </Link>
  )
}
