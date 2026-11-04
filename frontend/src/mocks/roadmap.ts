import type { RoadmapTaskStatus, RoadmapTaskView, RoadmapView } from '../types/view'

/**
 * 로드맵 Mock 데이터. Preview 의 가짜 로그인과 `?mock=` 으로 볼 때만 쓴다.
 *
 * 할 일 번호·제목·종류는 AI 로드맵(`backend/app/agent/roadmap.py`)이 실제로 내는 26개와 같다.
 * 상태만 "2단계를 하는 중"인 가게로 지어 두었다. 화면이 받을 모양을 리뷰하려는 것이라, 서버가
 * 내지 않는 할 일이나 설명은 넣지 않는다.
 */
const task = (id: string, title: string, kind: RoadmapTaskView['kind'], status: RoadmapTaskStatus, guidance?: string) =>
  ({ id, title, kind, status, ...(guidance ? { guidance } : {}) }) satisfies RoadmapTaskView

export const mockRoadmap: RoadmapView = {
  supported: true,
  unsupportedReason: null,
  currentStage: 2,
  stages: [
    {
      stage: 1,
      title: '폐업 준비',
      tasks: [
        task('intake', '상황 진단', 'CASE_FACT', 'COMPLETED'),
        task('closure_date', '폐업 날짜 정하기', 'CASE_FACT', 'IN_PROGRESS'),
        task('notify_landlord', '임대인에게 폐업 알리고 계약 종료일 맞추기', 'CHECKLIST', 'COMPLETED'),
        task(
          'notify_employees',
          '직원에게 폐업 알리기',
          'CHECKLIST',
          'COMPLETED',
          '폐업으로 직원을 해고하는 경우, 적어도 30일 전에 알려야 하고 30일 전에 알리지 못했다면 30일분 이상의 통상임금을 줘야 해요. 계속 일한 기간이 3개월 미만인 직원 등은 예외예요.',
        ),
        task('check_loan', '은행에 폐업 후 상환 조건 확인', 'CHECKLIST', 'NOT_APPLICABLE'),
      ],
    },
    {
      stage: 2,
      title: '원상복구·철거',
      tasks: [
        task('restoration', '원상복구 범위 확인', 'PROCEDURE', 'IN_PROGRESS'),
        task('support_conditions', '점포철거비 조건 확인', 'CHECKLIST', 'COMPLETED'),
        task('support_application', '소상공인24 사전 신청', 'CHECKLIST', 'NOT_STARTED'),
        task('support_approval', '1차 적격심사 결과 확인', 'CASE_FACT', 'NEEDS_CONFIRMATION'),
        task('choose_contractor', '철거 업체 정하기', 'CHECKLIST', 'NOT_STARTED'),
        task('before_photo', '철거 전 사진', 'CHECKLIST', 'NOT_STARTED'),
        task('restoration_work', '원상복구·철거 작업', 'PROCEDURE', 'NOT_STARTED'),
        task('contractor_documents', '철거 후 서류 받기', 'CHECKLIST', 'NOT_STARTED'),
      ],
    },
    {
      stage: 3,
      title: '영업 마무리·폐업 신고',
      tasks: [
        task('dispose_stock', '재고·장비 처분', 'CHECKLIST', 'NOT_STARTED'),
        task('terminate_contracts', '카드단말기·배달앱·렌탈·공과금 해지', 'CHECKLIST', 'NOT_STARTED'),
        task('employee_payments', '직원 임금·퇴직급여 정산', 'PROCEDURE', 'NOT_STARTED'),
        task('employee_insurance', '4대보험 상실·탈퇴 신고', 'PROCEDURE', 'NOT_STARTED'),
        task('closure_submission', '통합 폐업 신고', 'PROCEDURE', 'NOT_STARTED'),
      ],
    },
    {
      stage: 4,
      title: '지원금 정산·가게 반환',
      tasks: [
        // 1차 심사 결과를 아직 몰라서(위 `support_approval`) 서버가 정산 항목을 "확인 필요"로 준다(#181)
        task('closure_certificate', '폐업사실증명원 발급', 'CHECKLIST', 'NEEDS_CONFIRMATION'),
        task('document_check', 'AI 서류 점검', 'DOCUMENT_CHECK', 'NOT_STARTED'),
        task('settlement_submission', '소상공인24 정산 제출', 'CHECKLIST', 'NEEDS_CONFIRMATION'),
        task('return_premises', '가게 반환', 'PROCEDURE', 'NOT_STARTED'),
        task('deposit_settlement', '보증금 정산 기록', 'CHECKLIST', 'NOT_STARTED'),
      ],
    },
    {
      stage: 5,
      title: '세금·마무리',
      tasks: [
        task('vat_submission', '부가세 폐업 확정신고', 'CHECKLIST', 'NOT_STARTED'),
        task('income_tax', '종합소득세 신고 여부 확인', 'CHECKLIST', 'NOT_STARTED'),
        task('post_closure_support', '폐업 후 지원 안내 확인', 'CHECKLIST', 'NOT_STARTED'),
      ],
    },
  ],
}

/** `?mock=roadmap-unsupported`: 미지원 업종. 문구는 서버(`roadmap.py`)가 쓰는 그대로다 */
export const mockUnsupportedRoadmap: RoadmapView = {
  supported: false,
  unsupportedReason: '지금은 개인 카페만 폐업 순서를 안내해요. 프랜차이즈 카페와 일반 음식점은 준비 중이에요.',
  currentStage: null,
  stages: [],
}
