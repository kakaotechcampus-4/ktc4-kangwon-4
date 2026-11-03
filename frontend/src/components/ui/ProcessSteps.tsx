import { IconCheckmarkCircleFill } from '@karrotmarket/react-monochrome-icon'

import { HammerLoader } from './HammerLoader'

/**
 * 단계 하나의 상태.
 *
 * - `done` 끝남
 * - `run`  지금 하는 중
 * - `wait` 아직 차례가 아님
 */
export type StepStatus = 'done' | 'run' | 'wait'

export interface Step {
  label: string
  status: StepStatus
}

const STATUS_TEXT: Record<StepStatus, string> = {
  done: '완료',
  run: '처리 중',
  wait: '대기',
}

const STATUS_COLOR: Record<StepStatus, string> = {
  done: 'text-fg-brand-contrast',
  run: 'text-fg-brand-contrast',
  wait: 'text-fg-disabled',
}

interface ProcessStepsProps {
  steps: Step[]
}

/**
 * 리본이 일하는 단계를 한 줄씩 보여준다 (시안 M05c).
 *
 * **단계는 부르는 쪽이 정한다.** 서버는 처리 단계를 내려주지 않으므로, 화면이 실제로 아는
 * 사건(보냈다·기다린다·결과가 왔다)에 맞춰 상태를 넘긴다. 시간이 지났다고 다음 줄로 넘기지
 * 않는다 — 실제 진행과 상관없이 넘어가면 끝나지 않은 일을 끝났다고 말하게 된다.
 *
 * 상태 글자("완료"·"처리 중"·"대기")를 화면에 그대로 쓴다. 색과 아이콘만으로 상태를 말하면
 * 색을 구분하기 어려운 사람과 화면 읽기 프로그램이 알 수 없다.
 *
 * 하는 중인 줄의 망치는 숨긴다. 같은 화면 위쪽의 큰 망치가 이미 "일하는 중"을 알린다.
 */
export function ProcessSteps({ steps }: ProcessStepsProps) {
  return (
    <ol className="flex flex-col">
      {steps.map((step, index) => (
        <li key={step.label} className="flex items-center gap-3 py-2.5">
          <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center">
            {step.status === 'done' && <IconCheckmarkCircleFill className="size-7 text-fg-brand" />}
            {step.status === 'run' && <HammerLoader size={24} />}
            {step.status === 'wait' && (
              <span className="grid size-6 place-items-center rounded-full text-13 font-bold text-fg-neutral-subtle ring-[1.5px] ring-stroke-neutral-weak ring-inset">
                {index + 1}
              </span>
            )}
          </span>
          <span className={`flex-1 text-17 ${step.status === 'wait' ? 'text-fg-neutral-subtle' : ''}`}>
            {step.label}
          </span>
          <span className={`text-14 font-bold whitespace-nowrap ${STATUS_COLOR[step.status]}`}>
            {STATUS_TEXT[step.status]}
          </span>
        </li>
      ))}
    </ol>
  )
}
