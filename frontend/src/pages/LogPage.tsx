import { IconClockLine } from '@karrotmarket/react-monochrome-icon'

import { EmptyState } from '../components/ui/EmptyState'

/**
 * 작업 기록. 리본과 사장님이 한 일이 차례로 남는 곳.
 *
 * TODO(API): 기록 API가 없어 빈 상태만 보여준다. 가짜 기록으로 채우지 않는다.
 */
export function LogPage() {
  return (
    <EmptyState
      icon={<IconClockLine size={32} />}
      title="아직 남은 기록이 없어요"
      description={'리본이 한 일과 사장님이 한 일이\n여기에 차례로 남아요'}
    />
  )
}
