import type { LogActor, LogEntry } from '../types/view'

/**
 * 기록 조회(`GET /cases/logs`, #143)를 기록 탭 모양으로 바꾼다.
 *
 * 서버는 문구 없이 사건 코드만 준다(#143 "문구는 FE가 event 코드로 만든다"). 코드 → 문구는
 * 화면에 띄우는 말을 고르는 것이라 판단이 아니라 표시다.
 *
 * TODO(#143): 머지되면 `types/api.ts` 에 응답 모양을 넣고 `unknown` 대신 그 타입으로 받는다.
 * 지금은 머지 전이라 확정되지 않은 칸을 타입에 넣지 않는다(FE 규칙 9).
 */

/** 사건 코드 → 문장. 누가 했는지는 줄 아래(`사장님 · 10.17`)에 따로 적어서 문장에 넣지 않는다 */
const EVENT_TEXT: Record<string, { actor: LogActor; text: string }> = {
  CASE_CREATED: { actor: 'OWNER', text: '가게 상황을 알려주셨어요' },
  RESULT_SUBMITTED: { actor: 'OWNER', text: '할 일 결과를 알려주셨어요' },
  CONFLICT_DECIDED: { actor: 'OWNER', text: '기록과 다른 부분에서 맞는 쪽을 고르셨어요' },
  NEXT_ACTION_DECIDED: { actor: 'RIBBON', text: '다음 할 일을 정했어요' },
  MORE_INFO_REQUESTED: { actor: 'RIBBON', text: '더 여쭤볼 것을 정리했어요' },
  CONFLICT_FOUND: { actor: 'RIBBON', text: '기록과 다른 부분을 찾았어요' },
  JUDGMENT_FAILED: { actor: 'RIBBON', text: '다음 할 일을 정하지 못했어요' },
}

/** 누가 했는지 화면 말 */
export const ACTOR_LABEL: Record<LogActor, string> = { OWNER: '사장님', RIBBON: '리본' }

/**
 * `2026-10-17T14:02:11` → `10.17`.
 *
 * `Date` 로 바꾸지 않는다. 서버는 시간대 없이 한국 시각을 보내서(#143), `Date` 로 읽으면
 * 브라우저 시간대에 따라 날짜가 밀린다. 글자에서 월·일만 잘라 쓰면 그런 일이 없다.
 */
function toDateLabel(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const matched = /^\d{4}-(\d{2})-(\d{2})/.exec(value)
  return matched ? `${matched[1]}.${matched[2]}` : null
}

/**
 * 기록 목록을 화면 줄로. 목록 모양이 아니면 `null`(화면이 "불러오지 못했어요"로 그린다).
 *
 * **모르는 코드는 그 줄만 뺀다.** 서버가 사건을 늘리면(#149 체크·#159 서류 기록 예정)
 * FE가 따라오기 전까지 코드가 영어로 뜨거나 목록 전체가 사라지면 안 된다. 날짜를 못 읽는
 * 줄도 같다.
 *
 * 누가 했는지는 서버 `actor` 를 그대로 쓰되, 코드와 어긋나면 그 줄을 뺀다 — 사장님이 한 일을
 * 리본이 했다고 적으면 기록이 거짓이 된다.
 *
 * 순서는 서버 그대로다(최근 것부터).
 */
export function toLogEntries(body: unknown): LogEntry[] | null {
  const logs = (body as { logs?: unknown } | null)?.logs
  if (!Array.isArray(logs)) return null

  const entries: LogEntry[] = []
  logs.forEach((item: unknown, index) => {
    const row = item as { actor?: unknown; event?: unknown; occurred_at?: unknown } | null
    const known = typeof row?.event === 'string' ? EVENT_TEXT[row.event] : undefined
    const date = toDateLabel(row?.occurred_at)
    if (!known || date === null || row?.actor !== known.actor) return

    entries.push({ key: `${index}-${row.event}`, actor: known.actor, text: known.text, date })
  })
  return entries
}
