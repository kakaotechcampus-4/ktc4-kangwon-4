import { useLocation } from 'react-router'

import { usesMockData } from '../lib/auth'
import { readMockKey } from '../lib/mockSwitch'
import { mockRoadmap, mockUnsupportedRoadmap } from '../mocks/roadmap'
import type { RoadmapView } from '../types/view'

/** 로드맵을 불러온 상태 */
export type RoadmapQuery =
  /** 로드맵 조회 API 가 아직 없다(현종님 작업 예정). 실서버에서만 */
  | { status: 'UNAVAILABLE' }
  | { status: 'READY'; view: RoadmapView }

/**
 * 로드맵(5단계 · 할 일 상태 · 현재 단계). 로드맵 화면과 홈 단계 카드가 같이 쓴다.
 *
 * TODO(로드맵 조회 API): BE 계획 1번(현종님)이 머지되면 그 응답을 어댑터로 바꿔 불러온다. 응답 모양이
 * 정해지기 전이라 `types/api.ts` 에는 넣지 않는다(FE 규칙 9). 그 전에는 실서버에서 `UNAVAILABLE` 이고,
 * Mock(`?mock=`)으로 볼 때만 예시 로드맵을, `?mock=roadmap-unsupported` 면 미지원 업종을 준다.
 */
export function useRoadmap(): RoadmapQuery {
  const { search } = useLocation()
  if (!usesMockData(search)) return { status: 'UNAVAILABLE' }
  return { status: 'READY', view: readMockKey(search) === 'roadmap-unsupported' ? mockUnsupportedRoadmap : mockRoadmap }
}
