"""Bound the existing MVP priorities using verified Case state and source results.

The Supervisor still chooses a candidate and an action. State descriptions and
confirmation questions come from code, so UNKNOWN never becomes 'undecided'.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.agent.action_catalog import ACTION_DEFINITIONS, build_action_candidates
from app.agent.procedure_tool.rules import procedure_plan_constraints
from app.agent.schemas import (
    ActionDecisionDraft,
    CaseSnapshot,
    DecisionDraft,
    EvidenceRecord,
    InfoAnalysisResult,
    KnownProcedureStep,
    MutationSet,
    ReviewSourceResult,
    SupportAnalysisResult,
)

_PROCEDURE_LABELS = {
    "FILE_TAX_BUSINESS_CLOSURE": "사업자 폐업신고",
    "FILE_FOOD_SERVICE_CLOSURE": "식품영업 폐업신고",
    "REPORT_WORKPLACE_INSURANCE_CLOSURE": "사업장 탈퇴 신고",
}
_QUESTIONS = {
    "business_type": "어떤 가게를 운영하시나요?",
    "franchise_status": "프랜차이즈 가게인가요?",
    "lease_status": "가게 자리를 월세, 무상 임차, 자가 중 어떤 방식으로 사용하시나요?",
    "employee_count": "직원이 몇 명인가요?",
    "planned_closure_date": "정리할 예정일을 정하셨다면 알려주세요.",
    "restoration_scope": "확인한 원상복구 범위가 있으면 알려주세요.",
    "restoration_scope_detail": "확인한 원상복구 범위의 구체적인 내용을 알려주세요.",
    "demolition_required": "철거가 필요한지 확인한 내용이 있으면 알려주세요.",
    "restoration_status": "원상복구 작업이 어디까지 진행됐는지 알려주세요.",
}


def _values(snapshot: CaseSnapshot, mutations: MutationSet) -> dict[str, Any]:
    facts = {
        fact.field_path.value: (fact.status, fact.value) for fact in snapshot.facts
    }
    facts.update(
        (change.field_path.value, (change.proposed_status, change.proposed_value))
        for change in mutations.fact_changes
    )
    return {
        key: value for key, (status, value) in facts.items() if status == "CONFIRMED"
    }


def _decision_fields(
    candidate: dict[str, Any], action: dict[str, Any]
) -> dict[str, Any]:
    return {
        "decision_type": "ACTION",
        "selection_summary": action["title"],
        "requires_human": True,
        "evidence_refs": candidate["blocker"]["evidence_refs"],
        "blocker": candidate["blocker"],
        "next_action": action,
        "questions_for_user": [],
    }


def candidate_decision_fields(
    candidate: dict[str, Any], action_code: str, target: dict[str, Any]
) -> dict[str, Any]:
    action = next(
        (
            item
            for item in candidate["actions"]
            if item["action_code"] == action_code and item["target"] == target
        ),
        None,
    )
    if action is None:
        raise ValueError("action does not belong to selected blocker candidate")
    return _decision_fields(candidate, action)


def build_blocker_candidates(
    snapshot: CaseSnapshot,
    steps: Sequence[KnownProcedureStep],
    sources: Sequence[ReviewSourceResult],
    mutations: MutationSet,
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> list[dict[str, Any]]:
    """Apply the priority already specified in supervisor_messages, then cap at 3."""
    values = _values(snapshot, mutations)
    state_refs = list(
        dict.fromkeys(ref for fact in snapshot.facts for ref in fact.evidence_refs)
    )
    state_refs.extend(
        ref
        for change in mutations.fact_changes
        for ref in change.source_evidence_refs
        if ref not in state_refs
    )
    completed = values.get("restoration_status") == "COMPLETED"
    support_first = values.get("demolition_required") == "REQUIRED" and not completed
    missing = [
        label
        for key, label in (
            ("restoration_scope", "원상복구 범위"),
            ("demolition_required", "철거 필요 여부"),
        )
        if key not in values
    ]
    restoration_first = (
        not support_first
        and not completed
        and bool(missing)
        and values.get("lease_status") in {"LEASED_PAID", "LEASED_FREE"}
    )
    findings = {
        (
            finding.procedure_step.procedure_step_id,
            finding.procedure_step.step_code,
        ): finding
        for source in sources
        if isinstance(source.output, InfoAnalysisResult)
        for finding in source.output.procedure_findings
    }
    checks = {
        check.support_program.support_program_id: check
        for source in sources
        if isinstance(source.output, SupportAnalysisResult)
        for check in source.output.support_checks
    }
    groups: dict[str, dict[str, Any]] = {}
    for row in build_action_candidates(sources, evidence_by_id):
        target = row["target"]
        is_support = target["target_kind"] == "SUPPORT_PROGRAM"
        if support_first and not is_support:
            continue
        if is_support:
            if restoration_first:
                continue
            check = checks[target["support_program"]["support_program_id"]]
            key = f"support:{check.support_program.support_program_id}"
            description = "지원조건과 신청 전 증빙의 확인이 필요합니다."
            title = f"{check.program_name}의 현재 조건과 신청 전 증빙을 확인하세요."
            reason = "제공된 지원 안내의 현재 조건을 담당 기관에 확인해야 합니다."
            questions = ["현재 조건과 신청 전에 준비할 증빙은 무엇인가요?"]
            refs = list(check.evidence_refs)
        else:
            reference = target["procedure_step"]
            step_code = reference["step_code"]
            finding = findings[(reference["procedure_step_id"], step_code)]
            # A stale/undetermined finding cannot establish a current blocker.
            if finding.relevance != "RELEVANT":
                continue
            key = f"procedure:{reference['procedure_step_id']}"
            refs = list(finding.evidence_refs)
            if step_code == "CONFIRM_RESTORATION_SCOPE":
                if not restoration_first:
                    continue
                subject = "와 ".join(missing)
                description = f"{subject}가 아직 확인되지 않았습니다."
                title = f"임대인에게 {subject}를 확인하세요."
                reason = (
                    f"현재 {subject}가 확인되지 않아 임대인에게 확인할 필요가 있습니다."
                )
                questions = [
                    "원상복구해야 할 범위는 어디까지인가요?"
                    if label == "원상복구 범위"
                    else "철거가 필요한가요?"
                    for label in missing
                ]
            else:
                if restoration_first:
                    continue
                label = _PROCEDURE_LABELS[step_code]
                description = (
                    f"{label}의 진행 상태와 준비사항을 확인할 필요가 있습니다."
                )
                confirmation = ACTION_DEFINITIONS[row["action_code"]].confirmation_only
                title = (
                    f"담당 기관에 {label} 준비사항을 확인하세요."
                    if confirmation
                    else f"{label}를 제출하세요."
                )
                reason = (
                    f"제공된 공식 안내를 바탕으로 {label}에 필요한 준비를 확인하세요."
                    if confirmation
                    else finding.required_actions[0].text
                )
                questions = (
                    [f"{label}에 필요한 서류와 제출 방법을 확인해 주시겠습니까?"]
                    if confirmation
                    else [
                        "제출한 신고서와 첨부서류가 접수되었는지 확인해 주시겠습니까?"
                    ]
                )
        action = {key: row[key] for key in ("action_code", "target")}
        action.update(
            title=title, reason=reason, questions_to_ask=questions, evidence_refs=refs
        )
        candidate = {
            "candidate_id": key,
            "blocker": {
                "description": description,
                "evidence_refs": list(dict.fromkeys([*state_refs, *refs])),
            },
            "actions": [action],
        }
        # Reuse the exact registry, dependency, applicability and completion guard
        # used after Supervisor selection; no second interpretation of the rules.
        preview = ActionDecisionDraft.model_validate(
            {
                **_decision_fields(candidate, action),
                "next_action": {**action, "sequence": 1},
                "draft_id": "00000000-0000-0000-0000-000000000001",
                "draft_version": 1,
                "created_at": snapshot.captured_at,
                "based_on_call_ids": [str(source.meta.call_id) for source in sources],
            }
        )
        if procedure_plan_constraints(steps, snapshot, mutations, preview):
            continue
        if key in groups:
            groups[key]["actions"].append(action)
        else:
            groups[key] = candidate
    return [groups[key] for key in sorted(groups)][:3]


def missing_info_fields(
    snapshot: CaseSnapshot,
    sources: Sequence[ReviewSourceResult],
    mutations: MutationSet,
) -> dict[str, Any] | None:
    """A bounded question fallback without re-asking confirmed Case fields."""
    values = _values(snapshot, mutations)
    progress = {
        (
            item.procedure_step.procedure_step_id,
            item.procedure_step.step_code,
        ): item.status
        for item in snapshot.procedure_progress
    }
    progress.update(
        (
            (item.procedure_step.procedure_step_id, item.procedure_step.step_code),
            item.proposed_status,
        )
        for item in mutations.procedure_progress_changes
    )
    restoration_questions_resolved = values.get(
        "restoration_status"
    ) == "COMPLETED" or any(
        code == "CONFIRM_RESTORATION_SCOPE" and status == "COMPLETED"
        for (_, code), status in progress.items()
    )
    restoration_detail_unnecessary = (
        values.get("restoration_status") == "NOT_REQUIRED"
        or values.get("restoration_scope") == "NOT_REQUIRED"
    )
    support_first = (
        values.get("demolition_required") == "REQUIRED"
        and values.get("restoration_status") != "COMPLETED"
    )
    refs = list(
        dict.fromkeys(ref for fact in snapshot.facts for ref in fact.evidence_refs)
    )
    refs.extend(
        ref
        for change in mutations.fact_changes
        for ref in change.source_evidence_refs
        if ref not in refs
    )
    if not refs:
        return None
    if support_first:
        description = "현재 판단에 사용할 지원 안내가 부족해 추가 확인이 필요합니다."
        questions = ["지원 안내문이나 담당 기관에서 확인한 내용이 있으면 알려주세요."]
    else:
        missing = list(
            dict.fromkeys(
                path.value
                for source in sources
                if isinstance(source.output, InfoAnalysisResult)
                for question in source.output.question_candidates
                for path in question.resolves_field_paths
                if path.value not in values
                and not (
                    restoration_questions_resolved
                    and path.value.startswith(("restoration_", "demolition_"))
                )
                and not (
                    restoration_detail_unnecessary
                    and path.value == "restoration_scope_detail"
                )
            )
        )
        questions = [_QUESTIONS[key] for key in missing if key in _QUESTIONS][:3]
        if not questions:
            questions = [
                "다음 절차를 확인할 수 있는 안내문이나 담당 기관의 안내 내용이 있으면 알려주세요."
            ]
        description = (
            "다음 행동의 판단에 필요한 정보나 절차 안내가 아직 확인되지 않았습니다."
        )
    return {
        "decision_type": "NEEDS_MORE_INFO",
        "selection_summary": description,
        "requires_human": True,
        "evidence_refs": refs,
        "blocker": {"description": description, "evidence_refs": refs},
        "next_action": None,
        "questions_for_user": questions,
    }


def candidate_decision_violations(
    decision: DecisionDraft,
    candidates: Sequence[dict[str, Any]],
    fallback: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    """Shared by Supervisor and independent Review, including a forced-model PASS."""
    expected = fallback
    if decision.next_action is not None:
        expected = next(
            (
                _decision_fields(candidate, action)
                for candidate in candidates
                for action in candidate["actions"]
                if action["action_code"] == decision.next_action.action_code
                and action["target"]
                == decision.next_action.target.model_dump(mode="json")
            ),
            None,
        )
    elif candidates:
        expected = None
    if expected is None:
        return [("/decision", "decision is outside the current blocker candidates")]
    actual = decision.model_dump(mode="json")
    if actual.get("next_action") is not None:
        actual["next_action"].pop("sequence")
    return [
        (f"/decision/{key}", "decision differs from verified blocker state or action")
        for key, value in expected.items()
        if actual.get(key) != value
    ]
