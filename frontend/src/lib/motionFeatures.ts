/**
 * 움직임 도구(Motion)의 기능 묶음. `App.tsx` 가 첫 화면을 그린 뒤 따로 받아 온다.
 *
 * 끌기(아래 시트 끌어서 닫기)까지 든 묶음이라 크다(gzip 약 40KB). 첫 화면을 받는 데 끼우면
 * 그만큼 화면이 늦게 뜬다. 따로 받는 동안 `m.div` 는 움직임 없이 그냥 그려진다.
 */
export { domMax as default } from 'motion/react'
