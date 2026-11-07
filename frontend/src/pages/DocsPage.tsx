import {
  IconCameraLine,
  IconChevronDownLine,
  IconDocumentLine,
  IconDocumentTrayLine,
  IconPictureLine,
  IconPlusLine,
  IconTrashcanLine,
} from '@karrotmarket/react-monochrome-icon'
import { type ChangeEvent, type ReactNode, useId, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { Badge } from '../components/ui/Badge'
import { BottomSheet } from '../components/ui/BottomSheet'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { HammerLoader } from '../components/ui/HammerLoader'
import { InfoBox } from '../components/ui/InfoBox'
import { type DocumentAction, useDocuments } from '../hooks/useDocuments'
import { useEntersForward } from '../lib/viewTransition'
import type { DocumentCheckView, DocumentsView, DocumentView } from '../types/view'

/**
 * 서류함 (시안 M04). 할 일을 하면서 올린 서류가 모이는 곳.
 *
 * 올린 서류를 종류 이름과 상태 배지로 늘어놓고, [서류 올리기]로 한 장씩 더한다. 종류를 나누고
 * 값을 꺼내는 것은 서버(문서 Tool)가 하고, 화면은 결과를 옮긴다.
 *
 * 시안은 "정산 서류 6종 중 n종이 모였어요"와 빠진 서류 줄을 직접 그리지만 그 셈은 하지 않는다.
 * 무엇이 빠졌는지는 점검 결과의 서버 문구로만 알린다 — FE가 필요한 서류 목록을 들고 있으면
 * 점검 규칙이 두 곳에 생긴다(FE 규칙 1).
 */
export function DocsPage() {
  const navigate = useNavigate()
  const rise = useEntersForward()
  const { search } = useLocation()
  const { query, reload, action, upload, remove, confirm } = useDocuments()
  /** 종류·값을 확인하고 있는 서류 */
  const [confirming, setConfirming] = useState<DocumentView | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  /** 빼기 전에 묻고 있는 서류. 서버에서 지우면 되돌릴 길이 없어 한 번 묻는다 */
  const [removing, setRemoving] = useState<DocumentView | null>(null)

  function handlePicked(file: File) {
    setSheetOpen(false)
    void upload(file)
  }

  const uploadButton = (
    <Button
      variant="outline"
      disabled={query.status !== 'READY' || action === 'UPLOADING'}
      onClick={() => setSheetOpen(true)}
    >
      <span className="inline-flex items-center gap-1.5">
        <IconPlusLine size={20} aria-hidden="true" />
        서류 올리기
      </span>
    </Button>
  )

  if (query.status === 'LOADING') {
    return (
      <div className="flex flex-1 items-center justify-center">
        <HammerLoader size={48} label="서류함을 불러오는 중" />
      </div>
    )
  }

  // 불러오지 못한 것을 빈 서류함으로 그리면 올린 서류가 사라진 줄 안다
  if (query.status === 'LOAD_FAILED') {
    return (
      <EmptyState
        icon={<IconDocumentTrayLine size={32} />}
        title="서류함을 불러오지 못했어요"
        description="연결 상태를 확인하고 다시 불러와 주세요"
        action={<Button onClick={reload}>다시 불러오기</Button>}
      />
    )
  }

  const { documents, check, documentKinds } = query.view

  return (
    <div className="flex flex-1 flex-col gap-4 px-4 pt-2 pb-6">
      {documents.length === 0 ? (
        <EmptyState
          icon={<IconDocumentTrayLine size={32} />}
          title="아직 모인 서류가 없어요"
          description={'할 일을 하면서 올린 서류가\n여기에 모여요'}
        />
      ) : (
        <>
          <p className="text-15 text-fg-neutral-muted">서류 {documents.length}개가 모였어요.</p>
          <ul className={`flex flex-col ${rise ? 'rise-children' : ''}`}>
            {documents.map((document) => (
              <DocumentRow
                key={document.id}
                document={document}
                check={check}
                onRemove={() => setRemoving(document)}
                onConfirm={() => setConfirming(document)}
              />
            ))}
          </ul>
        </>
      )}

      <ActionNotice action={action} />
      {check?.status === 'ISSUES' && (
        <InfoBox tone="critical" title="점검에서 확인할 것이 있어요.">
          <ul className="flex flex-col gap-1">
            {check.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </InfoBox>
      )}

      <div className="mt-auto flex flex-col gap-2">
        {uploadButton}
        {/*
          주 버튼은 하나다(FE 규칙 5). 점검을 통과했으면 제출 파일로, 아니면 점검으로 간다.
          서류가 없으면 점검할 것이 없어 두지 않는다
        */}
        {check?.status === 'COMPLETE' ? (
          <Button onClick={() => navigate({ pathname: '/docs/done', search }, { viewTransition: true })}>정산 제출 파일 보기</Button>
        ) : (
          documents.length > 0 && (
            <Button disabled={action === 'UPLOADING'} onClick={() => navigate({ pathname: '/docs/check', search }, { viewTransition: true })}>
              정산 서류 점검하기
            </Button>
          )
        )}
      </div>

      <UploadSheet open={sheetOpen} onClose={() => setSheetOpen(false)} onPicked={handlePicked} />
      {/* 서류마다 새로 그린다. 앞 서류에서 고친 값이 다음 서류의 칸에 남으면 안 된다 */}
      <ConfirmSheet
        key={confirming?.id ?? 'none'}
        document={confirming}
        documentKinds={documentKinds}
        onCancel={() => setConfirming(null)}
        onConfirm={(id, kind, values) => {
          setConfirming(null)
          confirm(id, kind, values)
        }}
      />
      <RemoveSheet
        document={removing}
        onCancel={() => setRemoving(null)}
        onConfirm={(id) => {
          setRemoving(null)
          remove(id)
        }}
      />
    </div>
  )
}

/**
 * 서류 한 줄. 배지는 셋이다 — 서버가 확인이 필요하다고 한 서류는 "확인 필요", 마지막 점검이
 * 통과했으면 "점검 완료", 그 밖에는 "보관 중".
 */
function DocumentRow({
  document,
  check,
  onRemove,
  onConfirm,
}: {
  document: DocumentView
  check: DocumentCheckView | null
  onRemove: () => void
  onConfirm: () => void
}) {
  // 확인이 필요한 서류는 배지가 곧 확인하러 가는 버튼이다. 확인하기 전에는 점검이 끝나지 않는다(#159)
  const badge = document.needsConfirmation ? (
    <button
      type="button"
      aria-label={`${document.kindLabel} 확인하기`}
      onClick={onConfirm}
      className="shrink-0 cursor-pointer rounded-md focus-visible:outline-2 focus-visible:outline-stroke-brand-solid"
    >
      <Badge tone="critical">확인하기</Badge>
    </button>
  ) : check?.status === 'COMPLETE' ? (
    <Badge tone="brand">점검 완료</Badge>
  ) : (
    <Badge>보관 중</Badge>
  )

  return (
    <li className="flex items-center gap-3 py-3">
      <span
        aria-hidden="true"
        className="grid size-11 shrink-0 place-items-center rounded-xl bg-bg-neutral-weak text-fg-neutral-muted"
      >
        <IconDocumentLine size={22} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-17 font-bold">{document.kindLabel}</span>
        <span className="mt-0.5 block truncate text-14 text-fg-neutral-muted">{document.filename}</span>
      </span>
      {badge}
      <button
        type="button"
        aria-label={`${document.kindLabel} 빼기`}
        onClick={onRemove}
        className="grid size-10 shrink-0 cursor-pointer place-items-center rounded-lg text-fg-neutral-subtle active:bg-bg-transparent-pressed"
      >
        <IconTrashcanLine size={20} aria-hidden="true" />
      </button>
    </li>
  )
}

/**
 * 확인이 필요한 서류의 종류와 값을 사장님이 확인하는 시트.
 *
 * 사진이나 글자 인식으로 읽은 서류는 리본이 확신하지 못해, 사장님이 확인해야 점검이 끝난다(#159).
 * 종류를 모르면 골라야 넘어간다. 값은 **서버가 꺼낸 칸만** 보여주고 고치게 한다 — 어떤 서류에 어떤
 * 값이 필요한지는 점검 규칙이 아는 것이라 FE가 칸을 늘리지 않는다(11/03 시우님).
 *
 * 빈 칸으로는 보내지 않는다. 서버는 받은 값을 사장님이 확인한 값으로 저장해서, 빈 값이 맞는 값으로
 * 남는다.
 */
export function ConfirmSheet({
  document,
  documentKinds,
  onCancel,
  onConfirm,
}: {
  document: DocumentView | null
  documentKinds: DocumentsView['documentKinds']
  onCancel: () => void
  onConfirm: (id: string, kind: string, values: Record<string, string>) => void
}) {
  const kindKnown = documentKinds.some((option) => option.kind === document?.kind)
  const [kind, setKind] = useState(kindKnown && document ? document.kind : '')
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries((document?.fields ?? []).map((field) => [field.name, field.value])),
  )
  const kindId = useId()

  // 보이는 칸만 본다. 안 보이는 칸이 비어 있으면 사장님은 왜 버튼이 잠겼는지 알 수 없다
  const filled = (document?.fields ?? [])
    .filter((field) => field.label !== null)
    .every((field) => (values[field.name] ?? '').trim().length > 0)
  const ready = document !== null && kind !== '' && filled

  return (
    <BottomSheet
      open={document !== null}
      onClose={onCancel}
      title="서류 확인하기"
      description={document ? `${document.filename} · 리본이 읽은 내용이 맞는지 봐 주세요.` : undefined}
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (!ready) return
          onConfirm(
            document.id,
            kind,
            Object.fromEntries(Object.entries(values).map(([name, value]) => [name, value.trim()])),
          )
        }}
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor={kindId} className="text-15 font-medium text-fg-neutral-muted">
            서류 종류
          </label>
          {/*
            브라우저가 그리는 화살표는 칸 끝에 붙어 여백으로 옮길 수 없다. 그것을 숨기고(`appearance-none`)
            로드맵 단계와 같은 화살표를 안쪽에 둔다
          */}
          <div className="relative">
            <select
              id={kindId}
              value={kind}
              onChange={(event) => setKind(event.target.value)}
              className="h-13 w-full cursor-pointer appearance-none rounded-xl bg-bg-layer-default pr-11 pl-3 text-17 ring-1 ring-stroke-neutral-weak ring-inset"
            >
              <option value="" disabled>
                종류를 골라 주세요
              </option>
              {documentKinds.map((option) => (
                <option key={option.kind} value={option.kind}>
                  {option.label}
                </option>
              ))}
            </select>
            <IconChevronDownLine
              size={20}
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 right-4 -translate-y-1/2 text-fg-neutral-subtle"
            />
          </div>
        </div>

        {/* 이름을 모르는 칸은 보여주지 않지만 `values` 에는 남아 원래 값 그대로 같이 보낸다 */}
        {document?.fields.map(
          (field) =>
            field.label !== null && (
              <FieldInput
                key={field.name}
                label={field.label}
                value={values[field.name] ?? ''}
                onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))}
              />
            ),
        )}

        <Button type="submit" disabled={!ready}>
          맞아요, 확인했어요
        </Button>
      </form>
    </BottomSheet>
  )
}

/** 꺼낸 값 하나를 고치는 칸. 글자는 17px — 16px보다 작으면 iOS Safari가 포커스할 때 화면을 키운다 */
function FieldInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const id = useId()
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-15 font-medium text-fg-neutral-muted">
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-13 rounded-xl px-3 text-17 ring-1 ring-stroke-neutral-weak ring-inset"
      />
    </div>
  )
}

/**
 * 빼기 전에 묻는 시트.
 *
 * 줄 끝의 휴지통은 스크롤하다 잘못 누르기 쉬운 자리이고, 서버에서 지운 서류는 되돌릴 API 가
 * 없다(#159 `DELETE`). 무엇을 빼는지 종류 이름과 파일 이름으로 보여주고 한 번 더 묻는다.
 */
function RemoveSheet({
  document,
  onCancel,
  onConfirm,
}: {
  document: DocumentView | null
  onCancel: () => void
  onConfirm: (id: string) => void
}) {
  return (
    <BottomSheet
      open={document !== null}
      onClose={onCancel}
      title="이 서류를 뺄까요?"
      description={document ? `${document.kindLabel} · ${document.filename}` : undefined}
    >
      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onCancel}>
          그대로 두기
        </Button>
        <Button className="flex-1" onClick={() => document && onConfirm(document.id)}>
          빼기
        </Button>
      </div>
    </BottomSheet>
  )
}

/** 올리기 중 · 실패 안내 */
function ActionNotice({ action }: { action: DocumentAction }) {
  switch (action) {
    case 'IDLE':
      return null
    // 서류 한 장에 수십 초가 걸릴 수 있다(#159). 멈춘 줄 알고 다시 올리지 않게 기다리는 중임을 알린다
    case 'UPLOADING':
      return (
        <div className="flex items-center gap-3 rounded-2xl bg-bg-neutral-weak px-4 py-3.5">
          <HammerLoader size={28} label="서류를 읽는 중" />
          <p className="text-15">리본이 서류를 읽고 나누는 중이에요. 시간이 조금 걸릴 수 있어요.</p>
        </div>
      )
    case 'TOO_LARGE':
      return (
        <InfoBox tone="critical" title="파일이 너무 커요.">
          20MB 이하의 파일을 올려 주세요.
        </InfoBox>
      )
    // 서버는 끊긴 뒤에도 읽기를 마치고 저장해 둔다. 같은 파일을 다시 올리면 저장된 결과를 쓴다(#159)
    case 'TIMED_OUT':
      return (
        <InfoBox tone="critical" title="읽는 데 시간이 오래 걸려 기다림이 끊겼어요.">
          같은 파일을 한 번 더 올려 주시면 이어서 받아요.
        </InfoBox>
      )
    case 'UNREADABLE':
      return (
        <InfoBox tone="critical" title="서류를 읽지 못했어요.">
          잠시 뒤 다시 올려 주세요. 사진이면 글자가 잘 보이게 다시 찍어 주세요.
        </InfoBox>
      )
    case 'REJECTED':
      return (
        <InfoBox tone="critical" title="이 파일은 올릴 수 없어요.">
          비어 있거나 받을 수 없는 파일이에요. 사진이나 PDF로 다시 골라 주세요.
        </InfoBox>
      )
    // 같은 파일은 다시 올려도 같은 판정이라 "다시 올려 주세요"를 쓰지 않는다
    case 'SAFETY_BLOCKED':
      return (
        <InfoBox tone="critical" title="이 파일은 자동으로 읽지 않았어요.">
          폐업 서류와 관계없는 내용이나 처리할 수 없는 요청이 들어 있을 수 있어요. 같은 파일을 다시 올리지 마시고, 서류
          내용을 확인한 뒤 다른 파일로 올려 주세요.
        </InfoBox>
      )
    // 위기 신호로 판정된 경우. 폐업 절차보다 사람을 먼저 챙기고, 공식 상담 번호만 알린다(상담은 우리가 하지 않는다).
    // 번호 이름은 부정적으로 읽히지 않게 줄여 쓰고, 번호 자체는 빼지 않는다(#228)
    case 'CRISIS_SUPPORT':
      return (
        <InfoBox tone="neutral" title="지금 많이 힘드시다면, 혼자 견디지 않으셔도 돼요.">
          폐업 준비는 잠시 멈춰도 괜찮아요. 올려 두신 서류와 진행 상황은 그대로 남아 있어요. 언제든 힘들면{' '}
          <a href="tel:109" className="font-semibold underline">
            상담전화 109
          </a>
          (24시간),{' '}
          <a href="tel:15770199" className="font-semibold underline">
            정신건강 상담전화 1577-0199
          </a>
          로 연락해 주세요.
        </InfoBox>
      )
    case 'UPLOAD_FAILED':
      return (
        <InfoBox tone="critical" title="서류를 올리지 못했어요.">
          연결이 불안정했을 수 있어요. 같은 파일을 다시 올려 주세요.
        </InfoBox>
      )
    case 'CHANGE_FAILED':
      return (
        <InfoBox tone="critical" title="바꾼 내용을 저장하지 못했어요.">
          서류함은 그대로예요. 잠시 뒤 다시 해 주세요.
        </InfoBox>
      )
  }
}

/**
 * 올리기 시트 (시안 "서류 첨부하기"). 셋 다 진짜 파일 고르기다.
 *
 * 시안의 "시연용 서류" 줄은 두지 않는다 — 가짜 서류를 진짜처럼 올리는 길이 된다.
 * 한 장씩 받는다. 서버가 여러 장 한 번에 받는 길은 열지 않았다(#159).
 */
function UploadSheet({
  open,
  onClose,
  onPicked,
}: {
  open: boolean
  onClose: () => void
  onPicked: (file: File) => void
}) {
  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // 같은 파일을 다시 골라도 바뀐 것으로 잡히게 비운다
    event.target.value = ''
    if (file) onPicked(file)
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="서류 올리기" description="사진이나 PDF를 한 장씩 올려 주세요.">
      <div className="flex flex-col">
        <PickOption icon={<IconCameraLine size={22} />} label="카메라로 찍기">
          <input type="file" accept="image/*" capture="environment" className="sr-only" onChange={handleChange} />
        </PickOption>
        <PickOption icon={<IconPictureLine size={22} />} label="앨범에서 고르기">
          <input type="file" accept="image/*" className="sr-only" onChange={handleChange} />
        </PickOption>
        <PickOption icon={<IconDocumentLine size={22} />} label="파일에서 고르기">
          <input type="file" accept="application/pdf,image/*" className="sr-only" onChange={handleChange} />
        </PickOption>
      </div>
    </BottomSheet>
  )
}

/** 고르기 한 줄. `<label>` 이 숨긴 파일 입력을 감싸, 줄을 누르면 파일 고르기가 열린다 */
function PickOption({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <label className="press-scale flex min-h-14 cursor-pointer items-center gap-3 rounded-xl px-1 text-17 font-medium active:bg-bg-transparent-pressed">
      <span aria-hidden="true" className="text-fg-neutral-muted">
        {icon}
      </span>
      {label}
      {children}
    </label>
  )
}
