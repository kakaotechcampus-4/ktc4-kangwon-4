"""검수 절차 정리본으로 Info 초안을 코드로 만든다. 모델을 부르지 않는다.

첫 판단(CASE_CREATED)에는 버튼 값만 들어와 읽을 글이 없다. 그런데 Info 모델은 판단마다
검수 절차 원문을 다시 읽어 절차별 요약·할 일을 인용하느라 출력 8~9천 토큰, 호출 1번에
약 135초를 썼다(2026-11-04 Langfuse 기준값, 판단 시간의 83%). 원문이 같으면 결과도 같아서,
사람이 검수한 정리본(app/common/procedure-digests.ko-KR.json)을 원문 지문(content_hash)에 묶어
두고 그대로 쓴다.

정리본에는 서비스가 실제로 쓰는 것만 둔다. 할 일(행동 후보의 조건이자 이유 문장), 요약 1문장,
결정 주체, 철거 서류 이름(#155 질문). 신청 경로·URL·기한은 아무도 읽지 않고 기한 단정
위험만 있어 넣지 않는다. "이 가게에 해당하는가"는 가게마다 달라 정리본에 두지 않고 규칙
(procedure_applicability)으로 계산한다.

정리본이 검수 전이거나, 원문 지문이 달라졌거나, 분석할 절차가 정리본에 없으면 None을
돌려준다. 그러면 지금처럼 모델이 분석한다.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agent.procedure_tool.rules import procedure_applicability
from app.agent.schemas import (
    AgentFieldKey,
    DecisionAuthority,
    FactStatus,
    FreshnessStatus,
    InfoAnalysisInput,
    InfoCompletionStatus,
    MissingFieldBlock,
    ProcedureRelevance,
    RequiredDocument,
    SourcedText,
)

DIGEST_PATH = Path(__file__).resolve().parents[2] / "common" / "procedure-digests.ko-KR.json"

# 원상복구 범위·철거 여부를 모르면 임대인에게 물어야 한다(Info 프롬프트 9번 규칙과 같은 질문).
_RESTORATION_QUESTIONS = {
    AgentFieldKey.RESTORATION_SCOPE: ("원상복구 범위가 아직 확인되지 않았습니다.", "원상복구해야 할 범위는 어디까지인가요?"),
    AgentFieldKey.DEMOLITION_REQUIRED: ("철거 필요 여부가 아직 확인되지 않았습니다.", "철거가 필요한가요?"),
}


def _bare_hash(value: str) -> str:
    return value.removeprefix("sha256:")


# 사장님 글(임대인 답변)로 정해지는 원상복구 칸. 값 꺼내기 단계에서 되물을 수 있는 칸은 이것뿐이다.
_ANSWER_FIELDS = frozenset({
    AgentFieldKey.RESTORATION_SCOPE, AgentFieldKey.DEMOLITION_REQUIRED, AgentFieldKey.RESTORATION_SCOPE_DETAIL,
})


@lru_cache
def load_digests(path: Path = DIGEST_PATH) -> dict[str, Any] | None:
    """검수를 마친 정리본만 돌려준다. 파일이 없거나 검수 전이면 None."""

    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if data.get("reviewed_by") and data.get("reviewed_at") else None


def digest_draft_fields(
    request: InfoAnalysisInput, digests: dict[str, Any], analysis_step_codes: set[str],
) -> dict[str, Any] | None:
    """InfoAnalysisDraft에 넣을 값. 정리본으로 다 채울 수 없으면 None."""

    # 원문 지문이 같은 근거만 쓴다. 원문이 갱신되면 지문이 달라져 정리본은 자동으로 빠진다.
    # 검수 파일은 "sha256:<hex>", 실행 중 근거는 "<hex>"로 들고 있어 앞머리를 떼고 비교한다.
    evidence_by_hash = {
        _bare_hash(item.content_hash): item.evidence_id
        for item in request.procedure_lookup_result.evidence_records
        if item.content_hash and item.freshness_status == FreshnessStatus.CURRENT
    }
    evidence_of = {
        record_id: evidence_by_hash.get(_bare_hash(content_hash))
        for record_id, content_hash in digests["source_hashes"].items()
    }
    steps = {item.procedure_step.step_code: item for item in request.known_procedure_steps}

    def sourced(item: dict[str, str]) -> SourcedText:
        return SourcedText(text=item["text"], evidence_refs=[evidence_of[item["record_id"]]])

    findings = []
    for code in sorted(analysis_step_codes):
        digest = digests["steps"].get(code)
        if digest is None or code not in steps:
            return None
        items = [digest["summary"], *digest["required_actions"], *digest["required_documents"]]
        if any(evidence_of.get(item["record_id"]) is None for item in items):
            return None
        applies = procedure_applicability(steps[code], request.case_snapshot, request.fact_overlays)
        findings.append({
            "step_code": code,
            "summary": sourced(digest["summary"]),
            # 해당한다고 확정된 절차만 바로 할 일 후보가 된다. 모르거나 해당 안 되면 확인 대상으로 둔다
            # (해당 안 되는 절차는 Blocker 후보에서 규칙으로 다시 빠진다, blocker_candidates.py).
            "relevance": ProcedureRelevance.RELEVANT if applies is True else ProcedureRelevance.POSSIBLY_RELEVANT,
            "decision_authority": DecisionAuthority(digest["decision_authority"]),
            "requires_confirmation": True,
            "required_actions": [sourced(item) for item in digest["required_actions"]],
            "required_documents": [
                RequiredDocument(name=item["name"], submission_stage=None,
                                 evidence_refs=[evidence_of[item["record_id"]]])
                for item in digest["required_documents"]
            ],
            "application_channel": None,
            "application_url": None,
            "deadline": None,
            "evidence_refs": sorted({evidence_of[item["record_id"]] for item in items}),
        })

    missing_fields = []
    if "CONFIRM_RESTORATION_SCOPE" in analysis_step_codes:
        known = {
            fact.field_path for fact in request.case_snapshot.facts
            if fact.status == FactStatus.CONFIRMED and fact.value is not None
        } | {item.field_path for item in request.fact_overlays}
        for field, (reason, question) in _RESTORATION_QUESTIONS.items():
            if field not in known:
                missing_fields.append({
                    "field_path": field, "reason_summary": reason,
                    "blocks": [MissingFieldBlock.SUPERVISOR_DECISION], "question": question,
                })
    return {
        "completion_status": InfoCompletionStatus.NEEDS_USER_INPUT if missing_fields else InfoCompletionStatus.COMPLETE,
        "facts": [],
        "procedure_observations": [],
        "procedure_findings": findings,
        "missing_fields": missing_fields,
        "uncertainties": [],
    }


def with_digest_findings(fact_output: dict[str, Any], digest_fields: dict[str, Any]) -> dict[str, Any]:
    """모델이 사장님 글에서 꺼낸 값에 정리본의 절차 정리를 붙인다(InfoAnalysisDraft 모양).

    정리본의 원상복구 질문은 모델이 아직 다루지 않은 칸만 더한다. 방금 임대인 답변으로 범위가
    정해졌거나(facts) 모델이 이미 묻기로 한 칸(missing_fields)은 다시 묻지 않는다.
    """

    # 이 단계는 사장님 답 한 줄(임대인 답변·서류 글)을 읽는다. 답과 상관없는 진단 항목(보험 가입 이력·폐업 시기
    # 등)까지 "모름"으로 되묻게 두면, Review가 그 질문을 blocker 목록에도 요구해 매번 반려했다(2026-11-05 실측,
    # REVIEW_RETRY_EXHAUSTED). 그런 항목은 상황 진단에서 받는 값이라 여기서는 원상복구 칸만 되묻는다.
    # 이 단계의 모델은 절차를 조회하지 않으므로 되묻는 칸은 모두 "다음 할 일 판단을 막는 칸"이다.
    # 그렇게 표시해야 코드가 그 칸으로 확인 질문 blocker(missing:*)를 만든다(blocker_candidates.missing_info_fields).
    # 짧은 지시문에서 모델이 PROCEDURE_LOOKUP 등으로 적으면 질문만 있고 blocker가 없어 Review가 반려했다(G17 실측).
    asked = [
        item | {"blocks": [MissingFieldBlock.SUPERVISOR_DECISION]}
        for item in fact_output["missing_fields"] if item["field_path"] in _ANSWER_FIELDS
    ]
    handled = {item["field_path"] for item in [*fact_output["facts"], *asked]}
    added = [item for item in digest_fields["missing_fields"] if item["field_path"] not in handled]
    missing = [*asked, *added]
    status = fact_output["completion_status"]
    if missing and status == InfoCompletionStatus.COMPLETE:
        status = InfoCompletionStatus.NEEDS_USER_INPUT
    elif not missing and status == InfoCompletionStatus.NEEDS_USER_INPUT:
        status = InfoCompletionStatus.COMPLETE
    return fact_output | {
        "completion_status": status,
        "procedure_findings": digest_fields["procedure_findings"],
        "missing_fields": missing,
    }
