import type { CaseLogResponse } from '../types/api'
import { DOCUMENT_KINDS } from './documents'
import type { LogActor, LogEntry } from '../types/view'

/**
 * 기록 조회(`GET /cases/logs`, #143)를 기록 탭 모양으로 바꾼다.
 *
 * 서버는 문구 없이 사건 코드만 준다(#143 "문구는 FE가 event 코드로 만든다"). 코드 → 문구는
 * 화면에 띄우는 말을 고르는 것이라 판단이 아니라 표시다.
 */

/** 사건 코드 → 문장. 누가 했는지는 줄 아래(`사장님 · 10.17`)에 따로 적어서 문장에 넣지 않는다 */
const EVENT_TEXT: Record<string, { actor: LogActor; text: string }> = {
  CASE_CREATED: { actor: 'OWNER', text: '가게 상황을 알려주셨어요' },
  RESULT_SUBMITTED: { actor: 'OWNER', text: '할 일 결과를 알려주셨어요' },
  CONFLICT_DECIDED: { actor: 'OWNER', text: '기록과 다른 부분에서 맞는 쪽을 고르셨어요' },
  /*
   * 어떤 할 일인지는 적지 않는다. 서버는 항목 번호(`task_id`)만 주고 이름은 로드맵이 따로
   * 내려주는데, 이름을 FE가 따로 들고 있으면 로드맵과 어긋날 수 있다(11/03 시우님).
   * TODO(로드맵 조회 API): 로드맵 이름을 받게 되면 "재고·장비 처분을 마치셨어요"처럼 적는다
   */
  CHECKLIST_COMPLETED: { actor: 'OWNER', text: '할 일 하나를 마치셨어요' },
  CHECKLIST_UNCHECKED: { actor: 'OWNER', text: '마친 할 일 하나를 되돌리셨어요' },
  SUPPORT_RESULT_REPORTED: { actor: 'OWNER', text: '점포철거비 1차 심사 결과를 알려주셨어요' },
  // 어떤 서류인지는 아래 줄에 서류함과 같은 이름으로 붙인다(`toDetail`)
  DOCUMENT_UPLOADED: { actor: 'OWNER', text: '서류를 올리셨어요' },
  NEXT_ACTION_DECIDED: { actor: 'RIBBON', text: '다음 할 일을 정했어요' },
  MORE_INFO_REQUESTED: { actor: 'RIBBON', text: '더 여쭤볼 것을 정리했어요' },
  CONFLICT_FOUND: { actor: 'RIBBON', text: '기록과 다른 부분을 찾았어요' },
  JUDGMENT_FAILED: { actor: 'RIBBON', text: '다음 할 일을 정하지 못했어요' },
  /*
   * 판단으로 로드맵 할 일이 새로 생겼다(#184). 개수는 `toText` 가 넣는다. 시안은 "답변대로 할 일 3개를
   * 추가했어요"인데, 충돌에서 고른 뒤의 판단에도 이 줄이 생겨 "답변대로"는 뺀다(11/04 #184 리뷰)
   */
  ROADMAP_TASKS_ADDED: { actor: 'RIBBON', text: '할 일을 새로 추가했어요' },
  // 서버는 정산 서류 점검을 통과했을 때만 남긴다(#174). 통과하면 제출 파일(ZIP)이 만들어진다
  DOCUMENTS_CHECKED: { actor: 'RIBBON', text: '서류를 점검하고 제출 파일을 만들었어요' },
}

/** 철거비 심사 결과(`detail`) → 덧붙이는 한 줄. 사장님이 알려 준 값이지 리본의 판단이 아니다 */
const SUPPORT_RESULT_DETAIL: Record<string, string> = {
  APPROVED: '승인됐다고 하셨어요',
  REJECTED: '안 됐다고 하셨어요',
  UNKNOWN: '아직 모른다고 하셨어요',
}

/** 누가 했는지 화면 말 */
export const ACTOR_LABEL: Record<LogActor, string> = { OWNER: '사장님', RIBBON: '리본' }

/**
 * `2026-10-17T14:02:11+09:00` → `10.17`.
 *
 * `Date` 로 바꾸지 않는다. 서버가 한국 시각을 보내니 글자에서 월·일만 잘라 쓰면 브라우저
 * 시간대와 상관없이 사장님이 겪은 날짜 그대로다. 시간대가 빠져 와도 같다.
 */
function toDateLabel(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const matched = /^\d{4}-(\d{2})-(\d{2})/.exec(value)
  return matched ? `${matched[1]}.${matched[2]}` : null
}

/** 줄 문장. 할 일이 몇 개 새로 생겼는지는 서버가 개수 글자로 준다. 읽지 못하면 개수 없이 쓴다 */
function toText(event: string, detail: unknown, text: string): string {
  if (event === 'ROADMAP_TASKS_ADDED' && typeof detail === 'string' && /^[1-9]\d*$/.test(detail)) {
    return `할 일 ${detail}개를 새로 추가했어요`
  }
  return text
}

/** 줄 아래 덧붙일 한 줄. 정한 할 일 제목, 심사 결과, 올린 서류 종류. 없거나 모르는 값이면 붙이지 않는다 */
function toDetail(event: string, detail: unknown): string | undefined {
  if (typeof detail !== 'string' || detail.length === 0) return undefined
  if (event === 'NEXT_ACTION_DECIDED') return detail
  if (event === 'SUPPORT_RESULT_REPORTED') return SUPPORT_RESULT_DETAIL[detail]
  // 서류함과 같은 이름을 쓴다. 모르는 종류면 코드(영어)를 보이지 않고 붙이지 않는다
  if (event === 'DOCUMENT_UPLOADED') return DOCUMENT_KINDS.find((item) => item.kind === detail)?.label
  return undefined
}

/**
 * 기록 목록을 화면 줄로. 목록 모양이 아니면 `null`(화면이 "불러오지 못했어요"로 그린다).
 *
 * **모르는 코드는 그 줄만 뺀다.** 서버가 사건을 늘려도(#174 서류 기록처럼) FE가 따라오기
 * 전까지 코드가 영어로 뜨거나 목록 전체가 사라지면 안 된다. 날짜를 못 읽는 줄도 같다.
 *
 * 누가 했는지는 서버 `actor` 를 그대로 쓰되, 코드와 어긋나면 그 줄을 뺀다 — 사장님이 한 일을
 * 리본이 했다고 적으면 기록이 거짓이 된다.
 *
 * 순서는 서버 그대로다(최근 것부터).
 */
export function toLogEntries(body: CaseLogResponse | null): LogEntry[] | null {
  const logs: unknown = body?.logs
  if (!Array.isArray(logs)) return null

  const entries: LogEntry[] = []
  logs.forEach((item: unknown, index) => {
    const row = item as Partial<Record<'actor' | 'event' | 'occurred_at' | 'detail', unknown>> | null
    const event = typeof row?.event === 'string' ? row.event : ''
    const known = EVENT_TEXT[event]
    const date = toDateLabel(row?.occurred_at)
    if (!known || date === null || row?.actor !== known.actor) return

    entries.push({
      key: `${index}-${event}`,
      actor: known.actor,
      text: toText(event, row?.detail, known.text),
      detail: toDetail(event, row?.detail),
      date,
    })
  })
  return entries
}
