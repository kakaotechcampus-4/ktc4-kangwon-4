import type { RoadmapResponse } from '../types/api'
import type { RoadmapStageView, RoadmapTaskKind, RoadmapTaskStatus, RoadmapTaskView, RoadmapView } from '../types/view'

const STATUSES: readonly RoadmapTaskStatus[] = ['NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'NOT_APPLICABLE', 'NEEDS_CONFIRMATION']
const KINDS: readonly RoadmapTaskKind[] = ['CHECKLIST', 'PROCEDURE', 'DOCUMENT_CHECK', 'CASE_FACT']

const isText = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0

/**
 * 할 일 한 줄. 번호·제목이 없거나 상태·종류를 모르면 `null` 이다.
 *
 * 모르는 상태를 비슷한 상태로 바꿔 그리지 않는다. 예를 들어 "해당 없음"인 할 일을 "시작 전"으로 그리면
 * 할 필요 없는 일을 하라고 내미는 셈이다.
 */
function toTask(value: unknown): RoadmapTaskView | null {
  const row = value as Partial<Record<keyof RoadmapResponse['stages'][number]['tasks'][number], unknown>> | null
  if (!row || !isText(row.task_id) || !isText(row.title)) return null

  const status = STATUSES.find((item) => item === row.status)
  const kind = KINDS.find((item) => item === row.kind)
  if (!status || !kind) return null

  return {
    id: row.task_id,
    title: row.title,
    kind,
    status,
    ...(isText(row.guidance) ? { guidance: row.guidance } : {}),
  }
}

function toStage(value: unknown): RoadmapStageView | null {
  const row = value as Partial<Record<keyof RoadmapResponse['stages'][number], unknown>> | null
  if (!row || typeof row.stage !== 'number' || !isText(row.title) || !Array.isArray(row.tasks)) return null

  return {
    stage: row.stage,
    title: row.title,
    tasks: row.tasks.map(toTask).filter((task): task is RoadmapTaskView => task !== null),
  }
}

/**
 * 로드맵 조회(`GET /cases/roadmap`, #178)를 로드맵 화면 모양으로 바꾼다.
 *
 * 단계·할 일·지금 단계는 서버가 준 그대로 옮긴다. 화면이 할 일 상태를 보고 지금 단계를 짐작하지
 * 않는다(#179 `current_stage`).
 *
 * **모르는 상태·종류인 할 일은 그 줄만 뺀다.** 서버가 값을 늘려도 FE가 따라오기 전까지 로드맵이 통째로
 * 사라지면 안 된다(기록 `toLogEntries` 와 같은 기준). 단계 목록이 없거나 지원 여부를 모르면 읽지 못한
 * 것이라 `null` 이고, 화면은 "불러오지 못했어요"로 그린다.
 */
export function toRoadmapView(body: RoadmapResponse | null): RoadmapView | null {
  if (!body || typeof body.supported !== 'boolean' || !Array.isArray(body.stages)) return null

  return {
    supported: body.supported,
    unsupportedReason: isText(body.unsupported_reason) ? body.unsupported_reason : null,
    currentStage: typeof body.current_stage === 'number' ? body.current_stage : null,
    stages: body.stages.map(toStage).filter((stage): stage is RoadmapStageView => stage !== null),
  }
}
