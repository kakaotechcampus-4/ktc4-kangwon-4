import type { CurrentCaseView, Fact } from '../types/view'

/**
 * ② 현재 Case 화면의 Mock 데이터.
 *
 * 서버를 부를 수 없는 자리에서 화면을 보여주는 데이터다 — Preview 의 가짜 로그인과
 * `?mock=` 링크. 각 Mock 은 **서버가 이미 판단을 마친 결과**이고, facts 를 보고
 * blocker 를 유도하는 함수를 두면 안 된다. 그 판단은 서버 몫이다.
 *
 * 판단 상태마다 하나씩 둔다. 가게 정보는 상태와 무관하게 늘 보이므로 한 벌을 같이 쓴다 —
 * 상태마다 facts 를 따로 적어두면 한 곳만 고쳐서 서로 달라진다.
 */

/**
 * 사용자가 답할 수 있는 항목만 담는다. 지원 조건 확인처럼 시스템이 조회할 것은 넣지
 * 않는다 — "아직 확인 안 된 것" 목록이 사용자에게 할 일로 읽힌다.
 */
const facts: Fact[] = [
  { key: 'business_type', label: '업종', value: '카페', status: 'CONFIRMED' },
  { key: 'franchise', label: '프랜차이즈', value: '비프랜차이즈', status: 'CONFIRMED' },
  { key: 'employee_count', label: '직원 수', value: '2명', status: 'CONFIRMED' },
  { key: 'lease_status', label: '점포 형태', value: '임차 (월세)', status: 'CONFIRMED' },
  { key: 'planned_closure_date', label: '폐업 예정일', status: 'UNKNOWN' },
  { key: 'restoration_scope', label: '원상복구 범위', status: 'UNKNOWN' },
  { key: 'demolition_required', label: '철거 필요 여부', status: 'UNKNOWN' },
]

/**
 * 판단이 끝난 상태.
 *
 * `blocker` 와 다음 할 일이 반드시 함께 있다 — 서버가 둘 중 하나라도 비면 `DONE` 으로
 * 주지 않는다. "막힌 것이 없는" Mock 을 두지 않는 이유도 같다. 볼 수 없는 화면을
 * Mock 으로 남겨두면 있는 줄 알게 된다.
 *
 * `reason` 과 `questions` 는 서버가 아직 안 보내지만 여기서는 채워 둔다. 값이 들어왔을 때
 * 화면이 어떻게 보이는지 확인할 길이 필요하다.
 */
export const doneCase: CurrentCaseView = {
  facts,
  judgment: {
    status: 'DONE',
    blocker: {
      title: '원상복구 범위가 아직 확인되지 않았습니다.',
      description: '이 내용이 확인되면 다음 순서를 바로 알려드릴 수 있어요.',
    },
    nextAction: {
      title: '임대인에게 원상복구 범위를 확인하세요.',
      reason:
        '철거가 필요한지, 이후 어떤 순서로 정리할지 판단하려면 원상복구 범위를 먼저 알아야 합니다.',
      questions: ['어디까지 원래대로 돌려놔야 하나요?', '철거까지 해야 하나요?'],
    },
  },
}

/** Case 를 막 만들어 판단이 아직 돌고 있는 상태. 생성 직후에는 반드시 여기를 거친다 */
export const pendingCase: CurrentCaseView = {
  facts,
  judgment: { status: 'PENDING' },
}

/**
 * 다음 할 일을 정하기 전에 사장님에게 먼저 물어볼 것이 있는 상태.
 *
 * 여기 질문은 **서비스가 사장님에게** 묻는 것이다. 할 일 카드의 "이렇게 물어보세요"는
 * 사장님이 임대인에게 물을 말이라 서로 다르다.
 */
export const moreInfoCase: CurrentCaseView = {
  facts,
  judgment: {
    status: 'NEEDS_MORE_INFO',
    questions: [
      '임대인이 가게 전체를 원래대로 돌려놓으라고 했나요, 일부만 정리하면 된다고 했나요?',
      '철거 범위를 확인할 수 있는 계약서나 안내문이 있나요?',
    ],
  },
}

/** 판단을 마치지 못한 상태. 가게 정보는 저장돼 있고 사장님 탓이 아니다 */
export const judgmentFailedCase: CurrentCaseView = {
  facts,
  judgment: { status: 'FAILED' },
}

/**
 * 서버가 우리가 모르는 상태를 보냈거나, 상태와 내용의 조합이 계약과 어긋난 경우.
 *
 * 실제로 일어날 수 있다 — BE 가 `judgment_status` 에 `CONFLICT` 추가를 건의한 상태라,
 * 그쪽이 먼저 배포되면 이 화면이 뜬다.
 */
export const unrecognizedCase: CurrentCaseView = {
  facts,
  judgment: { status: 'UNRECOGNIZED' },
}
