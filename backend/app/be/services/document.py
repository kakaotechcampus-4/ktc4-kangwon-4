"""서류 올리기·확인·점검·제출 파일. 실제 처리는 #128의 DocumentTool이 하고, 여기는 Case와 저장만 맡는다.

DocumentTool은 저장을 호출자에게 맡긴다(tool.py 첫 줄). 서류 원본과 가린 PDF를 이미
`AGENT_DOCUMENT_DIR/<Case UUID>/` 폴더에 두므로, Case별 목록·점검 결과도 그 폴더의
JSON 파일 하나에 둔다. DB 테이블을 늘리지 않아 배포 DB를 초기화하지 않아도 된다(발표 전 결정).
"""

import logging
import os
from datetime import date
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlmodel import Session

from app.agent.document_tool.documents import DocumentError
from app.agent.document_tool.models import DocumentContext, DocumentFieldName, DocumentKind
from app.agent.document_tool.safety import SafetyBlockedError
from app.agent.document_tool.tool import DocumentTool
from app.be.crud import case as case_crud
from app.be.crud import case_document_history as case_document_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.models.case import Case
from app.be.models.case_document_history import CaseDocumentHistory
from app.be.models.case_history import CaseHistory
from app.common.agent_dto import document_replan_text

logger = logging.getLogger(__name__)

CONTEXT_FILE = "case_documents.json"
# 마지막으로 판단에 넘긴 서류. 지금 서류와 비교해 판단에 아직 안 넘긴 원상복구 조항이 있는지 본다.
JUDGED_CONTEXT_FILE = "judged_documents.json"
MAX_UPLOAD_BYTES = 20_000_000


def document_directory() -> Path:
    return Path(os.environ.get("AGENT_DOCUMENT_DIR") or Path.home() / ".cache/reborn/documents")


def document_case_id(case: Case) -> UUID:
    # 도구는 Case를 UUID로 나눈다. dev는 서버를 켤 때마다 표를 지워 Case 번호가 1부터
    # 다시 시작하므로, 가입 시각까지 섞어 예전 Case의 서류 폴더를 다시 쓰지 않게 한다.
    return uuid5(NAMESPACE_URL, f"reborn-case:{case.id}:{case.created_at.isoformat()}")


def load_context(directory: Path, case: Case) -> DocumentContext:
    path = directory / str(document_case_id(case)) / CONTEXT_FILE
    if path.is_file():
        context = DocumentContext.model_validate_json(path.read_bytes())
    else:
        context = DocumentContext(case_id=document_case_id(case))
    # 가게 이름은 점검에서 서류의 상호·공급받는 자와 맞춰 보는 기준이다. 가입 뒤 바뀔 수 있어
    # 저장해 둔 값을 믿지 않고 매번 Case에서 다시 채운다. 신청인 이름·실제 폐업일은 점검 요청 때 받는다.
    context.business_name = case.store_name
    return context


def save_context(directory: Path, context: DocumentContext, filename: str = CONTEXT_FILE) -> None:
    path = directory / str(context.case_id) / filename
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(context.model_dump_json(), encoding="utf-8")
    pending.replace(path)


# 안전 검사가 막은 서류. 같은 파일은 다시 올려도 같은 판정이라(retryable=False) "다시 올려 주세요"를 쓰지 않는다.
# 화면 문구는 FE(DocsPage)가 code를 보고 정한다. 위기 판정이면 상담 창구를 안내한다.
_SAFETY_MESSAGES = {
    "AGENT_SAFETY_REFUSE": "이 파일은 자동으로 읽지 않았어요. 서류 내용을 확인한 뒤 다른 파일로 올려 주세요.",
    "AGENT_SAFETY_CRISIS_SUPPORT": "폐업 준비는 잠시 멈춰도 괜찮아요. 힘들 땐 언제든 상담전화 109(24시간)에 연락해 보세요.",
}


def _rejected(error: DocumentError) -> HTTPException:
    # DocumentError 문구는 사장님에게 보여 줄 말로 쓰여 있어(예: "현재 Case의 문서가 아닙니다") 그대로 넘긴다
    return HTTPException(status_code=422, detail=str(error))


async def upload_document(
    session: Session, tool: DocumentTool, directory: Path, case: Case,
    filename: str, content: bytes, kind: DocumentKind | None,
) -> DocumentContext:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="20MB 이하의 파일을 올려 주세요.")
    context = load_context(directory, case)
    try:
        updated = await tool.add_document(context, filename, content, kind_hint=kind)
    except DocumentError as error:
        raise _rejected(error) from None
    except SafetyBlockedError as error:
        logger.warning("서류 안전 검사 차단: %s", error.code)
        raise HTTPException(status_code=422, detail={
            "code": error.code, "message": _SAFETY_MESSAGES.get(error.code, _SAFETY_MESSAGES["AGENT_SAFETY_REFUSE"]),
        }) from None
    except Exception:  # noqa: BLE001 - 모델·OCR 실패. 제공자 응답 본문을 사장님에게 보이지 않는다
        logger.exception("서류 처리 실패")
        raise HTTPException(status_code=502, detail="서류를 읽지 못했어요. 잠시 뒤 다시 올려 주세요.") from None
    # 모델을 기다리는 동안 삭제·확인·다른 업로드가 끝날 수 있다. 저장 구간만 Case로
    # 줄 세우고, 이번 분석이 바꾼 문서만 최신 목록에 합친다. 그사이 바뀐 문서는 보존한다.
    session.refresh(case, with_for_update=True)
    current = load_context(directory, case)
    before = {document.document_id: document for document in context.documents}
    records = {document.document_id: document for document in current.documents}
    changed = False
    for document in updated.documents:
        previous = before.get(document.document_id)
        if document == previous or records.get(document.document_id) != previous:
            continue
        records[document.document_id] = document
        changed = True
        if previous is None:
            case_document_history_crud.create_case_document_history(
                session,
                CaseDocumentHistory(case_id=case.id, action="UPLOADED", document_kind=document.analysis.kind),
            )
    if changed:
        current.documents = list(records.values())
        current.document_check = None
    save_context(directory, current)
    session.commit()
    return current


def confirm_document(
    session: Session, tool: DocumentTool, directory: Path, case: Case, document_id: UUID,
    kind: DocumentKind, confirmed_fields: dict[DocumentFieldName, str],
) -> DocumentContext:
    session.refresh(case, with_for_update=True)
    try:
        updated = tool.confirm_document(
            load_context(directory, case), document_id, kind, confirmed_fields=confirmed_fields,
        )
    except DocumentError as error:
        raise _rejected(error) from None
    save_context(directory, updated)
    session.commit()
    return updated


def remove_document(session: Session, tool: DocumentTool, directory: Path, case: Case, document_id: UUID) -> DocumentContext:
    session.refresh(case, with_for_update=True)
    try:
        updated = tool.remove_document(load_context(directory, case), document_id)
    except DocumentError as error:
        raise _rejected(error) from None
    save_context(directory, updated)
    session.commit()
    return updated


def check_documents(
    session: Session, tool: DocumentTool, directory: Path, case: Case, applicant_name: str, closure_date: date | None,
    *, store_name: str | None = None,
) -> DocumentContext:
    session.refresh(case, with_for_update=True)
    # 서류에서 읽은 상호로 덮어쓰지 않는다. 사장님이 이 요청에 직접 보낸 이름만 저장한다.
    if store_name is not None:
        case.store_name = store_name
        session.add(case)
    # #251 순차 배포 중 구형 화면은 이름을 보내지 않는다. 기존 점검의 미확인 안내를 유지한다.
    context = load_context(directory, case)
    # 이체확인증의 보낸 사람과 맞춰 볼 신청인 이름은 서비스가 받는 칸이 없어 점검 직전에 사장님께 묻는다.
    # 폐업사실증명원과 맞춰 볼 폐업일은 사장님이 실제 날짜라고 확인한 값만 쓴다.
    # 가입 때 정한 폐업 예정일(planned_closure_date)은 실제 폐업일과 다른 사실이라 대신 쓰지 않는다.
    # 비우면 점검이 CLOSURE_DATE_UNCONFIRMED로 막는다.
    # 둘 다 서류 JSON에만 남기고 Case·AI 판단에는 넣지 않는다.
    context.applicant_name = applicant_name
    context.closure_date = closure_date
    try:
        updated = tool.check_documents(context)
    except DocumentError as error:
        raise _rejected(error) from None
    save_context(directory, updated)

    # 기록 탭 문구가 "점검하고 제출 파일을 만들었어요"라 통과한 점검만 남긴다.
    # 서류를 바꾸지 않고 다시 눌러 통과한 것은 남기지 않는다. 서류가 바뀌면 지난 점검이 지워진다.
    passed_before = context.document_check is not None and context.document_check.status == "COMPLETE"
    if not passed_before and updated.document_check is not None and updated.document_check.status == "COMPLETE":
        case_document_history_crud.create_case_document_history(
            session, CaseDocumentHistory(case_id=case.id, action="CHECKED"),
        )
    # 점검이 누락·불일치로 끝나도 직접 입력한 이름은 재접속 때 다시 보여 준다.
    session.commit()
    return updated


def queue_document_judgment(session: Session, directory: Path, case: Case) -> int | None:
    """판단에 아직 안 넘긴 원상복구 조항이 있으면 판단 이력을 PENDING으로 남기고 그 번호를 돌려준다.

    지금 서류를 "마지막으로 판단에 넘긴 서류"(JUDGED_CONTEXT_FILE)와 비교한다(document_replan_text).
    같은 조항의 재업로드·금액 서류 추가·서류 빼기는 None이라 판단하지 않는다.
    판단할 수 없는 상태라 건너뛰면 기준을 옮기지 않으므로, 진행 중인 판단이나 충돌 확인이
    끝날 때 queue_owed_document_judgment가 같은 비교로 다시 판단을 넣는다.
    판단을 부르는 일은 호출한 쪽이 한다. 결과는 홈(GET /cases)이 PENDING을 보고 다시 묻는다.
    """

    # 판단할 조항이 없으면 DB를 건드리지 않는다. 금액 서류만 올릴 때마다 Case를 잠그지 않게 한다.
    if _pending_replan_text(directory, case) is None:
        return None
    member_id = case.member_id

    # 라우터는 서류 처리(OCR)를 기다리기 전에 Case를 읽는다. MySQL은 한 트랜잭션 안에서 처음
    # 읽은 시점을 계속 보여 주고, 이미 읽은 Case 객체도 저절로 다시 읽지 않는다. 그 사이 다른
    # 요청이 PENDING을 넣거나 Case를 완료로 바꿔도 못 보므로, 여기서 트랜잭션을 끝내고 새로 잠근다.
    # (commit하면 세션이 들고 있던 객체도 버려져 잠금 조회가 최신 값을 읽는다.)
    session.commit()

    # 결과 제출(case.submit_case_results)과 같은 이유로 Case를 잠그고 확인한다.
    # 같은 Case에 PENDING이 둘 생기면 판단이 서로의 결과를 덮는다.
    case = case_crud.lock_case_by_member_id(session, member_id)
    blocked = _judgment_blocked_reason(session, case)
    if blocked is not None:
        logger.info("Case %s 서류 재판단 미룸: %s", case.id if case else None, blocked)
        session.rollback()
        return None

    # 잠근 뒤 다시 본다. 기다리는 사이 다른 요청이 같은 서류로 판단을 넣었으면 기준이 옮겨져 있다.
    context = load_context(directory, case)
    text = _pending_replan_text(directory, case, context)
    if text is None:
        session.rollback()
        return None

    history = case_history_crud.create_case_history(
        session,
        CaseHistory(case_id=case.id, raw_input=text, source="DOCUMENT_SUBMITTED", judgment_status="PENDING"),
    )
    # 기준 파일과 PENDING 이력은 같이 남거나 같이 없어야 한다. PENDING만 남으면 실행할 작업 없이
    # 홈이 계속 "판단 중"이고, 기준만 옮겨지면 이 서류가 판단에서 빠진다(#173 리뷰).
    # 그래서 이력을 확정하기 전에 기준을 먼저 쓰고, 확정이 실패하면 기준을 되돌린다.
    judged_path = _judged_context_path(directory, case)
    previous_judged = judged_path.read_bytes() if judged_path.is_file() else None
    try:
        save_context(directory, context, JUDGED_CONTEXT_FILE)
    except OSError:
        # 서류는 이미 저장됐다. 판단할 수 없을 때처럼 이번 판단만 미룬다. 기준이 그대로라
        # 다음 업로드나 다음 판단이 끝날 때 다시 시도한다.
        logger.exception("Case %s 서류 판단 기준 저장 실패, 판단을 미룸", case.id)
        session.rollback()
        return None
    try:
        session.commit()
    except Exception:
        _restore_judged_context(judged_path, previous_judged)
        raise
    return history.id


def queue_owed_document_judgment(session: Session, directory: Path, case_history_id: int) -> int | None:
    """판단(case_history_id)이 끝난 뒤, 그동안 판단에 못 넘긴 서류가 있으면 판단을 넣는다.

    판단 중이거나 충돌 확인을 기다리는 동안 올린 서류는 저장만 되고 판단은 미뤄진다.
    그 서류가 빠지지 않게 판단·충돌 확인이 끝날 때마다 여기를 부른다(#173 리뷰).
    """

    history = case_history_crud.get_case_history_by_id(session, case_history_id)
    case = case_crud.get_case_by_id(session, history.case_id) if history is not None else None
    if case is None:
        return None
    return queue_document_judgment(session, directory, case)


def _pending_replan_text(directory: Path, case: Case, context: DocumentContext | None = None) -> str | None:
    """판단에 아직 안 넘긴 원상복구 조항이 있으면 판단 글, 없으면 None."""

    current = context if context is not None else load_context(directory, case)
    return document_replan_text(_load_judged_context(directory, case), current)


def _judged_context_path(directory: Path, case: Case) -> Path:
    return directory / str(document_case_id(case)) / JUDGED_CONTEXT_FILE


def _load_judged_context(directory: Path, case: Case) -> DocumentContext | None:
    # 없으면 서류로 판단한 적이 없다는 뜻이라, 지금 서류의 조항을 전부 새 값으로 본다
    path = _judged_context_path(directory, case)
    return DocumentContext.model_validate_json(path.read_bytes()) if path.is_file() else None


def _restore_judged_context(path: Path, previous: bytes | None) -> None:
    # 판단 이력 확정이 실패했을 때 기준을 쓰기 전으로 돌린다. 그래야 이 서류가 다음에 다시 판단된다.
    try:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(previous)
    except OSError:
        logger.exception("서류 판단 기준 되돌리기 실패: %s", path)


def _judgment_blocked_reason(session: Session, case: Case | None) -> str | None:
    """지금 판단을 새로 돌릴 수 없으면 그 이유. 결과 제출이 409로 막는 경우와 같다."""

    if case is None:
        return "Case 없음"
    if case.case_status == "COMPLETED":
        return "폐업 정리를 마친 Case"
    if conflict_reference_crud.get_pending_conflicts_by_case_id(session, case.id):
        return "확인 대기 중인 충돌"
    latest = case_history_crud.get_latest_user_driven_case_history(session, case.id)
    if latest is not None and latest.judgment_status == "PENDING":
        return "직전 판단 처리 중"
    return None


def settlement_zip(tool: DocumentTool, directory: Path, case: Case) -> bytes:
    try:
        return tool.prepare_settlement(load_context(directory, case))
    except DocumentError as error:
        raise _rejected(error) from None
