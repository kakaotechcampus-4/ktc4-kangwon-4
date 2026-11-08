import { Button } from './Button'
import { HammerLoader } from './HammerLoader'
import { InfoBox } from './InfoBox'
import { ProcessSteps, type Step } from './ProcessSteps'

interface ProcessingScreenProps {
  /** 제목 (예: "답변을 정리하고 있어요") */
  title: string
  /** 망치의 읽기 이름. 화면 읽기 프로그램이 "무엇을 하는 중"인지 읽는다 */
  loaderLabel: string
  /** 단계 줄. 어느 줄이 끝났는지는 화면이 아는 사건으로 정한다(`toResultSteps`) */
  steps: Step[]
}

/**
 * 보낸 뒤 판단을 기다리는 화면 한 장 (시안 M05c 처리 중).
 *
 * 결과 입력(`/results`)과 충돌 확인(`/confirm`)이 같이 쓴다. 둘 다 접수 번호를 받고 같은
 * 판단을 기다리는 자리라 모양도 같아야 한다 — 어느 쪽에서 보냈는지에 따라 기다리는 화면이
 * 다르면 같은 일을 다른 일처럼 읽는다. 다른 것은 제목과 단계 줄 문구뿐이다.
 *
 * 망치는 위쪽에 둔다. 가운데로 내리면 시선이 아래로 떨어진다.
 *
 * 화면 틀(위쪽 뒤로 버튼)은 쓰는 쪽이 감싼다. 여기는 그 안의 본문만 그린다.
 */
export function ProcessingScreen({ title, loaderLabel, steps }: ProcessingScreenProps) {
  return (
    <main className="flex flex-col gap-6 px-4 pt-2 pb-8">
      <div className="flex flex-col items-center gap-5 pt-2 text-center">
        <HammerLoader size={72} label={loaderLabel} />
        <div>
          <h1 className="text-26 font-bold">{title}</h1>
          <p className="mt-2 text-17 text-fg-neutral-muted">사장님이 하실 일은 없어요.</p>
        </div>
      </div>
      <ProcessSteps steps={steps} />
      {/*
        판단은 길면 2분 넘게 걸린다. 떠나면 결과가 사라지는 줄 알면 그동안 화면에 묶인다.
        서버는 뒤에서 판단을 이어가고(#107), 다른 화면에 있으면 끝날 때 위쪽 띠로 알린다(`JudgmentWatcher`).
        홈(`/case`)은 스스로 기다려 결과를 보여준다.

        걸리는 시간은 적지 않는다. 잰 값(`docs/agent/monitoring-results.md`)은 로컬 실행 몇 건이라
        운영에서 얼마나 걸린다고 약속할 근거가 아니다 — 문서도 그렇게 쓰지 말라고 적었다
      */}
      <InfoBox>화면을 떠나셔도 계속 처리돼요. 다른 화면에 가 계셔도 끝나면 알려드려요.</InfoBox>
      {/* 시안대로 꺼진 버튼을 둔다. 누를 것이 없다는 것을 버튼 자리에서도 말한다 */}
      <Button disabled>처리 중이에요</Button>
    </main>
  )
}
