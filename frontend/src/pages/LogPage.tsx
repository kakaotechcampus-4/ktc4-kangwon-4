import { IconClockLine, IconPerson2Fill, IconSparkle2Fill } from '@karrotmarket/react-monochrome-icon'

import { ACTOR_LABEL } from '../adapters/logs'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { HammerLoader } from '../components/ui/HammerLoader'
import { useLogs } from '../hooks/useLogs'
import { useEntersForward } from '../lib/viewTransition'

/**
 * 작업 기록 (시안 M08). 리본과 사장님이 한 일이 최근 것부터 쌓인다.
 *
 * 시안은 리본이 한 일을 반짝이, 사장님이 한 일을 사람 그림으로 가른다. 누가 했는지는
 * 줄 아래 `리본 · 10.17` 로도 적어, 그림을 못 보는 사람도 알 수 있게 한다.
 */
export function LogPage() {
  const { query, reload } = useLogs()
  const rise = useEntersForward()

  if (query.status === 'LOADING') {
    return (
      <div className="flex flex-1 items-center justify-center">
        <HammerLoader size={48} label="기록을 불러오는 중" />
      </div>
    )
  }

  if (query.status === 'LOAD_FAILED') {
    return (
      <EmptyState
        icon={<IconClockLine size={32} />}
        title="기록을 불러오지 못했어요"
        description="연결 상태를 확인하고 다시 불러와 주세요"
        action={<Button onClick={reload}>다시 불러오기</Button>}
      />
    )
  }

  if (query.entries.length === 0) {
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
      <ul className={`flex flex-col ${rise ? 'rise-children' : ''}`}>
        {query.entries.map((entry) => (
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
              {entry.detail && <span className="mt-0.5 block text-15 text-fg-neutral">{entry.detail}</span>}
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
