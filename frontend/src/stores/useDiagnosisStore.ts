import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createSessionValue } from '../lib/sessionStore'
import type { DiagnosisAnswers } from '../types/view'

export const EMPTY_DIAGNOSIS: DiagnosisAnswers = {
  business: null,
  franchise: null,
  situations: null,
  paysRent: null,
  restorationClause: null,
  fullTimeCount: 0,
  partTimeCount: 0,
  hadEmployees: null,
  insurances: null,
  closure: null,
}

interface DiagnosisStore {
  answers: DiagnosisAnswers
  /** 고친 답만 넘긴다. 나머지 답은 그대로 둔다 */
  setAnswers: (patch: Partial<DiagnosisAnswers>) => void
  /** 가입 요청이 받아들여진 뒤 부른다. 다음 진단이 앞 사람의 답으로 시작하지 않게 한다 */
  reset: () => void
}

/**
 * 저장 자리를 `lib/sessionStore`에 맡긴다.
 *
 * 저장소를 못 쓰는 브라우저(사생활 보호 모드, 쓰기만 실패하는 경우)를 거기서 이미
 * 처리하고 있다. Zustand가 `sessionStorage`를 직접 쓰면 쓰기가 실패할 때 답을 고르는
 * 순간 예외가 나서 화면이 멈춘다. 같은 처리를 두 번 만들지 않는다.
 */
const saved = createSessionValue('reborn:diagnosis')

/**
 * 상황 진단 답.
 *
 * 질문이 한 장씩 주소(`?step=`)로 나뉘어 있어서, 화면을 넘기거나 새로고침해도 앞에서
 * 고른 답이 남아 있어야 한다. 그래서 화면 상태가 아니라 저장소에 둔다.
 *
 * `sessionStorage`에 두는 것은 로그인 토큰(`lib/auth.ts`)과 같은 이유다. 대출이 남았는지,
 * 직원이 몇 명인지 같은 답이 공용 PC에 브라우저를 닫은 뒤까지 남지 않게 한다.
 *
 * 답만 저장한다. 서버에서 오는 값(Case, 판단 결과)은 여기 두지 않는다.
 */
export const useDiagnosisStore = create<DiagnosisStore>()(
  persist(
    (set) => ({
      answers: EMPTY_DIAGNOSIS,
      setAnswers: (patch) => set((state) => ({ answers: { ...state.answers, ...patch } })),
      reset: () => set({ answers: EMPTY_DIAGNOSIS }),
    }),
    {
      name: 'reborn:diagnosis',
      storage: createJSONStorage(() => ({
        getItem: () => saved.read(),
        setItem: (_name, value) => saved.write(value),
        removeItem: () => saved.write(null),
      })),
      // 함수는 저장할 수 없고, 저장할 필요도 없다
      partialize: (state) => ({ answers: state.answers }),
    },
  ),
)
