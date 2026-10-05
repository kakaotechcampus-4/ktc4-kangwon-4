interface FollowUpQuestionCardProps {
  /** 서버가 정한 순서 그대로 받는다 */
  questions: string[]
  /**
   * 어떤 맥락에서 묻는지에 따라 달라진다.
   *
   * `/results` 는 사장님이 방금 적어낸 말에 대해 되묻는 자리라 "말씀만으로는"이 맞지만,
   * `/case` 에서 첫 판단이 정보를 더 달라고 할 때는 사장님이 아직 아무 말도 한 적이 없다.
   * 같은 문구를 쓰면 하지도 않은 말을 했다고 하는 셈이다.
   */
  label?: string
  title?: string
  description?: string
}

/**
 * 다음 할 일을 정하기 전에 사용자에게 먼저 물어볼 것이 있는 상태(`NEEDS_MORE_INFO`).
 *
 * 여기 질문은 **서비스가 사장님에게** 묻는 것이다. 할 일 카드의 "이렇게 물어보세요"는
 * 사장님이 임대인에게 물을 말이라, 둘 다 "질문"이지만 방향이 반대다.

 */
export function FollowUpQuestionCard({
  questions,
  label = '조금만 더',
  title = '말씀만으로는 아직 정하기 어려워요.',
  description = '아래만 알려주시면 바로 이어서 안내해 드릴 수 있어요.',
}: FollowUpQuestionCardProps) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-5">
      <h2 className="text-sm font-bold tracking-wide text-gray-500">{label}</h2>

      <p className="mt-3 text-lg font-bold text-gray-900">{title}</p>
      <p className="mt-2 text-base leading-relaxed text-gray-600">{description}</p>

      <ul className="mt-4 flex flex-col gap-2 border-t border-gray-100 pt-3.5">
        {questions.map((question) => (
          <li key={question} className="flex gap-2 text-base leading-relaxed text-gray-700">
            {/* 가운뎃점은 장식이라 낭독기가 읽을 필요가 없다. 질문만 한 덩어리로 둔다 */}
            <span aria-hidden="true">·</span>
            <span>{question}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
