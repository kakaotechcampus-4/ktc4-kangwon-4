import { IconDocumentTrayLine } from '@karrotmarket/react-monochrome-icon'

import { EmptyState } from '../components/ui/EmptyState'

/**
 * 서류함. 할 일을 하면서 올린 서류가 모이는 곳.
 *
 * TODO(API): 서류 목록 API가 없어 빈 상태만 보여준다. 가짜 서류로 채우지 않는다.
 * 올리기 시트와 목록은 7번 PR에서 만든다.
 */
export function DocsPage() {
  return (
    <EmptyState
      icon={<IconDocumentTrayLine size={32} />}
      title="아직 모인 서류가 없어요"
      description={'할 일을 하면서 올린 서류가\n여기에 모여요'}
    />
  )
}
