import type {
  ConfirmView,
  ConflictSide,
  ReplanView,
  ResultInputView,
  SubmitOutcome,
} from '../types/view'

/**
 * ③④⑤ 결과 입력 흐름의 Mock 데이터.
 *
 * `docs/hero-scenario.md` §5의 Turn 2(재계획)와 Turn 3(충돌)을 그대로 옮겼다.
 * ② `normalCase`에서 이어지는 한 사람의 이야기다 — 원상복구 범위를 확인하러 갔다가
 * 임대인에게 철거가 필요하다는 답을 듣고 돌아온 시점.
 *
 * 각 Mock은 서버가 이미 판단을 마친 결과다. 입력한 문장을 보고 무엇이 바뀌었는지
 * 계산하는 함수를 두면 안 된다 — 그 판단은 서버 몫이다.
 */

/** ③ — 무엇에 대한 결과를 말하는지 상기시킬 직전 Next Action */
export const resultInput: ResultInputView = {
  nextAction: {
    seq: 1,
    title: '임대인에게 원상복구 범위를 확인하세요.',
    reason:
      '철거가 필요한지, 이후 어떤 순서로 정리할지 판단하려면 원상복구 범위를 먼저 알아야 합니다.',
    questions: ['어디까지 원래대로 돌려놔야 하나요?', '철거까지 해야 하나요?'],
  },
}

/**
 * 처리 중에 순서대로 보여줄 문구.
 *
 * 정지한 스피너는 몇 초만 지나도 고장으로 읽히지만, 문구가 바뀌면 살아 있는 것으로
 * 읽힌다. `/results` 한 번에 여러 Agent와 Review가 도는 구조라 대기가 길 수 있다.
 *
 * TODO(API): 이 문구들은 Supervisor가 실제로 무엇을 부르는지 모르는 상태에서 추정해
 * 쓴 것이다. 지원금 Agent를 부르지 않는 요청에도 "지원을 찾는 중"이 뜨면 화면이 사실이
 * 아닌 것을 말하게 된다. 연동 시점에 두 갈래 중 하나로 정한다.
 *   - 서버가 진행 단계를 내려주면 그 값으로 바꾼다 (현재 계약에는 없음)
 *   - 내려주지 않으면 과정을 특정하지 않는 문구로 바꾼다 (진행감만 전달)
 */
export const pendingMessages = [
  '말씀하신 내용을 확인하고 있습니다',
  '바뀐 내용이 어떤 절차에 영향을 주는지 살펴보는 중입니다',
  '받으실 수 있는 지원이 있는지 찾아보는 중입니다',
  '다음에 하실 일을 정리하고 있습니다',
]

/** ⑤ 정상 — 철거가 필요하다고 확인되어 다음 할 일이 바뀐 상태 */
export const updatedReplan: ReplanView = {
  changes: [
    {
      key: 'restoration_scope',
      label: '원상복구 범위',
      previousValue: null,
      newValue: '전체 철거',
    },
    {
      key: 'demolition_required',
      label: '철거 필요 여부',
      previousValue: null,
      newValue: '필요함',
    },
  ],
  blocker: {
    title: '철거 전에 지원 조건을 확인해야 합니다.',
    description: '철거를 먼저 진행하면 지원 신청에 필요한 증빙을 남기지 못할 수 있어요.',
  },
  nextAction: {
    seq: 2,
    title: '점포철거비 지원 조건과 필요한 서류를 확인하세요.',
    reason:
      '철거가 필요하다고 확인되어 점포철거비 지원이 검토 대상이 되었습니다. 신청 조건에 철거 전 증빙이 포함될 수 있습니다.',
    questions: ['신청하려면 어떤 서류가 필요한가요?', '철거 전에 받아둬야 할 것이 있나요?'],
  },
}

/**
 * ⑤ 예외 — 이미 알고 있던 내용이라 바뀐 것이 없는 상태.
 *
 * 사실이 그대로이므로 이전 판단도 그대로다.
 */
export const noChangeReplan: ReplanView = {
  changes: [],
  blocker: updatedReplan.blocker,
  nextAction: updatedReplan.nextAction,
}

/**
 * ④에서 기존 기록을 유지하기로 한 경우.
 *
 * Case가 바뀌지 않았으므로 판단도 바뀌지 않는다. 여기서 새 할 일을 만들면
 * "바뀐 것이 없다"는 안내와 화면이 서로 다른 말을 하게 된다.
 */
export const keptReplan: ReplanView = {
  changes: [],
  blocker: {
    title: '원상복구 범위가 아직 확인되지 않았습니다.',
    description: '이 내용이 확인되면 다음 순서를 바로 알려드릴 수 있어요.',
  },
  nextAction: resultInput.nextAction,
}

/**
 * ④에서 새 값을 택한 경우.
 *
 * `updatedReplan`과 달리 이전 값이 `미확인`이 아니라 기록돼 있던 `필요 없음`이다.
 * ④가 "지금 기록된 내용: 필요 없음"이라고 보여준 직후라, 같은 값을 써야 두 화면이
 * 같은 과거를 말한다. 충돌 항목이 아닌 원상복구 범위는 여기 담지 않는다.
 */
export const confirmedReplan: ReplanView = {
  changes: [
    {
      key: 'demolition_required',
      label: '철거 필요 여부',
      previousValue: '필요 없음',
      newValue: '필요함',
    },
  ],
  blocker: updatedReplan.blocker,
  nextAction: updatedReplan.nextAction,
}

/** ④ — 기존 기록과 어긋나 사용자에게 되묻는 상태 */
export const conflictConfirm: ConfirmView = {
  rawInput: '다시 확인했는데 철거해야 한대요.',
  conflicts: [
    {
      key: 'demolition_required',
      label: '철거 필요 여부',
      storedValue: '필요 없음',
      incomingValue: '필요함',
    },
  ],
}

/** `?mock=` 키별로 준비된 제출 결과. 키가 없으면 정상 경로를 쓴다 */
const OUTCOMES: Record<string, SubmitOutcome> = {
  conflict: { kind: 'CONFIRM', view: conflictConfirm },
  'no-change': { kind: 'REPLAN', view: noChangeReplan },
  'more-info': {
    kind: 'STAY',
    state: {
      kind: 'NEEDS_MORE_INFO',
      questions: [
        '철거가 필요하다고 하신 곳이 매장 전체인가요, 일부인가요?',
        '임대인이 기한을 함께 말씀하셨나요?',
      ],
    },
  },
  invalid: {
    kind: 'STAY',
    state: {
      kind: 'INVALID_TRANSITION',
      message: '이미 철거가 끝난 것으로 기록되어 있어 이 내용은 반영할 수 없습니다.',
    },
  },
  failed: {
    kind: 'STAY',
    state: {
      kind: 'FAILED',
      message: '다음 할 일을 다시 계산하지 못했습니다.',
    },
  },
}

/**
 * `?mock=` 키에 따라 제출 결과를 돌려준다.
 *
 * 사용자가 친 문장을 함께 받아 충돌 화면에 그대로 싣는다. 서버는 이 문장을 응답에
 * 돌려주지 않으므로(`docs/interface-spec.md` §5), 연동 후에도 프론트가 자기가 보낸
 * 문장을 넘겨야 한다.
 *
 * 지연을 두는 것은 처리 중 화면을 눌러볼 수 있게 하려는 것이다.
 * TODO(API): 계약이 확정되면 이 함수를 `POST /cases/{caseId}/results` 호출로 바꾼다.
 */
export function simulateSubmit(mockKey: string, rawInput: string): Promise<SubmitOutcome> {
  const outcome: SubmitOutcome = Object.hasOwn(OUTCOMES, mockKey)
    ? OUTCOMES[mockKey]
    : { kind: 'REPLAN', view: updatedReplan }

  const resolved: SubmitOutcome =
    outcome.kind === 'CONFIRM'
      ? { kind: 'CONFIRM', view: { ...outcome.view, rawInput } }
      : outcome

  return new Promise((resolve) => {
    window.setTimeout(() => resolve(resolved), PENDING_MS)
  })
}

/**
 * 처리 중 지연.
 *
 * `PendingCard`의 문구 전환이 누적 5.4초(`STEP_MS` 1200+1800+2400)다. 이보다 짧으면
 * 뒤쪽 문구가 읽히기 전에 화면이 넘어가므로 넉넉하게 둔다. 실제 응답도 여러 Agent와
 * 필수 Review를 거쳐 수 초가 걸린다.
 */
const PENDING_MS = 7000

/**
 * ④에서 선택을 보낸 뒤의 결과.
 *
 * 준비된 응답 중 하나를 고를 뿐 재계획을 계산하지 않는다.
 *
 * 선택을 필드별로 받지만 지금은 "전부 유지했는가"만 본다. 충돌이 둘 이상이고 선택이
 * 엇갈리면 화면이 실제 선택과 달라진다 — Mock이 1건만 내려주는 동안은 드러나지 않는다.
 *
 * TODO(API): POST /cases/{caseId}/results/confirm 호출로 바꾼다. 요청 본문은
 * `rawInput`과 `confirmedChanges: [{ field, value }]` 라, 여기 오는 STORED/INCOMING을
 * 실제 값으로 바꾸고 입력 문장을 함께 넘기는 변환이 그때 필요하다.
 * 실패 응답과 네트워크 오류 처리도 그때 함께 넣는다.
 */
export function simulateConfirm(choices: Record<string, ConflictSide>): Promise<ReplanView> {
  const sides = Object.values(choices)
  const keptAll = sides.length > 0 && sides.every((side) => side === 'STORED')

  return new Promise((resolve) => {
    window.setTimeout(() => resolve(keptAll ? keptReplan : confirmedReplan), PENDING_MS)
  })
}
