import type { Fact } from '../types/view'
import { StatusBadge } from './StatusBadge'

interface FactListProps {
  title: string
  /** 섹션 제목 우측 보조 텍스트 */
  caption?: string
  facts: Fact[]
}

export function FactList({ title, caption, facts }: FactListProps) {
  if (facts.length === 0) return null

  return (
    <section>
      <div className="flex items-baseline justify-between px-0.5 pb-2">
        <h2 className="text-base font-bold text-gray-700">{title}</h2>
        {caption && <span className="text-sm text-gray-500">{caption}</span>}
      </div>

      <ul className="divide-y divide-gray-100 overflow-hidden rounded-2xl border border-gray-200 bg-white">
        {facts.map((fact) => (
          <li key={fact.key} className="flex items-center gap-2.5 p-4">
            <span className="flex-1 text-base text-gray-700">{fact.label}</span>
            {fact.value && (
              <span className="text-base font-bold text-gray-900">{fact.value}</span>
            )}
            <StatusBadge status={fact.status} />
          </li>
        ))}
      </ul>
    </section>
  )
}
