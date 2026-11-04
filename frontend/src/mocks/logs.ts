import type { LogEntry } from '../types/view'

/**
 * 기록 탭 · 홈 띠의 Mock 데이터. Preview 의 가짜 로그인과 `?mock=` 으로 볼 때만 쓴다.
 *
 * 서버가 줄 수 있는 사건 코드(#143)로 만든 문장만 둔다. 시안의 "철거 서류 4개를 나눠 넣었어요"
 * 같은 줄은 아직 서버에 그런 사건이 없어 넣지 않는다 — 넣으면 실서버에서 볼 수 없는 화면을
 * 리뷰하게 된다.
 */
export const mockLogEntries: LogEntry[] = [
  { key: 'mock-5', actor: 'RIBBON', text: '다음 할 일을 정했어요', detail: '철거 업체 견적 받기', date: '10.18' },
  { key: 'mock-5-added', actor: 'RIBBON', text: '할 일 3개를 새로 추가했어요', date: '10.18' },
  { key: 'mock-4', actor: 'OWNER', text: '할 일 하나를 마치셨어요', date: '10.18' },
  { key: 'mock-3-uploaded', actor: 'OWNER', text: '서류를 올리셨어요', detail: '임대차계약서', date: '10.17' },
  { key: 'mock-3', actor: 'RIBBON', text: '기록과 다른 부분을 찾았어요', date: '10.17' },
  { key: 'mock-2', actor: 'OWNER', text: '할 일 결과를 알려주셨어요', date: '10.17' },
  { key: 'mock-1', actor: 'RIBBON', text: '다음 할 일을 정했어요', detail: '임대인에게 원상복구 범위 묻기', date: '10.14' },
  { key: 'mock-0', actor: 'OWNER', text: '가게 상황을 알려주셨어요', date: '10.14' },
]
