import { IconClockLine, IconPerson2Fill, IconSparkle2Fill } from '@karrotmarket/react-monochrome-icon'
import { useLocation } from 'react-router'

import { ACTOR_LABEL } from '../adapters/logs'
import { EmptyState } from '../components/ui/EmptyState'
import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import { mockLogEntries } from '../mocks/logs'
import type { LogEntry } from '../types/view'

/**
 * 작업 기록 (시안 M08). 리본과 사장님이 한 일이 최근 것부터 쌓인다.
 *
 * 시안은 리본이 한 일을 반짝이, 사장님이 한 일을 사람 그림으로 가른다. 누가 했는지는
 * 줄 아래 `리본 · 10.17` 로도 적어, 그림을 못 보는 사람도 알 수 있게 한다.
 *
 * TODO(#143): 기록 조회 API가 머지되면 `toLogEntries` 로 불러와 그린다. 그 전에는 실서버에서
 * 빈 상태다. Mock(`?mock=`)으로 볼 때는 예시 기록을, `?mock=logs-empty` 면 빈 상태를 그린다.
 */
export function LogPage() {
  const { search } = useLocation()
  const entries: LogEntry[] = usesMockData(search) && readMockKey(search) !== 'logs-empty' ? mockLogEntries : []

  if (entries.length === 0) {
    return (
      <EmptyState
        icon={<IconClockLine size={32} />}
        title="아직 남은 기록이 없어요"
        description={'리본이 한 일과 사장님이 한 일이\n여기에 차례로 남아요'}
      />
    )
  }

  return (
    <div className="flex flex-col px-4 pt-2 pb-6">
      <p className="pb-2 text-15 text-fg-neutral-muted">최근 일부터 보여드려요.</p>
      <ul className="flex flex-col">
        {entries.map((entry) => (
          <li key={entry.key} className="flex items-center gap-3 py-3.5">
            <span
              aria-hidden="true"
              className={`grid size-10 shrink-0 place-items-center rounded-full ${
                entry.actor === 'RIBBON' ? 'bg-bg-brand-weak text-fg-brand' : 'bg-bg-neutral-weak text-fg-neutral-muted'
              }`}
            >
              {entry.actor === 'RIBBON' ? <IconSparkle2Fill size={20} /> : <IconPerson2Fill size={20} />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-17 font-medium">{entry.text}</span>
              <span className="mt-0.5 block text-14 text-fg-neutral-muted">
                {ACTOR_LABEL[entry.actor]} · {entry.date}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
