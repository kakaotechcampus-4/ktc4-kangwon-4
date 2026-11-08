import { describe, expect, it } from 'vitest'

import type { RoadmapResponse, RoadmapTaskResponse } from '../types/api'
import { toRoadmapView } from './roadmap'

const task = (overrides: Partial<RoadmapTaskResponse> = {}): RoadmapTaskResponse => ({
  task_id: 'dispose_stock',
  title: '재고·장비 처분',
  kind: 'CHECKLIST',
  status: 'NOT_STARTED',
  guidance: null,
  ...overrides,
})

const roadmap = (overrides: Partial<RoadmapResponse> = {}): RoadmapResponse => ({
  supported: true,
  unsupported_reason: null,
  current_stage: 3,
  stages: [{ stage: 3, title: '영업 마무리·폐업 신고', tasks: [task()] }],
  ...overrides,
})

describe('toRoadmapView', () => {
  it('단계·할 일·지금 단계를 서버가 준 그대로 옮긴다', () => {
    const view = toRoadmapView(
      roadmap({
        stages: [
          {
            stage: 3,
            title: '영업 마무리·폐업 신고',
            tasks: [task({ guidance: '렌탈 기기는 반납 날짜를 먼저 정해요.' })],
          },
        ],
      }),
    )

    expect(view).toEqual({
      supported: true,
      unsupportedReason: null,
      currentStage: 3,
      stages: [
        {
          stage: 3,
          title: '영업 마무리·폐업 신고',
          tasks: [
            {
              id: 'dispose_stock',
              title: '재고·장비 처분',
              kind: 'CHECKLIST',
              status: 'NOT_STARTED',
              guidance: '렌탈 기기는 반납 날짜를 먼저 정해요.',
            },
          ],
        },
      ],
    })
  })

  /** 설명이 없는 할 일에 빈 설명 줄을 그리지 않게 칸을 아예 뺀다 */
  it('설명이 없으면 설명 칸을 두지 않는다', () => {
    const view = toRoadmapView(roadmap())

    expect(view?.stages[0].tasks[0]).not.toHaveProperty('guidance')
  })

  /** 폐업 정리를 마쳤으면 서버가 지금 단계를 주지 않는다(#179). 화면은 어느 단계도 강조하지 않는다 */
  it('지금 단계가 없으면 null 로 둔다', () => {
    expect(toRoadmapView(roadmap({ current_stage: null }))?.currentStage).toBeNull()
  })

  it('미지원 업종이면 서버 안내 문구와 빈 단계를 그대로 둔다', () => {
    const view = toRoadmapView(
      roadmap({ supported: false, unsupported_reason: '프랜차이즈 카페는 아직 안내하지 않아요.', current_stage: null, stages: [] }),
    )

    expect(view).toEqual({
      supported: false,
      unsupportedReason: '프랜차이즈 카페는 아직 안내하지 않아요.',
      currentStage: null,
      stages: [],
    })
  })

  /** "해당 없음"을 "시작 전"처럼 비슷한 상태로 바꿔 그리면 할 필요 없는 일을 내민다. 그 줄만 뺀다 */
  it('모르는 상태·종류의 할 일은 그 줄만 빼고 나머지는 그린다', () => {
    const view = toRoadmapView(
      roadmap({
        stages: [
          {
            stage: 3,
            title: '영업 마무리·폐업 신고',
            tasks: [
              task(),
              task({ task_id: 'terminate_contracts', status: 'WAITING' as RoadmapTaskResponse['status'] }),
              task({ task_id: 'employee_payments', kind: 'MEETING' as RoadmapTaskResponse['kind'] }),
            ],
          },
        ],
      }),
    )

    expect(view?.stages[0].tasks.map((item) => item.id)).toEqual(['dispose_stock'])
  })

  it('단계 목록이 없거나 지원 여부를 모르면 읽지 못한 것으로 본다', () => {
    expect(toRoadmapView(null)).toBeNull()
    expect(toRoadmapView({ ...roadmap(), stages: undefined } as unknown as RoadmapResponse)).toBeNull()
    expect(toRoadmapView({ ...roadmap(), supported: undefined } as unknown as RoadmapResponse)).toBeNull()
  })
})
