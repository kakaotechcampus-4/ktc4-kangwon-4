/**
 * 예외 — 막고 있는 것이 없는 상태.
 *
 * 여기서 "확인이 필요합니다" 같은 회피 문구를 띄우면 안 된다.
 * 정보가 다 모였는데 아무것도 안 알려주는 화면이 되어버린다.
 * 아래 Next Action 카드가 이어서 다음 할 일을 보여준다.
 */
export function NoBlockerCard() {
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-emerald-600" />
        <h2 className="text-sm font-bold text-emerald-800">막혀 있는 것 없음</h2>
      </div>

      <p className="mt-2 text-base font-bold text-gray-900">
        지금 막고 있는 것이 없습니다.
      </p>
      <p className="mt-2 text-base leading-relaxed text-emerald-800">
        확인이 필요한 항목이 모두 정리됐어요. 아래 할 일부터 진행하시면 됩니다.
      </p>
    </section>
  )
}
