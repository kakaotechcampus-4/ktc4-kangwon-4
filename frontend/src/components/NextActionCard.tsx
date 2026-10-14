import { Link, useLocation } from 'react-router'

import type { NextAction } from '../types/view'

interface NextActionCardProps {
  /** 지금 화면이 들고 있는 판단이 최신인지 확신할 수 없을 때. 결과 제출을 막는다 */
  locked?: boolean
  nextAction: NextAction
}

/**
 * 화면에서 유일하게 강하게 강조하는 요소. 어두운 배경은 여기에만 쓴다.
 *
 * 주요 버튼은 이 카드 안에 둔다. 카드 밖에 또 두면 시선이 두 곳으로 나뉜다.
 */
export function NextActionCard({ nextAction, locked = false }: NextActionCardProps) {
  const { title, reason, questions } = nextAction
  // ?mock= 을 이어준다. 예외 화면을 링크만으로 따라갈 수 있어야 리뷰가 된다
  const { search } = useLocation()

  return (
    <section className="rounded-2xl bg-gray-900 p-5 text-white">
      <div className="flex items-center justify-between gap-2.5">
        <h2 className="text-sm font-bold tracking-wide text-gray-400">지금 할 일</h2>
        <span className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-xs font-bold">
          한 가지만
        </span>
      </div>

      <p className="mt-3 text-2xl font-bold">{title}</p>

      {/* 서버가 제목만 보내는 동안에는 비어 있다. 빈 문단을 그리면 여백만 남는다 */}
      {reason && <p className="mt-3 text-base leading-relaxed text-gray-300">{reason}</p>}

      {questions && questions.length > 0 && (
        <div className="mt-4 border-t border-white/15 pt-3.5">
          <h3 className="text-sm font-bold text-gray-400">이렇게 물어보시면 됩니다</h3>
          <ul className="mt-2 flex flex-col gap-2">
            {questions.map((question) => (
              <li key={question} className="flex gap-2 text-base leading-relaxed text-gray-200">
                {/* 가운뎃점은 장식이라 낭독기가 읽을 필요가 없다. 질문만 한 덩어리로 둔다 */}
                <span aria-hidden="true">·</span>
                <span>{question}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/*
        오래된 판단으로 결과를 보내면, 사장님은 이미 지난 할 일에 대해 답하게 된다.
        숨기지 않고 잠근다 — 사라지면 왜 사라졌는지 알 수 없다.
      */}
      {locked ? (
        <p className="mt-4 flex min-h-13 w-full items-center justify-center rounded-xl bg-white/15 px-4 text-center text-sm font-bold text-gray-300">
          최신 상태를 확인한 뒤에 알려주실 수 있어요
        </p>
      ) : (
        /* 어떤 할 일의 결과인지 다음 화면이 알아야 한다. 모르면 직전 할 일을 보여주게 된다 */
        <Link
          to={{ pathname: '/results', search }}
          state={nextAction}
          className="mt-4 flex min-h-13 w-full items-center justify-center rounded-xl bg-white text-base font-bold text-gray-900"
        >
          결과 알려주기
        </Link>
      )}
    </section>
  )
}
