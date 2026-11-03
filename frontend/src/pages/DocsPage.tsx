import {
  IconCameraLine,
  IconDocumentLine,
  IconDocumentTrayLine,
  IconPictureLine,
  IconPlusLine,
  IconTrashcanLine,
} from '@karrotmarket/react-monochrome-icon'
import { type ChangeEvent, type ReactNode, useState } from 'react'

import { Badge } from '../components/ui/Badge'
import { BottomSheet } from '../components/ui/BottomSheet'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { HammerLoader } from '../components/ui/HammerLoader'
import { InfoBox } from '../components/ui/InfoBox'
import { type DocumentAction, useDocuments } from '../hooks/useDocuments'
import type { DocumentCheckView, DocumentView } from '../types/view'

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
  const { query, action, upload, remove } = useDocuments()
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

  // 서류 API 가 들어오기 전(#159)에는 받을 곳이 없다. 눌리는데 아무 일도 없으면 고장으로 읽혀 꺼 둔다
  if (query.status === 'UNAVAILABLE') {
    return (
      <EmptyState
        icon={<IconDocumentTrayLine size={32} />}
        title="아직 모인 서류가 없어요"
        description={'서류를 받는 기능은 준비 중이에요.\n할 일을 하면서 올린 서류가 여기에 모여요'}
        action={uploadButton}
      />
    )
  }

  const { documents, check } = query.view

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
          <ul className="flex flex-col">
            {documents.map((document) => (
              <DocumentRow key={document.id} document={document} check={check} onRemove={() => setRemoving(document)} />
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

      <div className="mt-auto flex flex-col gap-2">{uploadButton}</div>

      <UploadSheet open={sheetOpen} onClose={() => setSheetOpen(false)} onPicked={handlePicked} />
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
}: {
  document: DocumentView
  check: DocumentCheckView | null
  onRemove: () => void
}) {
  const badge = document.needsConfirmation ? (
    <Badge tone="critical">확인 필요</Badge>
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
    case 'FAILED':
      return (
        <InfoBox tone="critical" title="서류를 올리지 못했어요.">
          잠시 뒤 같은 파일을 다시 올려 주세요.
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
    <label className="flex min-h-14 cursor-pointer items-center gap-3 rounded-xl px-1 text-17 font-medium active:bg-bg-transparent-pressed">
      <span aria-hidden="true" className="text-fg-neutral-muted">
        {icon}
      </span>
      {label}
      {children}
    </label>
  )
}
