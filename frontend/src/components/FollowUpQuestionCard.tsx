interface FollowUpQuestionCardProps {
  /** 서버가 정한 순서 그대로 받는다 */
  questions: string[]
}

/**
 * 입력만으로 상태를 확정할 수 없어 되묻는 상태(`NEEDS_MORE_INFO`).
 *
 * 입력 폼 아래에 붙어서 "이것만 더 말씀해 주세요"로 읽히게 한다. 폼을 대체하지
 * 않는 이유는, 사용자가 답을 같은 칸에 이어서 적으면 되기 때문이다.
 *
 * ② `InsufficientInfoCard`와 다르다. 그쪽은 "알려주셔야 할 항목"이고
 * 여기는 "방금 하신 말씀에 대해 더 여쭙는 것"이다.
 */
export function FollowUpQuestionCard({ questions }: FollowUpQuestionCardProps) {
  return (
    <section className="rounded-2xl border border-gray-300 bg-white p-5">
      <h2 className="text-sm font-bold tracking-wide text-gray-500">조금만 더</h2>

      <p className="mt-3 text-lg font-bold text-gray-900">
        말씀만으로는 아직 정하기 어려워요.
      </p>
      <p className="mt-2 text-base leading-relaxed text-gray-600">
        아래만 알려주시면 바로 이어서 안내해 드릴 수 있어요.
      </p>

      <ul className="mt-4 flex flex-col gap-2 border-t border-gray-100 pt-3.5">
        {questions.map((question) => (
          <li key={question} className="text-base leading-relaxed text-gray-700">
            · {question}
          </li>
        ))}
      </ul>
    </section>
  )
}
