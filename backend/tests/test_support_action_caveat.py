"""검수 전·오래된 지원 자료로도 확인 행동이 나와야 한다.

`_validate_pre_review_claim_safety`는 최신이 아닌 근거로 만든 문장마다 확인 문구를
요구한다. 지원사업 행동의 질문만 그 문구가 없어서, 검수 전 자료에서는 Supervisor가
세 번 다 초안을 버리고 `STRUCTURED_OUTPUT_FAILED`로 끝났다. 절차 쪽 질문은 모두
"확인해 주시겠습니까?"로 끝나므로 같은 상황에서 막히지 않는다.
"""

import asyncio

import pytest
from app.agent.claim_safety import has_confirmation_caveat
from app.agent.schemas import FreshnessStatus, SupportMatchStatus
from app.agent.supervisor import SupervisorAgent
from test_action_codes import source, support_sources
from test_blocker_candidates import ChoiceModel, candidates, request_with_state

_MATCH_STATUS = {
    "CURRENT": "NEEDS_CONFIRMATION",
    "UNKNOWN": "UNVERIFIABLE",
    "STALE": "STALE",
}


def request_with_support(freshness: str):
    """확정된 철거 필요 + 해당 최신성의 지원 자료 하나."""

    request = request_with_state(demolition_required="REQUIRED")
    output = support_sources()[0].output
    check = output.support_checks[0].model_copy(
        update={
            "match_status": SupportMatchStatus(_MATCH_STATUS[freshness]),
            "freshness_status": FreshnessStatus(freshness),
        }
    )
    used = {item.meta.call_id.int for item in request.source_results}
    call_id = next(index for index in range(3, 50) if index not in used)
    request.source_results.append(
        source(output.model_copy(update={"support_checks": [check]}), call_id=call_id)
    )
    # 근거 ID는 그대로 두고 최신성만 바꾼다. ID가 같은데 내용이 다르면 충돌로 막힌다.
    refs = set(check.evidence_refs)
    for holder in (request.case_snapshot, *(item.output for item in request.source_results)):
        records = getattr(holder, "evidence_records", None)
        if records is None:
            continue
        object.__setattr__(
            holder,
            "evidence_records",
            [
                record.model_copy(update={"freshness_status": FreshnessStatus(freshness)})
                if record.evidence_id in refs
                else record
                for record in records
            ],
        )
    return request


@pytest.mark.parametrize("freshness", ["CURRENT", "UNKNOWN", "STALE"])
def test_support_action_survives_non_current_evidence(freshness):
    async def run():
        request = request_with_support(freshness)
        rows = candidates(request)
        assert [row["candidate_id"] for row in rows] == ["support:1"]

        draft = await SupervisorAgent(ChoiceModel(), max_local_attempts=1).draft(request)
        assert draft.decision.decision_type == "ACTION"
        action = draft.decision.next_action
        assert action.action_code == "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS"
        # 최신이 아닌 근거를 쓰는 모든 문장에는 확인 문구가 있어야 한다.
        for text in (
            draft.decision.blocker.description,
            action.title,
            action.reason,
            *action.questions_to_ask,
        ):
            assert has_confirmation_caveat(text), text

    asyncio.run(run())
