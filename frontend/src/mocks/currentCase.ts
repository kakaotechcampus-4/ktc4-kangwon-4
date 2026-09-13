import type { CurrentCaseView } from '../types/view'

/**
 * ② 현재 Case 화면의 Mock 데이터.
 *
 * 서버 연동 전까지 화면의 데이터 소스다. 스키마가 확정되면 어댑터로 교체하고
 * 이 파일은 테스트 픽스처로 남긴다.
 *
 * 각 Mock은 서버가 이미 판단을 마친 결과다. facts를 보고 blocker를 유도하는
 * 함수를 두면 안 된다 — 그 판단은 서버 몫이다.
 */

/** 정상 — 막힌 것이 있고 다음 할 일도 정해진 상태 */
export const normalCase: CurrentCaseView = {
  facts: [
    { key: 'business_type', label: '업종', value: '카페', status: 'CONFIRMED' },
    { key: 'franchise', label: '프랜차이즈', value: '비프랜차이즈', status: 'CONFIRMED' },
    { key: 'employee_count', label: '직원 수', value: '2명', status: 'CONFIRMED' },
    { key: 'lease_status', label: '점포 형태', value: '임차', status: 'CONFIRMED' },
    { key: 'restoration_scope', label: '원상복구 범위', status: 'IN_PROGRESS' },
    { key: 'demolition_required', label: '철거 필요 여부', status: 'UNKNOWN' },
    { key: 'support_check', label: '지원 조건 확인', status: 'UNKNOWN' },
  ],
  blocker: {
    title: '원상복구 범위가 아직 확인되지 않았습니다.',
    description: '이 내용이 확인되면 다음 순서를 바로 알려드릴 수 있어요.',
  },
  nextAction: {
    seq: 1,
    title: '임대인에게 원상복구 범위를 확인하세요.',
    reason:
      '철거가 필요한지, 이후 어떤 순서로 정리할지 판단하려면 원상복구 범위를 먼저 알아야 합니다.',
    questions: ['어디까지 원래대로 돌려놔야 하나요?', '철거까지 해야 하나요?'],
  },
}

/** 예외 — 막고 있는 것이 없는 상태. 회피 문구 대신 다음 할 일을 바로 보여준다 */
export const noBlockerCase: CurrentCaseView = {
  facts: [
    { key: 'business_type', label: '업종', value: '카페', status: 'CONFIRMED' },
    { key: 'franchise', label: '프랜차이즈', value: '비프랜차이즈', status: 'CONFIRMED' },
    { key: 'employee_count', label: '직원 수', value: '2명', status: 'CONFIRMED' },
    { key: 'lease_status', label: '점포 형태', value: '임차', status: 'CONFIRMED' },
    { key: 'restoration_scope', label: '원상복구 범위', value: '철거 필요', status: 'CONFIRMED' },
    { key: 'demolition_required', label: '철거 필요 여부', value: '필요함', status: 'CONFIRMED' },
    { key: 'support_check', label: '지원 조건 확인', value: '확인함', status: 'CONFIRMED' },
  ],
  blocker: null,
  nextAction: {
    seq: 4,
    title: '철거 업체에서 견적서를 받아 두세요.',
    reason: '지원 신청에 견적서가 필요합니다. 철거를 진행하기 전에 받아 두는 것이 좋습니다.',
  },
}

/** 예외 — 정보가 부족해 다음 할 일을 정할 수 없는 상태 */
export const insufficientCase: CurrentCaseView = {
  facts: [
    { key: 'business_type', label: '업종', value: '카페', status: 'CONFIRMED' },
    { key: 'lease_status', label: '점포 형태', status: 'UNKNOWN' },
    { key: 'franchise', label: '프랜차이즈', status: 'UNKNOWN' },
    { key: 'employee_count', label: '직원 수', status: 'UNKNOWN' },
  ],
  blocker: null,
  nextAction: null,
}
