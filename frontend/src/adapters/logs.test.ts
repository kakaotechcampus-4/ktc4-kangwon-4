import { describe, expect, it, vi } from 'vitest'

import type { CaseLogItem, CaseLogResponse } from '../types/api'
import { toLogEntries, withTaskTitles } from './logs'
import type { RoadmapView } from '../types/view'

/** 서버 기록 한 줄. 테스트가 보려는 칸만 바꾼다. 서버가 모르는 코드를 보내는 경우도 만들 수 있게 넓게 받는다 */
const log = (actor: string, event: string, overrides: Partial<Record<keyof CaseLogItem, unknown>> = {}) =>
  ({ actor, event, occurred_at: '2026-10-17T14:02:11+09:00', task_id: null, detail: null, ...overrides }) as CaseLogItem

const logsOf = (...logs: CaseLogItem[]): CaseLogResponse => ({ logs })

/**
 * 기록은 사장님이 무엇을 했고 리본이 무엇을 했는지 돌아보는 자리다. 여기서 틀리면
 * 한 적 없는 일이 남거나, 한 사람이 바뀌어 기록이 거짓이 된다.
 */
describe('toLogEntries', () => {
  it('사건 코드를 문장으로, 날짜를 월.일로 바꾸고 서버 순서를 지킨다', () => {
    expect(
      toLogEntries(
        logsOf(
          log('RIBBON', 'MORE_INFO_REQUESTED', { occurred_at: '2026-10-18T09:00:00+09:00' }),
          log('OWNER', 'RESULT_SUBMITTED'),
        ),
      ),
    ).toEqual([
      { key: '0-MORE_INFO_REQUESTED', actor: 'RIBBON', text: '더 여쭤볼 것을 정리했어요', date: '10.18' },
      { key: '1-RESULT_SUBMITTED', actor: 'OWNER', text: '할 일 결과를 알려주셨어요', date: '10.17' },
    ])
  })

  /**
   * `Date` 로 읽으면 브라우저 시간대로 바뀌어, 한국 밖에서는 날짜가 밀린다.
   * 한국 밤 11시 기록이 다른 날로 넘어가면 안 된다
   */
  it('날짜는 글자에서 잘라 쓴다', () => {
    // 테스트는 UTC 에서 돌아 밀림이 안 보인다. 한국보다 느린 시간대로 바꿔 본다
    vi.stubEnv('TZ', 'America/Los_Angeles')
    try {
      expect(
        toLogEntries(logsOf(log('OWNER', 'CASE_CREATED', { occurred_at: '2026-10-31T23:59:59+09:00' })))?.[0].date,
      ).toBe('10.31')
    } finally {
      vi.unstubAllEnvs()
    }
  })

  /** 무엇을 정했는지까지 보여야 기록이 쓸모 있다. 서버가 할 일 제목을 같이 준다(#143) */
  it('정한 할 일 제목과 사장님이 알려 준 심사 결과를 덧붙인다', () => {
    const entries = toLogEntries(
      logsOf(
        log('RIBBON', 'NEXT_ACTION_DECIDED', { detail: '철거 업체 견적 받기' }),
        log('OWNER', 'SUPPORT_RESULT_REPORTED', { detail: 'APPROVED' }),
        log('OWNER', 'SUPPORT_RESULT_REPORTED', { detail: 'SOMETHING_NEW' }),
      ),
    )

    expect(entries?.map((entry) => entry.detail)).toEqual(['철거 업체 견적 받기', '승인됐다고 하셨어요', undefined])
  })

  /** 어떤 항목인지는 로드맵 이름이 생기기 전까지 적지 않는다. 이름을 따로 들고 있으면 로드맵과 어긋난다 */
  it('체크 기록은 할 일 이름 없이 적는다', () => {
    const [completed, unchecked] = toLogEntries(
      logsOf(
        log('OWNER', 'CHECKLIST_COMPLETED', { task_id: 'dispose_stock' }),
        log('OWNER', 'CHECKLIST_UNCHECKED', { task_id: 'dispose_stock' }),
      ),
    )!

    expect(completed.text).toBe('할 일 하나를 마치셨어요')
    expect(unchecked.text).toBe('마친 할 일 하나를 되돌리셨어요')
    expect(completed.detail).toBeUndefined()
  })

  /** 서버가 사건을 늘려도(#159 서류 기록 예정) 목록 전체가 사라지거나 영어 코드가 뜨면 안 된다 */
  it('모르는 사건과 날짜를 못 읽는 줄만 뺀다', () => {
    const entries = toLogEntries(
      logsOf(
        // 서버가 늘린 사건을 FE가 아직 모를 때(이 이름은 지어낸 것)
        log('OWNER', 'STORE_RENAMED'),
        log('RIBBON', 'CONFLICT_FOUND', { occurred_at: '어제' }),
        log('RIBBON', 'CONFLICT_FOUND'),
      ),
    )

    expect(entries?.map((entry) => entry.text)).toEqual(['기록과 다른 부분을 찾았어요'])
  })

  it('누가 했는지가 사건과 어긋나면 그 줄을 뺀다', () => {
    expect(toLogEntries(logsOf(log('RIBBON', 'RESULT_SUBMITTED')))).toEqual([])
  })

  it('목록 모양이 아니면 읽지 못한 것으로 둔다', () => {
    expect(toLogEntries(null)).toBeNull()
    expect(toLogEntries({ logs: 'none' } as unknown as CaseLogResponse)).toBeNull()
    expect(toLogEntries(logsOf())).toEqual([])
  })

  /** 판단으로 로드맵 할 일이 늘었다(#184). 시안의 "답변대로"는 충돌에서 고른 뒤에도 생겨 뺀다 */
  it('새로 생긴 할 일 개수를 문장에 넣는다', () => {
    expect(toLogEntries(logsOf(log('RIBBON', 'ROADMAP_TASKS_ADDED', { detail: '3' })))).toEqual([
      { key: '0-ROADMAP_TASKS_ADDED', actor: 'RIBBON', text: '할 일 3개를 새로 추가했어요', date: '10.17' },
    ])
  })

  /** 개수를 못 읽었다고 줄을 빼면 리본이 한 일이 사라진다. "0개"·"-1개"처럼 틀린 숫자도 적지 않는다 */
  it('개수를 읽지 못하면 개수 없이 쓴다', () => {
    const entries = toLogEntries(
      logsOf(
        log('RIBBON', 'ROADMAP_TASKS_ADDED', { detail: null }),
        log('RIBBON', 'ROADMAP_TASKS_ADDED', { detail: '0' }),
        log('RIBBON', 'ROADMAP_TASKS_ADDED', { detail: '세 개' }),
      ),
    )

    expect(entries?.map((entry) => entry.text)).toEqual(['할 일을 새로 추가했어요', '할 일을 새로 추가했어요', '할 일을 새로 추가했어요'])
  })

  it('할 일 추가를 사장님이 했다고 오면 그 줄을 뺀다', () => {
    expect(toLogEntries(logsOf(log('OWNER', 'ROADMAP_TASKS_ADDED', { detail: '3' })))).toEqual([])
  })

  /** 서류함과 같은 이름으로 적는다(#174). 모르는 종류 코드를 영어로 보이지 않는다 */
  it('올린 서류는 종류 이름을 아래 줄에 붙이고, 모르는 종류면 붙이지 않는다', () => {
    expect(
      toLogEntries(
        logsOf(
          log('OWNER', 'DOCUMENT_UPLOADED', { detail: 'TRANSFER' }),
          log('OWNER', 'DOCUMENT_UPLOADED', { detail: 'MYSTERY' }),
        ),
      ),
    ).toEqual([
      { key: '0-DOCUMENT_UPLOADED', actor: 'OWNER', text: '서류를 올리셨어요', detail: '이체확인증', date: '10.17' },
      { key: '1-DOCUMENT_UPLOADED', actor: 'OWNER', text: '서류를 올리셨어요', date: '10.17' },
    ])
  })

  /** 이전 서버는 재판단 중이거나 실패해도 이 사건을 보낸다. 접수만으로 계약 변경을 단정하지 않는다 */
  it('이전 서버의 서류 재판단 기록은 업로드 사실만 적는다', () => {
    expect(toLogEntries(logsOf(log('OWNER', 'DOCUMENT_SUBMITTED')))).toEqual([
      { key: '0-DOCUMENT_SUBMITTED', actor: 'OWNER', text: '서류를 올리셨어요', date: '10.17' },
    ])
  })

  it('서류 점검 통과는 리본이 한 일로 적는다', () => {
    expect(toLogEntries(logsOf(log('RIBBON', 'DOCUMENTS_CHECKED')))).toEqual([
      { key: '0-DOCUMENTS_CHECKED', actor: 'RIBBON', text: '서류를 점검하고 제출 파일을 만들었어요', date: '10.17' },
    ])
  })
})

/** 등록된 절차를 다 마친 기록(#315). 리본이 한 일로 적고, 사장님이 했다고 오면 거짓이라 뺀다 */
describe('toLogEntries — 등록된 절차 종료', () => {
  it('리본이 등록된 절차를 모두 마쳤다고 적는다', () => {
    expect(toLogEntries(logsOf(log('RIBBON', 'PROCEDURES_COMPLETED')))?.map((entry) => entry.text)).toEqual([
      '등록된 절차를 모두 마쳤어요',
    ])
    expect(toLogEntries(logsOf(log('OWNER', 'PROCEDURES_COMPLETED')))).toEqual([])
  })
})

/** 체크 기록은 번호만 온다. 이름은 로드맵이 준 것을 붙인다(FE가 따로 들고 있으면 로드맵과 어긋난다) */
describe('withTaskTitles', () => {
  const roadmap: RoadmapView = {
    supported: true,
    unsupportedReason: null,
    currentStage: 3,
    stages: [{ stage: 3, title: '영업 마무리·폐업 신고', tasks: [{ id: 'dispose_stock', title: '재고·장비 처분', kind: 'CHECKLIST', status: 'COMPLETED' }] }],
  }

  it('체크 기록에 로드맵의 할 일 이름을 아래 줄로 붙인다', () => {
    const entries = toLogEntries(logsOf(log('OWNER', 'CHECKLIST_COMPLETED', { task_id: 'dispose_stock' })))!

    expect(withTaskTitles(entries, roadmap)).toEqual([
      { key: '0-CHECKLIST_COMPLETED', actor: 'OWNER', text: '할 일 하나를 마치셨어요', detail: '재고·장비 처분', taskId: 'dispose_stock', date: '10.17' },
    ])
  })

  /** 번호(영어)를 보이거나 줄을 빼면 안 된다. 이름을 모르면 지금 문구 그대로 둔다 */
  it('로드맵을 못 불러왔거나 로드맵에 없는 번호면 이름 없이 둔다', () => {
    const entries = toLogEntries(logsOf(log('OWNER', 'CHECKLIST_UNCHECKED', { task_id: 'old_task' })))!

    expect(withTaskTitles(entries, roadmap)[0].detail).toBeUndefined()
    expect(withTaskTitles(entries, null)[0].detail).toBeUndefined()
    expect(withTaskTitles(entries, roadmap)[0].text).toBe('마친 할 일 하나를 되돌리셨어요')
  })
})
