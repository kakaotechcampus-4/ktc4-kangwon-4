import type { Fact } from '../types/view'

interface InsufficientInfoCardProps {
  /**
   * 물어볼 항목. 서버가 정한 순서 그대로 받는다.
   * `UNKNOWN`만 넘긴다 — `IN_PROGRESS`는 이미 확인하러 간 것이라 여기 넣으면
   * "알려주세요"와 "지금 확인 중"이 같은 화면에서 다른 말을 하게 된다.
   */
  missing: Fact[]
}

/**
 * 예외 — 정보가 부족해 다음 할 일을 정할 수 없는 상태.
 *
 * Next Action 자리를 대신하지만 어두운 배경을 쓰지 않는다.
 * 강하게 강조하는 것은 실제로 할 일이 있을 때뿐이다.
 *
 * TODO(BE 확인): 이 카드가 뜨는 조건(`nextAction === null`)이 실제로 어떤 서버 상태인지
 * 확정되지 않았다. `types/view.ts`의 `CurrentCaseView` 주석 참고.
 * 오류 상태라면 이 화면은 `/results`의 `NEEDS_MORE_INFO` 자리로 옮기고,
 * 여기에는 재시도 안내를 두는 것이 맞다.
 */
export function InsufficientInfoCard({ missing }: InsufficientInfoCardProps) {
  return (
    <section className="rounded-2xl border border-gray-300 bg-white p-5">
      <h2 className="text-sm font-bold tracking-wide text-gray-500">아직 정할 수 없음</h2>

      <p className="mt-3 text-lg font-bold text-gray-900">
        다음 할 일을 정하기에 정보가 부족합니다.
      </p>
      <p className="mt-2 text-base leading-relaxed text-gray-600">
        아래 항목만 알려주시면 바로 이어서 안내해 드릴 수 있어요.
      </p>

      {missing.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2 border-t border-gray-100 pt-3.5">
          {missing.map((fact) => (
            <li key={fact.key} className="text-base text-gray-700">
              · {fact.label}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
