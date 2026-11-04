import { IconChevronRightLine } from '@karrotmarket/react-monochrome-icon'
import { Link, useLocation } from 'react-router'

/** 시안의 폐업 단계 짧은 이름. 단계 번호 1~5 순서다 */
const STAGE_LABELS = ['준비', '철거', '신고', '정산', '세금']

interface HomeStageCardProps {
  /** 서버가 정한 지금 단계. 없으면 막대를 비우고 다섯 이름을 모두 흐리게 둔다 */
  stage?: { number: number; title: string } | null
  /** 폐업 정리를 모두 마쳤다(서버 `case_status` `COMPLETED`). 막대를 다 채우고 다섯 이름을 지난 단계로 칠한다 */
  completed?: boolean
}

/**
 * 홈 아래쪽의 폐업 단계 카드. 누르면 로드맵(폐업 전체 순서)으로 간다(시안과 같음).
 *
 * "지금은 원상복구·철거 단계"처럼 지금 단계를 굵게 칠한다. 지금 단계는 서버가 정한다 — 화면이
 * 할 일 상태로 짐작해 칠하면 서버가 정하지 않은 진행 상황을 확정된 것처럼 보여주게 된다.
 * 서버가 아직 주지 않으면 막대를 비워 둔다.
 *
 * 막대는 시안처럼 지금 단계의 가운데까지 채운다(`(단계 - 0.5) / 5`). 단계를 다 마쳤다는 뜻이 아니라
 * 그 단계에 와 있다는 뜻이다. 폐업 정리를 마쳤으면 끝까지 채운다(시안 `closed`).
 *
 * 마친 뒤의 제목은 "폐업 단계" 그대로다. 시안은 "지금은 세금·마무리 단계"인데, 단계 이름은 로드맵이
 * 주는 값이라 FE 가 마지막 단계 이름을 적어 두지 않는다.
 * TODO(로드맵 조회 API): 단계 이름이 오면 마친 뒤의 제목을 다시 정한다.
 */
export function HomeStageCard({ stage = null, completed = false }: HomeStageCardProps) {
  const { search } = useLocation()
  const current = !completed && stage && stage.number >= 1 && stage.number <= STAGE_LABELS.length ? stage : null
  const fill = completed ? 100 : current ? ((current.number - 0.5) / STAGE_LABELS.length) * 100 : null

  return (
    <Link
      to={{ pathname: '/roadmap', search }}
      viewTransition
      className="press-scale flex shrink-0 flex-col gap-3 rounded-2xl bg-bg-layer-default px-5 py-4.5 shadow-card active:bg-bg-layer-default-pressed"
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
        {fill !== null && <span className="block h-full rounded-full bg-bg-brand-solid" style={{ width: `${fill}%` }} />}
      </span>
      <ol className="grid grid-cols-5">
        {STAGE_LABELS.map((label, index) => {
          const number = index + 1
          const tone = completed
            ? 'font-medium text-fg-neutral-muted'
            : !current
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
      {fill === null && <span className="text-14 text-fg-neutral-muted">단계 정보는 곧 보여드릴게요</span>}
    </Link>
  )
}
