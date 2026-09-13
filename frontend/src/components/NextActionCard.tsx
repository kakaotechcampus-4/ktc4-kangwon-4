import type { NextAction } from '../types/view'

interface NextActionCardProps {
  nextAction: NextAction
}

/**
 * 화면에서 유일하게 강하게 강조하는 요소. 어두운 배경은 여기에만 쓴다.
 *
 * 주요 버튼은 이 카드 안에 둔다. 카드 밖에 또 두면 시선이 두 곳으로 나뉜다.
 */
export function NextActionCard({ nextAction }: NextActionCardProps) {
  const { title, reason, questions } = nextAction

  return (
    <section className="rounded-2xl bg-gray-900 p-5 text-white">
      <div className="flex items-center justify-between gap-2.5">
        <h2 className="text-sm font-bold tracking-wide text-gray-400">지금 할 일</h2>
        <span className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-xs font-bold">
          한 가지만
        </span>
      </div>

      <p className="mt-3 text-2xl font-bold">{title}</p>
      <p className="mt-3 text-base leading-relaxed text-gray-300">{reason}</p>

      {questions && questions.length > 0 && (
        <div className="mt-4 border-t border-white/15 pt-3.5">
          <h3 className="text-sm font-bold text-gray-400">이렇게 물어보시면 됩니다</h3>
          <ul className="mt-2 flex flex-col gap-2">
            {questions.map((question) => (
              <li key={question} className="text-base leading-relaxed text-gray-200">
                · {question}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ③ 결과 입력 화면이 아직 없다. 라우트가 생길 때 연결한다 */}
      <button
        type="button"
        disabled
        className="mt-4 min-h-13 w-full rounded-xl bg-white text-base font-bold text-gray-900 disabled:cursor-not-allowed disabled:bg-white/40 disabled:text-gray-700"
      >
        결과 알려주기
      </button>
      <p className="mt-2 text-center text-sm text-gray-400">다음 단계 화면은 준비 중입니다</p>
    </section>
  )
}
