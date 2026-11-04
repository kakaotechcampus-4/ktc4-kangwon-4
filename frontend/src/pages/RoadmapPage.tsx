import { IconCheckmarkCircleFill, IconChevronDownLine } from '@karrotmarket/react-monochrome-icon'
import { AnimatePresence, m, useReducedMotion } from 'motion/react'
import { type ReactNode, useState } from 'react'
import { Link, useLocation } from 'react-router'

import { Badge } from '../components/ui/Badge'
import { InfoBox } from '../components/ui/InfoBox'
import { TopBar } from '../components/ui/TopBar'
import { useRoadmap } from '../hooks/useRoadmap'
import type { RoadmapStageView, RoadmapTaskStatus } from '../types/view'

/** 할 일 상태 → 배지. 색만으로 가르지 않고 글자를 늘 넣는다 */
const STATUS_BADGE: Record<RoadmapTaskStatus, { tone: 'brand' | 'critical' | 'neutral'; label: string }> = {
  IN_PROGRESS: { tone: 'brand', label: '진행 중' },
  NEEDS_CONFIRMATION: { tone: 'critical', label: '확인 필요' },
  COMPLETED: { tone: 'neutral', label: '완료' },
  NOT_STARTED: { tone: 'neutral', label: '예정' },
  NOT_APPLICABLE: { tone: 'neutral', label: '해당 없음' },
}

/**
 * 폐업 전체 순서 (시안 M03). 다섯 단계와 단계마다의 할 일을 서버가 준 상태로 보여준다.
 *
 * 어느 단계가 지금인지는 서버가 정한다. 시안처럼 지금 단계만 펼쳐 두되, 다른 단계도 눌러서 펼칠 수
 * 있게 했다 — 시안은 펼칠 수 없어 앞으로 할 일을 미리 볼 길이 없다.
 *
 * 미지원 업종이면 서버가 쓴 안내 문구만 보여준다(#132 `unsupported_reason`). 홈의 할 일 카드는
 * 이와 상관없이 실제 판단을 따른다.
 *
 * 할 일을 누르면 여는 흐름은 다음 커밋에서 붙인다.
 */
export function RoadmapPage() {
  const query = useRoadmap()

  if (query.status === 'UNAVAILABLE') {
    return (
      <RoadmapFrame>
        <InfoBox title="폐업 전체 순서는 준비 중이에요.">
          할 일 순서를 보여주는 기능이 열리면 여기서 다섯 단계를 한눈에 볼 수 있어요.
        </InfoBox>
      </RoadmapFrame>
    )
  }

  const { supported, unsupportedReason, currentStage, stages } = query.view

  if (!supported) {
    return (
      <RoadmapFrame>
        <InfoBox title="이 가게는 아직 폐업 순서를 안내하지 않아요.">{unsupportedReason}</InfoBox>
      </RoadmapFrame>
    )
  }

  return (
    <RoadmapFrame>
      <ol className="flex flex-col">
        {stages.map((stage, index) => (
          <StageRow
            key={stage.stage}
            stage={stage}
            current={stage.stage === currentStage}
            last={index === stages.length - 1}
          />
        ))}
      </ol>
    </RoadmapFrame>
  )
}

/**
 * 단계 한 줄. 번호 동그라미와 세로선, 단계 이름, `완료 n/전체` 를 두고, 펼치면 할 일이 나온다.
 *
 * 전체 수에서 "해당 없음"은 뺀다. 이 가게가 할 필요 없는 일까지 세면 끝까지 해도 다 채워지지 않는다.
 * 해당하는 할 일을 모두 마친 단계는 번호 대신 체크를 그린다 — 서버가 준 상태를 세는 것이지 단계를
 * 짐작하는 것이 아니다.
 *
 * 펼치고 접을 때 할 일 목록의 높이가 늘고 준다(0.3초, 화면 이동과 같은 곡선). 접으면 움직임이 끝난 뒤
 * 목록을 지워서, 숨은 할 일에 키보드나 화면 낭독기가 닿지 않는다. 처음 그릴 때(지금 단계가 펼쳐진 채)는
 * 움직이지 않는다. "동작 줄이기"면 바로 펼치고 접는다.
 */
function StageRow({ stage, current, last }: { stage: RoadmapStageView; current: boolean; last: boolean }) {
  const { search } = useLocation()
  const [open, setOpen] = useState(current)
  const applicable = stage.tasks.filter((task) => task.status !== 'NOT_APPLICABLE')
  const done = applicable.filter((task) => task.status === 'COMPLETED').length
  const finished = applicable.length > 0 && done === applicable.length
  const listId = `stage-${stage.stage}-tasks`
  const reduceMotion = useReducedMotion()

  return (
    <li className="flex gap-3">
      <div aria-hidden="true" className="flex flex-col items-center">
        {finished ? (
          <IconCheckmarkCircleFill size={28} className="text-fg-brand" />
        ) : (
          <span
            className={`grid size-7 place-items-center rounded-full text-14 font-bold ${
              current ? 'bg-bg-brand-solid text-fg-on-brand-solid' : 'bg-bg-neutral-weak text-fg-neutral-muted'
            }`}
          >
            {stage.stage}
          </span>
        )}
        {!last && <span className="w-0.5 flex-1 bg-bg-neutral-weak" />}
      </div>

      <div className="min-w-0 flex-1 pb-5">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((value) => !value)}
          className="flex min-h-7 w-full cursor-pointer items-center gap-2 text-left"
        >
          <span className={`flex-1 text-17 ${current ? 'font-bold' : 'font-medium'}`}>
            {stage.title}
            {current && <span className="sr-only"> (지금 단계)</span>}
          </span>
          <span className="text-14 text-fg-neutral-muted tabular-nums">
            <span className="sr-only">완료 </span>
            {done}/{applicable.length}
          </span>
          <IconChevronDownLine
            size={18}
            aria-hidden="true"
            className={`text-fg-neutral-subtle transition-transform duration-300 ease-out-soft motion-reduce:transition-none ${open ? 'rotate-180' : ''}`}
          />
        </button>

        <AnimatePresence initial={false}>
          {open && (
            // 높이를 줄이는 바깥 상자. 목록의 위 여백도 이 안에 두어야 다 접혔을 때 여백이 남지 않는다
            <m.div
              key="tasks"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={reduceMotion ? { duration: 0 } : { duration: 0.3, ease: [0.2, 0.8, 0.2, 1] }}
              className="overflow-hidden"
            >
              <ul id={listId} className="flex flex-col gap-1 pt-2">
                {stage.tasks.map((task) => {
                  const badge = STATUS_BADGE[task.status]
                  const rowStyle = `flex items-start gap-3 rounded-xl px-3 py-3 ${
                    task.status === 'IN_PROGRESS' ? 'bg-bg-brand-weak' : ''
                  }`
                  const content = (
                    <>
                      <span className="min-w-0 flex-1">
                        <span
                          className={`block text-16 ${
                            task.status === 'NOT_APPLICABLE' ? 'text-fg-neutral-subtle' : 'font-medium'
                          }`}
                        >
                          {task.title}
                        </span>
                        {task.guidance && (
                          <span className="mt-1 block text-14 text-fg-neutral-muted">{task.guidance}</span>
                        )}
                      </span>
                      <Badge tone={badge.tone}>{badge.label}</Badge>
                    </>
                  )
                  return (
                    <li key={task.id}>
                      {/* 해당 없는 할 일은 열 것이 없다. 눌리는데 아무 일도 없으면 고장으로 읽힌다 */}
                      {task.status === 'NOT_APPLICABLE' ? (
                        <div className={rowStyle}>{content}</div>
                      ) : (
                        <Link
                          to={{ pathname: `/roadmap/${task.id}`, search }}
                          viewTransition
                          className={`${rowStyle} press-scale active:bg-bg-transparent-pressed`}
                        >
                          {content}
                        </Link>
                      )}
                    </li>
                  )
                })}
              </ul>
            </m.div>
          )}
        </AnimatePresence>
      </div>
    </li>
  )
}

/** 탭 없는 화면의 틀. 뒤로 버튼과 화면 이름을 둔다 */
function RoadmapFrame({ children }: { children: ReactNode }) {
  return (
    <div className="screen-frame mx-auto flex min-h-dvh max-w-[402px] flex-col bg-bg-layer-default">
      <TopBar title="폐업 전체 순서" />
      <main className="flex flex-col gap-4 px-4 pt-2 pb-8">{children}</main>
    </div>
  )
}
