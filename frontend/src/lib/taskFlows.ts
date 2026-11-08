import type { RoadmapTaskView } from '../types/view'

/**
 * 로드맵 할 일을 눌렀을 때 여는 장면(시안 M09).
 *
 *   CHECK           [다 했어요] / [완료 취소하기]. 체크 저장(#149)
 *   ATTACH          서류를 서류함에 올리고 체크. 서류는 서류 API(#159), 체크는 위와 같다
 *   SUPPORT_RESULT  철거비 1차 적격심사 결과 고르기(#149)
 *   DOCUMENT_CHECK  서류 점검 화면(`/docs/check`)으로 보낸다
 *   CLOSURE_REPORT  폐업 정보·가게 주소(#168)
 *   DEPOSIT         보증금 돌려받았는지(#168)
 *   REPORT_RESULT   공식 절차. 결과를 글로 알려주면 판단이 상태를 바꾼다(`/results`)
 *   INFO            사장님이 따로 할 것이 없다(가입 때 정한 것 등). 안내만
 */
export type TaskFlow =
  | 'CHECK'
  | 'ATTACH'
  | 'SUPPORT_RESULT'
  | 'DOCUMENT_CHECK'
  | 'CLOSURE_REPORT'
  | 'DEPOSIT'
  | 'REPORT_RESULT'
  | 'INFO'

/**
 * 할 일 번호 → 장면. 서버는 할 일 종류(`kind`)만 주고 어떤 입력을 받을지는 주지 않아 FE가 고른다.
 *
 * **무엇을 해야 하는지가 아니라 어떻게 받을지를 고르는 표다.** 할 일이 필요한지·끝났는지는 서버가
 * 정한다(FE 규칙 1). 여기 없는 번호는 종류로 고른다 — 서버가 할 일을 늘려도 화면이 막히지 않게.
 */
const FLOW_BY_TASK: Record<string, TaskFlow> = {
  // 사진·업체 서류·증명원은 서류함에 올려야 점검에 쓰인다
  before_photo: 'ATTACH',
  contractor_documents: 'ATTACH',
  closure_certificate: 'ATTACH',
  support_approval: 'SUPPORT_RESULT',
  closure_submission: 'CLOSURE_REPORT',
  deposit_settlement: 'DEPOSIT',
}

export function taskFlowOf(task: Pick<RoadmapTaskView, 'id' | 'kind'>): TaskFlow {
  const flow = FLOW_BY_TASK[task.id]
  if (flow) return flow

  switch (task.kind) {
    case 'CHECKLIST':
      return 'CHECK'
    case 'DOCUMENT_CHECK':
      return 'DOCUMENT_CHECK'
    case 'PROCEDURE':
      return 'REPORT_RESULT'
    case 'CASE_FACT':
      return 'INFO'
  }
}
