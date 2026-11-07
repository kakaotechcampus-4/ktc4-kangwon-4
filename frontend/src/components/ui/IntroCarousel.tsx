import {
  IconBellLine,
  IconBoxFlapLine,
  IconCheckmarkCircleFill,
  IconCheckmarkLine,
  IconDocumentLine,
  IconExclamationmarkCircleFill,
  IconILowercaseSerifCircleFill,
  IconPictureLine,
  IconReceiptLine,
  IconSparkle2Fill,
} from '@karrotmarket/react-monochrome-icon'
import { useState, type ReactNode } from 'react'

import { AiNotice } from './AiNotice'

/**
 * 소개 한 장. 제목은 앞 · 강조 · 뒤 세 조각으로 나눠 강조만 주황으로 칠한다.
 * 줄바꿈 자리는 `\n`으로 적고 `whitespace-pre-line`으로 살린다.
 */
interface Slide {
  pre: string
  highlight: string
  post: string
  sub: string
  /** 처음 쓸 때 한 번 AI 사용을 알린다. 마지막 장에만 둔다(#237) */
  aiNotice?: boolean
  picture: ReactNode
}

/**
 * 그림 속 휴대폰 화면.
 *
 * 그림이라 실제 화면이 아니다. 안의 글자는 "이런 일을 해요"를 보여주는 예시이고,
 * 서버 데이터가 아니다. 그래서 시안의 시연용 가게 이름("봄날 개인카페")은 "우리 가게"로
 * 바꿨다 — 사장님이 자기 가게가 이미 등록된 것으로 읽지 않게 한다.
 *
 * 색은 그림 속 화면 바탕이라 값이 같은 토큰을 빌린다(`#f7f8f9` = `bg-layer-default-pressed`).
 */
function PhoneFrame({ children }: { children: ReactNode }) {
  return (
    <div
      aria-hidden="true"
      className="mx-auto h-97 w-66 shrink-0 overflow-hidden rounded-t-[44px] bg-bg-neutral-weak px-2 pt-2 ring-1 ring-stroke-neutral-subtle ring-inset"
    >
      <div className="flex h-full flex-col gap-2.5 overflow-hidden rounded-t-[36px] bg-bg-layer-default-pressed px-3.5 pt-5.5 text-left">
        {children}
      </div>
    </div>
  )
}

function RoadmapPicture() {
  return (
    <PhoneFrame>
      <div className="flex items-center">
        <span className="flex-1 text-15 font-bold">우리 가게</span>
        <IconBellLine size={18} />
      </div>
      <div className="flex flex-col gap-2 rounded-xl bg-bg-layer-default px-3 py-2.5">
        <span className="text-12 font-bold">5단계 중 2단계 · 원상복구·철거</span>
        <div className="grid grid-cols-5 gap-0.75">
          {[true, true, false, false, false].map((done, k) => (
            <span key={k} className={`h-1 rounded-xs ${done ? 'bg-fg-brand' : 'bg-bg-neutral-weak-pressed'}`} />
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-2.5 rounded-14 bg-bg-layer-default p-3.5 shadow-floating">
        <span className="self-start rounded-sm bg-bg-brand-weak px-1.5 text-11 leading-5 font-bold text-fg-brand-contrast">
          사장님 할 일
        </span>
        <span className="text-15 font-bold">임대인에게 원상복구 범위를 물어보세요</span>
        <span className="text-12 text-fg-neutral-muted">범위에 따라 철거와 지원금 신청이 달라져요.</span>
        <span className="grid h-9 place-items-center rounded-lg bg-bg-brand-solid text-13 font-bold text-fg-on-brand-solid">
          물어볼 내용 보기
        </span>
      </div>
      <span className="flex items-center gap-1.25 pt-0.5 text-12 font-bold">
        <IconSparkle2Fill size={13} className="text-fg-brand" />
        리본이 해둔 일
      </span>
      <span className="flex gap-1.5 text-12">
        <IconCheckmarkLine size={14} className="shrink-0 text-fg-brand" />
        계약서에서 원상복구 조항을 찾아뒀어요
      </span>
    </PhoneFrame>
  )
}

const SORTED_DOCS = [
  { name: '철거공사내역서', icon: <IconReceiptLine size={16} /> },
  { name: '전자세금계산서', icon: <IconReceiptLine size={16} /> },
  { name: '철거 전 사진', icon: <IconPictureLine size={16} /> },
  { name: '철거 후 사진', icon: <IconPictureLine size={16} /> },
  { name: '임대차계약서', icon: <IconDocumentLine size={16} /> },
]

function DocsPicture() {
  return (
    <PhoneFrame>
      <span className="text-15 font-bold">서류함</span>
      <div className="flex items-start gap-2 rounded-[10px] bg-bg-brand-weak px-3 py-2.5 text-12">
        <IconSparkle2Fill size={14} className="mt-px shrink-0 text-fg-brand" />
        <div>
          <p className="font-bold">서류 4개를 나눠 넣었어요</p>
          <p className="text-fg-neutral-muted">사진 한 번에 올리면 끝나요</p>
        </div>
      </div>
      <ul className="rounded-14 bg-bg-layer-default py-1 shadow-floating">
        {SORTED_DOCS.map((doc) => (
          <li key={doc.name} className="flex items-center gap-2.5 px-2.5 py-2">
            <span className="grid size-7.5 shrink-0 place-items-center rounded-lg bg-bg-neutral-weak text-fg-neutral-muted">
              {doc.icon}
            </span>
            <span className="flex-1 text-13">{doc.name}</span>
            <span className="rounded-sm bg-bg-neutral-weak px-1.5 text-11 leading-5 font-medium text-fg-neutral-muted">
              보관 중
            </span>
          </li>
        ))}
      </ul>
    </PhoneFrame>
  )
}

const CHECKS: { label: string; note?: string; problem?: boolean }[] = [
  { label: '서류 종류 나누기' },
  { label: '상호·금액·날짜 꺼내기' },
  { label: '필요한 서류가 다 있는지', note: '이체확인증이 없어요', problem: true },
  { label: '서류끼리 금액 맞춰보기', note: '3,300,000원 · 거래처 같음' },
  { label: '개인정보 가리기' },
]

function CheckPicture() {
  return (
    <PhoneFrame>
      <div className="flex flex-col items-center gap-2 pt-1.5 pb-1 text-center">
        <IconExclamationmarkCircleFill size={36} className="text-fg-critical" />
        <span className="text-15 font-bold">확인하실 일이 1개 있어요</span>
        <span className="text-12 text-fg-neutral-muted">다른 서류는 모두 확인했어요</span>
      </div>
      <ul className="rounded-14 bg-bg-layer-default py-1.5 shadow-floating">
        {CHECKS.map((check) => (
          <li key={check.label} className="flex items-start gap-2.5 px-3 py-1.75">
            {check.problem ? (
              <IconExclamationmarkCircleFill size={20} className="shrink-0 text-fg-critical" />
            ) : (
              <IconCheckmarkCircleFill size={20} className="shrink-0 text-fg-brand" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-13">{check.label}</p>
              {check.note && (
                <p className={`text-11 ${check.problem ? 'text-fg-critical-contrast' : 'text-fg-neutral-muted'}`}>
                  {check.note}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </PhoneFrame>
  )
}

function SubmitPicture() {
  return (
    <PhoneFrame>
      <div className="flex flex-col items-center gap-2 pt-2.5 pb-1.5 text-center">
        <IconCheckmarkCircleFill size={40} className="text-fg-brand" />
        <span className="text-15 font-bold whitespace-pre-line">{'정산 제출 파일을\n만들었어요'}</span>
      </div>
      <div className="flex items-center gap-2.5 rounded-14 bg-bg-layer-default p-3 shadow-floating">
        <span className="grid size-8.5 shrink-0 place-items-center rounded-[9px] bg-bg-neutral-weak text-fg-neutral-muted">
          <IconBoxFlapLine size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-12 font-bold">정산제출_우리가게.zip</p>
          <p className="text-11 text-fg-neutral-subtle">서류 6종 · 점검 결과 1장</p>
        </div>
      </div>
      <div className="flex gap-1.5 rounded-[10px] bg-bg-neutral-weak-pressed px-3 py-2.5 text-11">
        <IconILowercaseSerifCircleFill size={13} className="mt-px shrink-0 text-fg-neutral-muted" />
        이 파일로 소상공인24에서 직접 제출해요
      </div>
      <span className="grid h-9 place-items-center rounded-lg bg-bg-brand-solid text-13 font-bold text-fg-on-brand-solid">
        파일 받기
      </span>
    </PhoneFrame>
  )
}

/**
 * 시안 M00의 네 장. 문구는 시안 그대로다.
 * 첫 장만 다르다 — 시안 "순서대로 알려드려요"는 단계를 차례로 밟는 것처럼 읽혀 "단계별로 챙겨드려요"로 바꿨다(#237)
 */
const SLIDES: Slide[] = [
  {
    pre: '폐업 준비, ',
    highlight: '단계별로',
    post: '\n챙겨드려요',
    sub: '우리 가게에 필요한 일만 골라드려요',
    picture: <RoadmapPicture />,
  },
  {
    pre: '서류는 ',
    highlight: '리본이 먼저',
    post: '\n읽고 정리해요',
    sub: '사진으로 찍어 올리면 종류별로 나눠요',
    picture: <DocsPicture />,
  },
  {
    pre: '빠진 서류는\n',
    highlight: '신청 전에',
    post: ' 찾아드려요',
    sub: '금액이 안 맞는 곳도 미리 알려드려요',
    picture: <CheckPicture />,
  },
  {
    pre: '신청은 ',
    highlight: '사장님이 직접',
    post: ',\n준비는 함께해요',
    sub: '제출할 파일을 한 번에 묶어드려요',
    aiNotice: true,
    picture: <SubmitPicture />,
  },
]

/**
 * 로그인 전에 보는 소개 네 장.
 *
 * 장마다 위 막대가 4.5초에 걸쳐 차오르고, 다 차면 다음 장으로 넘어간다. 화면 왼쪽
 * 1/3을 누르면 앞 장, 나머지를 누르면 다음 장이다(시안 그대로).
 *
 * **넘기는 시점을 타이머로 재지 않는다.** 막대 움직임이 끝나는 것(`animationend`)으로
 * 넘긴다. 타이머를 따로 두면 막대와 넘김이 어긋날 수 있고, 백그라운드 탭에서 움직임은
 * 멈췄는데 타이머만 흘러 몇 장을 건너뛴다.
 *
 * 같은 이유로 "움직임 줄이기"를 켠 사장님에게는 저절로 넘어가지 않는다. 막대가 움직이지
 * 않으니 끝나는 일도 없다. 직접 눌러서 넘기고, 막대는 지금 장까지 다 찬 모양으로 둔다.
 *
 * 누르는 자리는 투명한 버튼 두 개다. 화면 전체에 클릭을 걸고 좌표로 가르면 키보드와
 * 화면 낭독기로는 넘길 방법이 없다.
 */
export function IntroCarousel() {
  const [index, setIndex] = useState(0)
  const last = SLIDES.length - 1
  const slide = SLIDES[index]

  return (
    <section aria-label="리본 소개" className="flex min-h-0 flex-1 flex-col">
      <div aria-hidden="true" className="grid shrink-0 grid-cols-4 gap-1.5 px-4 pt-2.5">
        {SLIDES.map((_, k) => (
          <span key={k} className="h-1 overflow-hidden rounded-xs bg-bg-neutral-weak-pressed">
            <span
              // 지금 장이 되면 새로 그려야 움직임이 처음부터 다시 돈다
              key={k === index ? 'current' : 'other'}
              // 눈으로만 보는 막대라 역할이 없다. 테스트가 움직임 끝을 흉내 내려면 잡을 손잡이가 필요하다
              data-testid={k === index ? 'intro-progress' : undefined}
              onAnimationEnd={k === index && index < last ? () => setIndex(index + 1) : undefined}
              className={`block h-full rounded-xs bg-bg-brand-solid ${
                k < index ? 'w-full' : k > index ? 'w-0' : 'w-0 motion-safe:animate-intro-progress motion-reduce:w-full'
              }`}
            />
          </span>
        ))}
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden pt-11 select-none">
        {/* 장이 바뀔 때마다 새로 그려, 글은 흐리게 들어오고 그림은 조금 작은 데서 커지며 들어온다 */}
        <div key={index} className="flex flex-col gap-9">
          <div className="px-6 text-center motion-safe:animate-fade-in">
            <h1 className="text-26 font-bold whitespace-pre-line">
              {slide.pre}
              <span className="text-fg-brand-contrast">{slide.highlight}</span>
              {slide.post}
            </h1>
            <p className="mt-2.5 text-17 text-fg-neutral-muted">{slide.sub}</p>
            {slide.aiNotice && <AiNotice align="center" className="mt-2" />}
          </div>
          <div className="motion-safe:animate-picture-in">{slide.picture}</div>
        </div>

        <button
          type="button"
          aria-label="이전 소개"
          disabled={index === 0}
          onClick={() => setIndex(index - 1)}
          className="absolute inset-y-0 left-0 w-1/3 cursor-pointer disabled:cursor-default"
        />
        <button
          type="button"
          aria-label="다음 소개"
          disabled={index === last}
          onClick={() => setIndex(index + 1)}
          className="absolute inset-y-0 right-0 w-2/3 cursor-pointer disabled:cursor-default"
        />
      </div>
    </section>
  )
}
