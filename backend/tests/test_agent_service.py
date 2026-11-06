"""The BE-callable entry points, which BE wires a Case into.

These are the functions BE calls; nothing else in the suite covers them, so a
signature change here would otherwise only surface once BE is wired up. No
database, no provider: BE rows are built in memory and the runtime is replaced.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.agent.action_catalog import resolve_procedure_bindings
from app.agent.document_tool.models import (
    DocumentAnalysis,
    DocumentKind,
    DocumentRecord,
    ExtractedField,
)
from app.agent.guardrails import GuardrailViolation
from app.agent.procedure_tool.store import ProcedureStoreError
from app.agent.schemas import ProcedureStepRef
from app.agent.support_agent import ReviewedSupportCatalog
from app.be.models.procedure_step import ProcedureStep, StepDependency
from app.common.agent_data import (
    InMemoryReviewedProcedureStore,
    build_known_procedure_steps,
    load_reviewed_procedures,
)
from app.common.agent_dto import (
    CaseSnapshot, DocumentContext, RedactedInput, RestorationAnswer, document_input_text, document_replan_text,
)
from app.common.agent_service import (
    build_conflict_input,
    build_planning_input,
    run_case_planning,
)
from scripts import import_reviewed_procedures as import_cli

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
REF = "synthetic-document"


def row(step_id, step_code, **changes):
    return ProcedureStep(
        id=step_id,
        step_code=step_code,
        step_name="합성 절차",
        registry_version="synthetic/1",
        **changes,
    )


def known(*steps, dependencies=(), db_timezone=SEOUL):
    return build_known_procedure_steps(
        list(steps), list(dependencies), [], db_timezone=db_timezone
    )


def redacted_input(**changes):
    return RedactedInput.model_validate({
        "input_event_id": "evt-1",
        "source_type": "USER_INPUT",
        "redacted_text": "가게를 정리하려고 합니다.",
        "redactions": [],
        "submitted_at": NOW,
        **changes,
    })


def case_snapshot():
    return CaseSnapshot.model_validate({
        "snapshot_id": UUID(int=1),
        "case_id": 1,
        "case_status": "IN_PROGRESS",
        "facts": [
            {
                "field_path": name,
                "value_type": kind,
                "value": value,
                "status": "CONFIRMED",
                "evidence_refs": [REF],
                "updated_at": NOW,
            }
            for name, kind, value in (
                ("business_type", "STRING", "카페"),
                ("franchise_status", "BOOLEAN", False),
                ("lease_status", "ENUM", "LEASED_PAID"),
            )
        ],
        "procedure_progress": [],
        "evidence_records": [
            {
                "evidence_id": REF,
                "source_type": "OFFICIAL_DOCUMENT",
                "source_ref": "https://example.org/synthetic",
                "source_version": None,
                "locator": None,
                "excerpt": "합성 발췌",
                "published_at": None,
                "retrieved_at": NOW,
                "freshness_status": "CURRENT",
                "content_hash": None,
                "parent_evidence_refs": [],
            }
        ],
        "captured_at": NOW,
    })


# 1. Bindings. BE's step_code is its own ("BUSINESS_CLOSURE_REPORT"), so the
# mapping is supplied, never guessed from a name or alias.
def test_restoration_answer_requires_matching_text_and_result_trigger():
    from app.agent.schemas import canonical_digest

    answer = RestorationAnswer(restoration_scope="PARTIAL", demolition_required="NOT_REQUIRED")
    request = build_planning_input(trigger_type="RESULT_SUBMITTED", case_snapshot=case_snapshot(),
                                   user_input=redacted_input(redacted_text=answer.to_input_text()),
                                   restoration_answer=answer)
    assert request.trigger.restoration_answer == answer
    assert request.model_dump()["trigger"]["restoration_answer"] == answer.model_dump()
    assert canonical_digest(request.trigger) != canonical_digest(request.trigger.model_copy(update={"restoration_answer": None}))
    with pytest.raises(ValidationError, match="exact USER_INPUT text"):
        build_planning_input(trigger_type="RESULT_SUBMITTED", case_snapshot=case_snapshot(),
                             user_input=redacted_input(), restoration_answer=answer)
    with pytest.raises(ValueError, match="requires RESULT_SUBMITTED"):
        build_planning_input(trigger_type="CASE_CREATED", case_snapshot=case_snapshot(),
                             user_input=redacted_input(), restoration_answer=answer)


def test_restoration_answer_absence_keeps_legacy_serialization_unchanged():
    from pydantic import create_model
    from app.agent.schemas import AgentSchema, ResultSubmittedTrigger, canonical_digest

    request = build_planning_input(trigger_type="RESULT_SUBMITTED", case_snapshot=case_snapshot(),
                                   user_input=redacted_input())
    assert "restoration_answer" not in request.model_dump()["trigger"]
    assert "restoration_answer" not in request.model_dump(mode="json")["trigger"]
    legacy_type = create_model("LegacyResultSubmittedTrigger", __base__=AgentSchema, **{
        name: (field.annotation, field) for name, field in ResultSubmittedTrigger.model_fields.items()
        if name != "restoration_answer"
    })
    legacy = legacy_type.model_validate(request.trigger.model_dump())
    assert canonical_digest(request.trigger) == canonical_digest(legacy)


def test_bindings_reject_one_step_bound_twice():
    steps = known(row(11, "TAX_CLOSE_V2"))
    ref = ProcedureStepRef(procedure_step_id=11, step_code="TAX_CLOSE_V2")

    with pytest.raises(ValueError, match="multiple logical bindings"):
        resolve_procedure_bindings(
            steps,
            {"FILE_TAX_BUSINESS_CLOSURE": ref, "FILE_FOOD_SERVICE_CLOSURE": ref},
        )


def test_bindings_reject_a_logical_code_the_agent_does_not_define():
    steps = known(row(11, "TAX_CLOSE_V2"))
    ref = ProcedureStepRef(procedure_step_id=11, step_code="TAX_CLOSE_V2")

    with pytest.raises(ValueError, match="unknown logical procedure binding codes"):
        resolve_procedure_bindings(steps, {"FILE_TAX_BUSINES_CLOSURE": ref})


def test_bindings_reject_a_step_that_was_not_loaded():
    steps = known(row(11, "TAX_CLOSE_V2"))

    with pytest.raises(ValueError, match="unknown id\\+code"):
        resolve_procedure_bindings(
            steps,
            {
                "FILE_TAX_BUSINESS_CLOSURE": ProcedureStepRef(
                    procedure_step_id=12, step_code="TAX_CLOSE_V2"
                )
            },
        )


# 2. Registry adapter. The columns return naive datetimes, so the caller states
# the timezone and this must not guess UTC or the host zone.
def test_naive_deprecated_at_takes_the_declared_db_timezone():
    naive = datetime(2026, 9, 29, 10, 0)  # noqa: DTZ001 — 컬럼이 돌려주는 모양

    steps = known(row(11, "TAX_CLOSE_V2", deprecated_at=naive))

    assert steps[0].deprecated_at == naive.replace(tzinfo=SEOUL)
    assert steps[0].deprecated_at.utcoffset().total_seconds() == 9 * 3600


def test_db_timezone_must_be_a_tzinfo_not_its_name():
    with pytest.raises(TypeError, match="explicit datetime.tzinfo"):
        known(row(11, "TAX_CLOSE_V2"), db_timezone="Asia/Seoul")


def test_dependency_pointing_at_an_unloaded_step_is_rejected():
    dependency = StepDependency(
        procedure_step_id=11,
        prerequisite_procedure_step_id=99,
        dependency_type="REQUIRES",
    )

    with pytest.raises(ValueError, match="references unloaded procedure step 99"):
        known(row(11, "TAX_CLOSE_V2"), dependencies=[dependency])


# 3. Input assembly. Reject what MySQL would reject, while a retry is possible.
@pytest.mark.parametrize("invalid", ["creation", "unredacted_original"])
def test_completion_confirmation_keeps_the_result_input_boundary(invalid):
    from test_info_replanning import completion_confirmation_request, completion_report_graph

    graph, request = completion_report_graph("기관 처리 완료를 확인했습니다.")
    pending = asyncio.run(graph.run(request))
    choice = completion_confirmation_request(request, pending, True)
    confirmation = choice.trigger.procedure_completion_confirmation
    if invalid == "unredacted_original":
        confirmation.input.redacted_text += " 연락처는 010-1234-5678입니다."
    error = ValueError if invalid == "creation" else GuardrailViolation
    match = "RESULT_SUBMITTED" if invalid == "creation" else "PHONE_NUMBER"
    with pytest.raises(error, match=match):
        build_planning_input(
            trigger_type="CASE_CREATED" if invalid == "creation" else "RESULT_SUBMITTED",
            case_snapshot=choice.case_snapshot,
            user_input=choice.trigger.input,
            procedure_completion_confirmation=confirmation,
        )


def test_planning_input_rejects_a_trace_id_longer_than_its_column():
    with pytest.raises(ValidationError):
        build_planning_input(
            trigger_type="CASE_CREATED",
            case_snapshot=case_snapshot(),
            user_input=redacted_input(),
            trace_id="t" * 101,
        )


def test_planning_input_rejects_an_unredacted_phone_number():
    with pytest.raises(GuardrailViolation, match="PHONE_NUMBER"):
        build_planning_input(
            trigger_type="CASE_CREATED",
            case_snapshot=case_snapshot(),
            user_input=redacted_input(
                redacted_text="임대인(010-1234-5678)에게 물어봤습니다."
            ),
        )


def test_planning_input_rejects_an_unknown_trigger():
    with pytest.raises(ValueError, match="RESULT_SUBMITTED or DOCUMENT_SUBMITTED"):
        build_planning_input(
            trigger_type="CASE_CLOSED",
            case_snapshot=case_snapshot(),
            user_input=redacted_input(),
        )


def test_planning_input_accepts_a_document_upload_as_owner_input():
    request = build_planning_input(
        trigger_type="DOCUMENT_SUBMITTED",
        case_snapshot=case_snapshot(),
        user_input=redacted_input(redacted_text="사장님이 올린 서류에서 꺼낸 내용입니다.\n이체확인증: 3,300,000원"),
    )

    assert request.trigger.trigger_type == "DOCUMENT_SUBMITTED"
    assert request.trigger.input.source_type == "USER_INPUT"


def test_a_document_upload_is_not_recorded_as_an_official_document():
    with pytest.raises(ValidationError, match="USER_INPUT"):
        build_planning_input(
            trigger_type="DOCUMENT_SUBMITTED",
            case_snapshot=case_snapshot(),
            user_input=redacted_input(source_type="EXPERT_CONFIRMATION"),
        )


def document_record(kind, fields, *, needs_confirmation=False, confirmed_fields=None):
    return DocumentRecord(
        document_id=uuid4(), filename="doc.pdf", content_hash="h", redaction_count=0,
        cache_key="c", artifact_hash="a", confirmed_fields=confirmed_fields,
        analysis=DocumentAnalysis(
            kind=kind, needs_confirmation=needs_confirmation,
            fields=[ExtractedField(name=n, value=v, page=1, quote=q) for n, v, q in fields],
        ),
    )


def test_document_text_uses_values_so_names_inside_quotes_stay_out():
    context = DocumentContext(documents=[document_record(DocumentKind.TAX_INVOICE, [
        ("supplier", "가나철거", "공급자 상호 가나철거"),
        # 인용 안에 상호가 같이 들어 있다. 이름 칸만 빼면 이 상호가 그대로 남는다
        ("amount", "3300000", "가나철거 합계금액 3,300,000원"),
    ])])

    text = document_input_text(context)

    assert text == "사장님이 올린 서류에서 꺼낸 내용입니다.\n전자세금계산서 금액: 3300000"
    assert "가나철거" not in text


def test_document_text_leaves_out_dates_so_a_past_closure_is_not_read_as_planned():
    context = DocumentContext(documents=[
        document_record(DocumentKind.CLOSURE_CERTIFICATE, [("closure_date", "2026-11-30", "폐업일 2026.11.30")]),
        document_record(DocumentKind.TRANSFER, [("date", "2026-11-02", "이체일 2026.11.02")],
                        confirmed_fields={"date": "2026-11-03"}),
    ])

    assert document_input_text(context) is None


TAX_INVOICE_FIELDS = [("amount", "3300000", "합계금액 3,300,000원"), ("tax_amount", "300000", "세액 300,000원")]


@pytest.mark.parametrize(("needs_confirmation", "confirmed_fields", "expected"), [
    # 고친 값 목록이 있으면 그 목록만 쓴다. 고치지 않은 세액을 꺼낸 값으로 채우지 않는다
    (True, {"amount": "3500000"}, ["전자세금계산서 금액(사장님 확인): 3500000"]),
    (False, {"amount": "3500000"}, ["전자세금계산서 금액(사장님 확인): 3500000"]),
    # 빈 목록은 "넘길 값 없음"이다. 확인 필요 여부와 상관없이 꺼낸 값으로 돌아가지 않는다
    (False, {}, None),
    (True, {}, None),
    # 목록이 없을 때만 꺼낸 값을 쓰고, 확인이 필요한 서류는 넣지 않는다
    (True, None, None),
    (False, None, ["전자세금계산서 금액: 3300000", "전자세금계산서 세액: 300000"]),
])
def test_document_text_uses_only_the_owner_confirmed_list_when_there_is_one(
    needs_confirmation, confirmed_fields, expected
):
    context = DocumentContext(documents=[document_record(
        DocumentKind.TAX_INVOICE, TAX_INVOICE_FIELDS,
        needs_confirmation=needs_confirmation, confirmed_fields=confirmed_fields,
    )])

    text = document_input_text(context)

    assert text == (None if expected is None else "\n".join(["사장님이 올린 서류에서 꺼낸 내용입니다.", *expected]))
    assert document_input_text(DocumentContext()) is None


def test_document_text_becomes_a_document_submitted_planning_input():
    text = document_input_text(DocumentContext(documents=[
        document_record(DocumentKind.TRANSFER, [("amount", "3300000", "이체금액 3,300,000원")]),
    ]))

    request = build_planning_input(
        trigger_type="DOCUMENT_SUBMITTED",
        case_snapshot=case_snapshot(),
        user_input=redacted_input(redacted_text=text),
    )

    assert request.trigger.input.redacted_text == text


@pytest.mark.parametrize("legacy", [True, False])
def test_public_conflict_input_preserves_legacy_and_batch_choices_without_mutating_source(legacy):
    from test_procedure_only_graph import batch_conflict_graph

    _, source, _, _ = batch_conflict_graph()
    original = source.model_dump_json()
    trigger = source.trigger
    values = {"confirmed_conflict": trigger.conflicts[0]} if legacy else {
        "conflicts": trigger.conflicts, "selections": trigger.selections,
        "conflict_snapshot": trigger.conflict_snapshot,
    }
    request = build_conflict_input(
        case_snapshot=source.case_snapshot, input_event_id="stored-choice", confirmed_at=NOW, **values,
    )
    assert source.model_dump_json() == original
    assert request.case_snapshot == source.case_snapshot
    assert request.case_snapshot is not source.case_snapshot
    assert request.trigger.choices() == (
        [(trigger.conflicts[0], True)] if legacy else trigger.choices()
    )
    assert request.trigger.choices()[0][0] is not trigger.conflicts[0]


# 4. The run itself. The real runtime opens provider clients and a trace sink,
# so it is replaced here; what matters is that the outcome is checked and the
# runtime is always closed, including on the failure path.
class FakeOutcome:
    def __init__(self, outcome_type):
        self.outcome_type = outcome_type
        self.integrity_checked = False

    def assert_integrity(self):
        self.integrity_checked = True


class FakeRuntime:
    def __init__(self, outcome=None, error=None):
        self.outcome = outcome
        self.error = error
        self.closed = False
        self.flushed = False

    async def run_planning(self, request):
        if self.error is not None:
            raise self.error
        return self.outcome

    async def aclose(self):
        self.closed = True

    def flush(self):
        self.flushed = True


def plan_with(runtime, bindings):
    request = build_planning_input(
        trigger_type="CASE_CREATED",
        case_snapshot=case_snapshot(),
        user_input=redacted_input(),
    )

    async def run():
        with patch(
            "app.common.agent_service.build_runtime",
            new=AsyncMock(return_value=runtime),
        ) as build:
            outcome = await run_case_planning(
                request,
                known_procedure_steps=known(row(11, "FILE_TAX_BUSINESS_CLOSURE")),
                procedure_bindings=bindings,
                procedure_store=InMemoryReviewedProcedureStore("synthetic/1", ()),
                support_catalog=ReviewedSupportCatalog.model_validate(
                    {
                        "programs": [],
                        "evidence_records": [],
                        "catalog_version": "synthetic/1",
                    }
                ),
            )
            assert build.await_args.kwargs["procedure_bindings"] is bindings
            return outcome

    return asyncio.run(run())


@pytest.mark.parametrize("bindings", [{}, None])
def test_a_reviewed_plan_is_integrity_checked_before_it_is_returned(bindings):
    outcome = FakeOutcome("REVIEWED_PLAN")
    runtime = FakeRuntime(outcome=outcome)

    assert plan_with(runtime, bindings) is outcome
    assert outcome.integrity_checked
    assert runtime.closed and runtime.flushed


def test_a_safe_failure_is_returned_without_the_reviewed_plan_check():
    outcome = FakeOutcome("SAFE_FAILURE")

    assert plan_with(FakeRuntime(outcome=outcome), {}) is outcome
    assert not outcome.integrity_checked


def test_the_runtime_is_closed_and_flushed_when_planning_raises():
    runtime = FakeRuntime(error=RuntimeError("provider down"))

    with pytest.raises(RuntimeError, match="provider down"):
        plan_with(runtime, {})

    assert runtime.closed and runtime.flushed


@pytest.fixture
def import_cli_context(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["import_reviewed_procedures", "--case-id", "1"])
    monkeypatch.setitem(sys.modules, "app.be.db", SimpleNamespace(get_engine=lambda: object()))
    session = MagicMock()
    session.__enter__.return_value = session
    monkeypatch.setattr(import_cli, "Session", MagicMock(return_value=session))
    store = InMemoryReviewedProcedureStore("synthetic/1", ())
    monkeypatch.setattr(import_cli, "load_reviewed_procedures", MagicMock(return_value=store))
    writer = MagicMock(return_value=[])
    monkeypatch.setattr(import_cli, "import_reviewed_procedures", writer)
    return store, session, writer


def test_import_cli_passes_bundled_store_to_be_and_commits_without_new_column(import_cli_context):
    store, session, writer = import_cli_context
    import_cli.main()
    writer.assert_called_once_with(session, 1, store, as_of=ANY)
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()


def test_import_cli_validates_explicit_source_and_preserves_its_version(
    import_cli_context, monkeypatch, tmp_path,
):
    _, session, writer = import_cli_context
    source = tmp_path / "reviewed.json"
    source.write_text(json.dumps({
        "snapshot_version": "synthetic/2", "generated_at": NOW.isoformat(),
        "locale": "ko-KR", "records": [],
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "import_reviewed_procedures", "--case-id", "1", "--source", str(source),
    ])
    import_cli.main()
    imported_store = writer.call_args.args[2]
    assert imported_store.snapshot_version == "synthetic/2"
    import_cli.load_reviewed_procedures.assert_not_called()
    session.commit.assert_called_once_with()


def test_import_cli_rolls_back_when_be_import_fails(import_cli_context):
    _, session, writer = import_cli_context
    writer.side_effect = ProcedureStoreError("synthetic import failure")
    with pytest.raises(ProcedureStoreError, match="synthetic import failure"):
        import_cli.main()
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()


def test_import_cli_rejects_invalid_source_before_importing_database(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["import_reviewed_procedures", "--case-id", "1"])
    monkeypatch.setitem(sys.modules, "app.be.db", None)
    monkeypatch.setattr(import_cli, "load_reviewed_procedures", MagicMock(
        side_effect=ProcedureStoreError("synthetic invalid source"),
    ))
    with pytest.raises(ProcedureStoreError, match="synthetic invalid source"):
        import_cli.main()


def test_bundled_demolition_support_notice_is_reviewed_for_restoration_work():
    # 철거를 권할 때 근거로 쓸 2026 점포철거비 공고 원문. 사람이 검수한 자료만 AI가 쓴다.
    record = next(
        item for item in load_reviewed_procedures().records()
        if item.record_id == "DEMOLITION_SUPPORT_2026"
    )
    assert record.step_codes == ["PERFORM_RESTORATION"]
    assert record.reviewed_by is not None and record.reviewed_at is not None
    assert "자력철거 시 지원불가" in record.excerpt
    assert "이체확인증" in record.excerpt and "통장 사본" not in record.excerpt


CLAUSE = "원상복구 범위는 카운터·싱크대 부분이다."


def lease(clause=CLAUSE, *, confirmed=True):
    fields = [("restoration_clause", clause, clause)]
    return document_record(DocumentKind.LEASE, fields, needs_confirmation=True,
                           confirmed_fields={"restoration_clause": clause} if confirmed else None)


def test_replan_runs_only_when_a_new_restoration_clause_is_confirmed():
    first = DocumentContext(documents=[lease()])
    text = document_replan_text(DocumentContext(), first)
    assert text is not None and CLAUSE in text
    # 확인 필요 서류를 아직 확인하지 않았으면 부르지 않는다
    assert document_replan_text(DocumentContext(), DocumentContext(documents=[lease(confirmed=False)])) is None


@pytest.mark.parametrize("after_documents", [
    # 같은 조항을 다시 올림
    lambda: [lease(), lease()],
    # 금액 서류만 더함 — 금액 대조는 서류 점검이 한다
    lambda: [lease(), document_record(DocumentKind.TAX_INVOICE, TAX_INVOICE_FIELDS)],
    # 조항 서류를 뺌 — 이미 반영한 사실을 되돌리지 않는다
    lambda: [],
], ids=["same-clause-reupload", "amount-only", "removed"])
def test_replan_is_skipped_when_no_judgment_value_changes(after_documents):
    before = DocumentContext(documents=[lease()])
    assert document_replan_text(before, DocumentContext(documents=after_documents())) is None


def test_replan_runs_again_when_the_confirmed_clause_changes():
    before = DocumentContext(documents=[lease()])
    changed = "원상복구 범위는 전체이며 철거가 필요하다."
    text = document_replan_text(before, DocumentContext(documents=[lease(changed)]))
    assert text is not None and changed in text


def test_amount_only_upload_never_starts_a_judgment():
    after = DocumentContext(documents=[document_record(DocumentKind.TAX_INVOICE, TAX_INVOICE_FIELDS)])
    assert document_input_text(after) is not None  # 글은 만들 수 있어도
    assert document_replan_text(None, after) is None  # 판단은 부르지 않는다
