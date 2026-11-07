"""The SDK trace ID reaches the existing decision record through real MySQL saves."""

import asyncio
from unittest.mock import patch

import pytest
from sqlmodel import Session, select
from test_procedure_only_graph import graph_run_inputs
from test_action_codes import supervisor_request
from test_tracing import Client

from app.agent.tracing import LangfuseTraceSink
from app.agent.schemas import canonical_digest
from app.be.models.case_history import CaseHistory
from app.be.models.evidence import ConflictReference, DecisionRecord
from app.be.services import conflict_decision, decision_record, judgment
from case_world import case_engine, case_world  # noqa: F401 — isolated MySQL fixtures

TRACE_ID = "ab" * 16


def traced_outcome(case_id, source_trace_ids=None):
    template = supervisor_request()
    # Evidence IDs are globally unique in the real DB; separate each synthetic Case too.
    def own(value):
        return type(value).model_validate_json(value.model_dump_json().replace("synthetic-document", f"synthetic-document-{case_id}"))

    template.case_snapshot = own(template.case_snapshot)
    sources = []
    for source in template.source_results:
        output = own(source.output)
        if source.meta.component == "INFO_AGENT":
            output.based_on_procedure_lookup_digest = sources[0].output_digest
        sources.append(type(source)(meta=source.meta, output=output, output_digest=canonical_digest(output)))
    template.source_results = sources
    with patch("test_procedure_only_graph.supervisor_request", return_value=template):
        graph, request, _, _, _ = graph_run_inputs("RESULT_SUBMITTED")
    request.case_snapshot.case_id = case_id
    graph._trace_sink = LangfuseTraceSink(Client(TRACE_ID))
    if source_trace_ids is not None:
        original_meta = graph._meta

        def meta(*args, **kwargs):
            result = original_meta(*args, **kwargs)
            index = {"PROCEDURE_TOOL": 0, "INFO_AGENT": 1}.get(result.component)
            return result if index is None else result.model_copy(update={"trace_id": source_trace_ids[index]})

        graph._meta = meta
    outcome = asyncio.run(graph.run(request))
    assert outcome.outcome_type == "REVIEWED_PLAN", outcome
    outcome.assert_integrity()
    return outcome


@pytest.mark.parametrize("decision", [False, True], ids=["normal-judgment", "conflict-choice"])
def test_normal_and_conflict_save_paths_store_the_actual_span_id(case_engine, case_world, decision):  # noqa: F811
    _, case_id, _ = case_world.sign_up()
    history_id = case_world.add_history(case_id, "CONFLICT_DECISION" if decision else "USER_INPUT", "PENDING")
    conflict_id = case_world.add_conflict(case_id, history_id) if decision else None
    outcome = traced_outcome(case_id)
    with Session(case_engine) as session:
        if decision:
            conflict_decision._save_decision_outcome(session, history_id, outcome, {conflict_id: "STORED"})
        else:
            judgment._save_judgment_outcome(session, history_id, outcome)
    # Read a new DB session, not the object the writer still holds.
    with Session(case_engine) as session:
        record = session.exec(select(DecisionRecord).where(DecisionRecord.case_history_id == history_id)).one()
        assert (record.case_id, record.trace_id, record.run_id) == (case_id, TRACE_ID, str(outcome.review_proof.run_id))
        assert session.get(CaseHistory, history_id).judgment_status == "DONE"
        if decision:
            assert session.get(ConflictReference, conflict_id).status == "REJECTED"


@pytest.mark.parametrize("source_ids,explicit,expected", [
    ((None, None), None, None),
    ((TRACE_ID, "cd" * 16), None, None),
    ((TRACE_ID, "external-label"), None, None),
    (("external-label", "external-label"), None, None),
    (("0" * 32, "0" * 32), None, None),
    ((TRACE_ID, None), None, TRACE_ID),
    ((TRACE_ID, "cd" * 16), "explicit-correlation", "explicit-correlation"),
])
def test_trace_fallback_does_not_guess_and_preserves_explicit_values(  # noqa: F811
    case_engine, case_world, source_ids, explicit, expected,
):
    _, case_id, _ = case_world.sign_up()
    history_id = case_world.add_history(case_id, "USER_INPUT", "PENDING")
    outcome = traced_outcome(case_id, source_ids)
    with Session(case_engine) as session:
        decision_record.save_reviewed_plan(session, session.get(CaseHistory, history_id), outcome, trace_id=explicit)
    with Session(case_engine) as session:
        record = session.exec(select(DecisionRecord).where(DecisionRecord.case_history_id == history_id)).one()
        assert record.trace_id == expected
