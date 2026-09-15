import type { FactChange } from '../types/view'

interface ChangeListProps {
  /** 서버가 정한 순서 그대로 받는다. 빈 배열은 호출부가 처리한다 */
  changes: FactChange[]
}

/**
 * 방금 반영된 변경 목록.
 *
 * ⑤에서 가장 먼저 읽혀야 하는 정보다. 무엇이 바뀌었는지 모른 채 새 할 일만 보면
 * "왜 갑자기 다른 얘기를 하지"가 된다.
 *
 * 값이 서버에서 이미 확정된 상태로 오므로 프론트는 비교하지 않는다.
 */
export function ChangeList({ changes }: ChangeListProps) {
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
      <h2 className="text-sm font-bold tracking-wide text-emerald-700">방금 반영된 내용</h2>

      <ul className="mt-3 flex flex-col gap-3">
        {changes.map((change) => (
          <li key={change.key}>
            <p className="text-sm text-emerald-800">{change.label}</p>
            <p className="mt-0.5 text-base leading-relaxed">
              <span className="text-gray-500">{change.previousValue ?? '미확인'}</span>
              <span aria-hidden="true" className="mx-1.5 text-gray-400">
                →
              </span>
              <span className="sr-only">에서</span>
              <span className="font-bold text-gray-900">{change.newValue}</span>
              <span className="sr-only">(으)로 바뀜</span>
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}
