import type { Blocker } from '../types/view'

interface BlockerCardProps {
  blocker: Blocker
}

/**
 * 왜 막혔는지 설명하는 보조 정보. Next Action보다 약하게 보여야 한다.
 */
export function BlockerCard({ blocker }: BlockerCardProps) {
  return (
    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-amber-600" />
        <h2 className="text-sm font-bold text-amber-800">막혀 있는 것</h2>
      </div>

      <p className="mt-2 text-base font-bold text-gray-900">{blocker.title}</p>
      {blocker.description && (
        <p className="mt-2 text-base leading-relaxed text-amber-800">{blocker.description}</p>
      )}
    </section>
  )
}
