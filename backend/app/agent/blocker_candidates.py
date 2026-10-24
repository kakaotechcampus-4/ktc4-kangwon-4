"""Bound the existing MVP priorities using verified Case state and source results.

Closure candidates are ordered by confirmed Case state and stored dependencies.
State descriptions and confirmation questions never turn UNKNOWN into a fact.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.agent.action_catalog import (
    ACTION_DEFINITIONS,
    PROCEDURE_LABELS,
    ProcedureBindings,
    build_action_candidates,
    effective_procedure_progress,
    resolve_procedure_bindings,
)
from app.agent.claim_safety import expand_evidence
from app.agent.procedure_tool.rules import (
    business_type_code,
    procedure_constraints,
    procedure_plan_constraints,
)
from app.agent.schemas import (
    ActionDecisionDraft,
    CaseFieldKey,
    CaseSnapshot,
    DecisionDraft,
    EvidenceRecord,
    InfoAnalysisResult,
    KnownProcedureStep,
    MutationSet,
    ReviewSourceResult,
)

_QUESTIONS = {
    "business_type": "어떤 가게를 운영하시나요?",
    "franchise_status": "프랜차이즈 가게인가요?",
    "lease_status": "가게 자리를 월세, 무상 임차, 자가 중 어떤 방식으로 사용하시나요?",
    "employee_count": "직원이 몇 명인가요?",
    "restoration_scope": "확인한 원상복구 범위가 있으면 알려주세요.",
    "restoration_scope_detail": "확인한 원상복구 범위의 구체적인 내용을 알려주세요.",
    "demolition_required": "철거가 필요한지 확인한 내용이 있으면 알려주세요.",
    "restoration_status": "원상복구 작업이 어디까지 진행됐는지 알려주세요.",
}
_FIELD_LABELS = {
    "business_type": "가게 업종",
    "franchise_status": "프랜차이즈 여부",
    "lease_status": "가게 자리의 임차 형태",
    "employee_count": "직원 수",
    "restoration_scope": "원상복구 범위",
    "restoration_scope_detail": "원상복구 범위의 구체적인 내용",
    "demolition_required": "철거 필요 여부",
    "restoration_status": "원상복구 진행 상태",
}


def field_confirmation_question(field_path: CaseFieldKey) -> str:
    """Reuse the Case confirmation question when Info has no specific question."""
    if field_path == CaseFieldKey.PLANNED_CLOSURE_DATE:
        return "예정한 폐업일이 언제인지 알려주세요."
    return _QUESTIONS[field_path.value]


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
        "evidence_refs": candidate["evidence_refs"],
        "blocker": candidate["blocker"],
        "blockers": [candidate["blocker"]],
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
    procedure_bindings: ProcedureBindings | None = None,
) -> list[dict[str, Any]]:
    """Rank all executable closure candidates; support is outside the MVP."""
    resolved_bindings = resolve_procedure_bindings(steps, procedure_bindings)
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
    missing = [
        label
        for key, label in (
            ("restoration_scope", "원상복구 범위"),
            ("demolition_required", "철거 필요 여부"),
        )
        if key not in values
    ]
    restoration_first = (
        bool(missing)
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
    groups: dict[str, dict[str, Any]] = {}
    for row in build_action_candidates(
        sources,
        evidence_by_id,
        resolved_bindings,
        procedure_progress=effective_procedure_progress(snapshot, mutations),
    ):
        target = row["target"]
        if target["target_kind"] != "PROCEDURE":
            continue
        reference = target["procedure_step"]
        step_code = reference["step_code"]
        finding = findings[(reference["procedure_step_id"], step_code)]
        definition = ACTION_DEFINITIONS[row["action_code"]]
        logical_code = row["logical_code"]
        # A current source can support asking whether a procedure applies.
        # Submission still requires established relevance and master rules.
        if finding.relevance != "RELEVANT":
            if not (
                definition.confirmation_only
                and finding.relevance == "POSSIBLY_RELEVANT"
                and finding.requires_confirmation
            ):
                continue
            evidence = expand_evidence(
                [evidence_by_id[ref] for ref in finding.evidence_refs],
                evidence_by_id,
            )
            if any(item.freshness_status != "CURRENT" for item in evidence):
                continue
        key = f"procedure:{reference['procedure_step_id']}"
        refs = list(finding.evidence_refs)
        for progress in snapshot.procedure_progress:
            if progress.procedure_step == finding.procedure_step:
                refs.extend(progress.evidence_refs)
        for change in mutations.procedure_progress_changes:
            if change.procedure_step == finding.procedure_step:
                refs.extend(change.execution_evidence_refs)
        refs = list(dict.fromkeys(refs))
        if logical_code == "CONFIRM_RESTORATION_SCOPE":
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
            assert logical_code is not None
            label = PROCEDURE_LABELS[logical_code]
            evidence = expand_evidence(
                [evidence_by_id[ref] for ref in finding.evidence_refs],
                evidence_by_id,
            )
            confirmation = definition.confirmation_only
            applicability_unknown = finding.relevance == "POSSIBLY_RELEVANT"
            processing = row["phase"] == "PROCESSING"
            description = (
                f"{label}는 제출됐지만 기관 처리 완료 여부는 아직 확인되지 않았습니다."
                if processing
                else f"{label} 완료가 아직 확인되지 않았습니다."
                if not confirmation
                else f"{label} 안내의 현재 적용 여부를 확인할 필요가 있습니다."
                if any(item.freshness_status != "CURRENT" for item in evidence)
                else f"{label} 대상 여부와 준비사항을 확인할 필요가 있습니다."
                if applicability_unknown
                else f"{label}의 진행 상태와 준비사항을 확인할 필요가 있습니다."
            )
            title = (
                f"담당 기관에 {label}의 처리 완료 여부를 확인하세요."
                if processing
                else f"담당 기관에 {label} 대상 여부와 준비사항을 확인하세요."
                if applicability_unknown
                else f"담당 기관에 {label} 준비사항을 확인하세요."
                if confirmation
                else f"{label}를 진행하세요."
            )
            reason = (
                f"{label}의 제출과 기관 처리 완료는 구분해 확인해야 합니다."
                if processing
                else "제공된 공식 안내가 가게에 적용되는지 담당 기관에 확인할 필요가 있습니다."
                if applicability_unknown
                else f"제공된 공식 안내를 바탕으로 {label}에 필요한 준비를 확인하세요."
                if confirmation
                else finding.required_actions[0].text
            )
            questions = (
                ["해당 절차의 기관 처리가 완료되었는지 확인해 주시겠습니까?"]
                if processing
                else [
                    (
                        f"제 가게가 {label} 대상인지, 해당하면 필요한 서류와 제출 방법은 "
                        "무엇인지 확인해 주시겠습니까?"
                    )
                ]
                if applicability_unknown
                else [f"{label}에 필요한 서류와 제출 방법을 확인해 주시겠습니까?"]
                if confirmation
                else ["제출한 신고서와 첨부서류가 접수되었는지 확인해 주시겠습니까?"]
            )
        action = {key: row[key] for key in ("action_code", "target")}
        action.update(
            title=title, reason=reason, questions_to_ask=questions, evidence_refs=refs
        )
        decision_refs = list(dict.fromkeys([*state_refs, *refs]))
        candidate = {
            "candidate_id": key,
            "evidence_refs": decision_refs,
            "blocker": {"candidate_id": key, "description": description, "evidence_refs": decision_refs},
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
    progress = {
        item.procedure_step.procedure_step_id: item.status
        for item in snapshot.procedure_progress
    }
    progress.update(
        (change.procedure_step.procedure_step_id, change.proposed_status)
        for change in mutations.procedure_progress_changes
    )
    prerequisites = {
        dependency.prerequisite_procedure_step_id
        for step in steps
        if progress.get(step.procedure_step.procedure_step_id) != "COMPLETED"
        and any(
            finding.procedure_step == step.procedure_step
            and finding.relevance in {"RELEVANT", "POSSIBLY_RELEVANT"}
            for finding in findings.values()
        )
        and not procedure_constraints(
            step.model_copy(update={"dependencies": []}),
            snapshot,
            mutations.fact_changes,
            mutations.procedure_progress_changes,
        )
        for dependency in step.dependencies
        if dependency.dependency_type == "SEQUENTIAL"
    }

    def priority(candidate: dict[str, Any]) -> tuple[bool, bool, bool, str]:
        action = candidate["actions"][0]
        logical = next(
            (
                code
                for code, ref in resolved_bindings.items()
                if ref.model_dump(mode="json") == action["target"]["procedure_step"]
            ),
            None,
        )
        step_id = action["target"]["procedure_step"]["procedure_step_id"]
        return (
            logical != "CONFIRM_RESTORATION_SCOPE",
            step_id not in prerequisites,
            progress.get(step_id) != "IN_PROGRESS",
            logical or "",
        )

    for candidate in groups.values():
        # The current ProcedureFinding contract always requires confirmation.
        candidate["actions"].sort(
            key=lambda action: (
                not ACTION_DEFINITIONS[action["action_code"]].confirmation_only,
                action["action_code"],
            )
        )
    return sorted(groups.values(), key=priority)


def missing_info_fields(
    snapshot: CaseSnapshot,
    sources: Sequence[ReviewSourceResult],
    mutations: MutationSet,
    procedure_bindings: ProcedureBindings | None = None,
    *,
    held_only: bool = False,
    selected_candidate_id: str | None = None,
) -> dict[str, Any] | None:
    """Ask about one unresolved decision blocker in the existing question order."""
    values = _values(snapshot, mutations)
    restoration_detail_unnecessary = (
        values.get("restoration_status") == "NOT_REQUIRED"
        or values.get("restoration_scope") == "NOT_REQUIRED"
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
    # 확인이 필요한 사실은 Case에 반영되지 않으므로 mutations에 안 들어온다.
    # 그 사실의 근거(사장님이 쓴 문장)는 되물을 때 인용할 거라 여기서 모은다.
    held = [
        candidate
        for source in sources
        if isinstance(source.output, InfoAnalysisResult)
        for candidate in source.output.fact_candidates
        if candidate.requires_confirmation
        and not any(
            item.field_path == candidate.field_path
            and set(item.blocks) == {"SUPPORT_ANALYSIS"}
            for item in source.output.missing_fields
        )
    ]
    refs.extend(
        ref
        for candidate in held
        for ref in candidate.source_evidence_refs
        if ref not in refs
    )
    if not refs:
        return None
    missing_paths = {
        path.value
        for source in sources
        if isinstance(source.output, InfoAnalysisResult)
        for question in source.output.question_candidates
        for path in question.resolves_field_paths
        if path.value in _QUESTIONS
        and path.value not in values
        and any(
            item.field_path == path
            and "SUPERVISOR_DECISION" in item.blocks
            and item.question_candidate_id in {None, question.question_id}
            for item in source.output.missing_fields
        )
        and not (
            restoration_detail_unnecessary and path.value == "restoration_scope_detail"
        )
    }
    # 모델이 답을 냈다고 보면 그 필드를 missing_fields에 안 넣는다. 그런데 그 답이
    # 확인이 필요한 상태로 보류됐다면 아직 모르는 값이므로, 되물을 대상에 넣는다.
    # 이것이 없으면 "사실은 보류됐는데 아무도 묻지 않는" 상태가 된다.
    held_paths = {
        candidate.field_path.value
        for candidate in held
        if candidate.field_path.value in _QUESTIONS
        and candidate.field_path.value not in values
        and not (
            restoration_detail_unnecessary
            and candidate.field_path.value == "restoration_scope_detail"
        )
    }
    paths = held_paths if held_only else held_paths | missing_paths
    if values.get("restoration_scope") not in {"PARTIAL", "FULL"}:
        paths.discard("restoration_status")
    ordered = [path for path in _QUESTIONS if path in paths]
    if selected_candidate_id is None:
        missing = next(iter(ordered), None)
    else:
        missing = next((path for path in ordered if f"missing:{path}" == selected_candidate_id), None)
    if missing is None:
        return None
    questions = [_QUESTIONS[missing]]
    description = f"{_FIELD_LABELS[missing]} 확인이 필요합니다."
    blockers = [
        {"candidate_id": f"missing:{path}", "description": f"{_FIELD_LABELS[path]} 확인이 필요합니다.", "evidence_refs": refs}
        for path in ordered
    ]
    return {
        "decision_type": "NEEDS_MORE_INFO",
        "selection_summary": description,
        "requires_human": True,
        "evidence_refs": refs,
        "blocker": {"candidate_id": f"missing:{missing}", "description": description, "evidence_refs": refs},
        "blockers": blockers,
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
    expected_blockers = [item["blocker"] for item in candidates]
    if fallback is not None:
        expected_blockers.extend(fallback["blockers"])
    if fallback is not None and decision.next_action is None:
        selected = next(
            (
                item
                for item in fallback["blockers"]
                if item["candidate_id"] == decision.blocker.candidate_id
            ),
            None,
        )
        if selected is not None:
            field_path = selected["candidate_id"].removeprefix("missing:")
            expected = {
                **fallback,
                "blocker": selected,
                "selection_summary": selected["description"],
                "questions_for_user": [_QUESTIONS[field_path]],
            }
    if decision.next_action is not None:
        selected = next(
            (
                item
                for item in candidates
                if item["candidate_id"] == decision.blocker.candidate_id
            ),
            None,
        )
        try:
            expected = (
                candidate_decision_fields(
                    selected,
                    decision.next_action.action_code,
                    decision.next_action.target.model_dump(mode="json"),
                )
                if selected is not None
                else None
            )
        except ValueError:
            expected = None
    if expected is None:
        return [("/decision", "decision is outside the current blocker candidates")]
    actual = decision.model_dump(mode="json")
    if actual.get("next_action") is not None:
        actual["next_action"].pop("sequence")
    violations = [
        (f"/decision/{key}", "decision differs from verified blocker state or action")
        for key, value in expected.items()
        if key != "blockers" and actual.get(key) != value
    ]
    expected_by_id = {item["candidate_id"]: item for item in expected_blockers}
    actual_by_id = {
        item.candidate_id: item.model_dump(mode="json") for item in decision.blockers
    }
    if len(actual_by_id) != len(decision.blockers) or actual_by_id != expected_by_id:
        violations.append(
            (
                "/decision/blockers",
                "blockers must contain every verified candidate exactly once",
            )
        )
    return violations


def resolved_blocker_candidates(snapshot, known_steps, mutations, bindings) -> list[str]:
    """Only confirmed state can resolve a stored candidate; omission is no proof."""
    values = _values(snapshot, mutations)
    progress = {(item.procedure_step.procedure_step_id, item.procedure_step.step_code): item.status
                for item in snapshot.procedure_progress}
    progress.update({(item.procedure_step.procedure_step_id, item.procedure_step.step_code): item.proposed_status
                     for item in mutations.procedure_progress_changes})
    registry = {str(item.procedure_step.procedure_step_id): item for item in known_steps}
    resolved = []
    for candidate_id in snapshot.active_blocker_candidate_ids:
        if candidate_id.startswith("missing:"):
            if candidate_id.removeprefix("missing:") in values:
                resolved.append(candidate_id)
        elif candidate_id.startswith("procedure:"):
            step = registry.get(candidate_id.removeprefix("procedure:"))
            if step is None or step.deprecated_at is not None:
                continue
            business = values.get("business_type")
            unmet_conditions = {f"eligibility condition is not met: {item.condition_key}"
                                for item in step.eligibility_conditions}
            excluded = (
                business is not None and step.applicable_business_type != "ALL"
                and business_type_code(business) != step.applicable_business_type
            ) or any(
                reason in unmet_conditions
                for reason in procedure_constraints(
                    step, snapshot, mutations.fact_changes, mutations.procedure_progress_changes,
                )
            )
            if (
                excluded
                or progress.get((step.procedure_step.procedure_step_id, step.procedure_step.step_code)) == "COMPLETED"
                or step.procedure_step == bindings.get("CONFIRM_RESTORATION_SCOPE")
                and all(field in values for field in ("restoration_scope", "demolition_required"))
            ):
                resolved.append(candidate_id)
    return resolved
