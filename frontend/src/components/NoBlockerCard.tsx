/**
 * 안내된 행동을 막는 조건이 없는 상태. 전체 Case의 정보 확인·완료와 구분.
 *
 * 다음 할 일이 있을 때만 렌더된다. 할 일을 정하지 못한 상태에서 "막힌 게 없다"고 하면
 * 긍정 신호로 오해된다.
 */
export function NoBlockerCard() {
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-emerald-600" />
        <h2 className="text-sm font-bold text-emerald-800">막혀 있는 것 없음</h2>
      </div>

      <p className="mt-2 text-base font-bold text-gray-900">
        지금 안내된 일을 막는 조건 없음
      </p>
      <p className="mt-2 text-base leading-relaxed text-emerald-800">
        안내된 할 일 진행 후 결과 입력
      </p>
    </section>
  )
}
