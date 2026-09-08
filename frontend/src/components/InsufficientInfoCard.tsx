import type { Fact } from '../types/view'

interface InsufficientInfoCardProps {
  /** 물어볼 항목. 서버가 정한 순서 그대로 받는다 */
  missing: Fact[]
}

/**
 * 예외 — 정보가 부족해 다음 할 일을 정할 수 없는 상태.
 *
 * Next Action 자리를 대신하지만 어두운 배경을 쓰지 않는다.
 * 강하게 강조하는 것은 실제로 할 일이 있을 때뿐이다.
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
