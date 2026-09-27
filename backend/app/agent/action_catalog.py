"""Fixed action kinds; the separate target identifies the procedure or program."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.agent.claim_safety import REQUIRED_CLAIM_SOURCES, expand_evidence
from app.agent.schemas import (
    EvidenceRecord,
    FreshnessStatus,
    InfoAnalysisResult,
    ProcedureRelevance,
    ReviewSourceResult,
    SupportAnalysisResult,
    SupportMatchStatus,
)


@dataclass(frozen=True)
class ActionDefinition:
    description: str
    procedure_step_code: str | None
    confirmation_only: bool


ACTION_DEFINITIONS: dict[str, ActionDefinition] = {
    "CONFIRM_RESTORATION_SCOPE": ActionDefinition(
        "임대인에게 원상복구 범위와 철거 필요 여부를 확인한다.",
        "CONFIRM_RESTORATION_SCOPE",
        True,
    ),
    "CONFIRM_TAX_CLOSURE_REQUIREMENTS": ActionDefinition(
        "세무서 등 공식 창구에 사업자 폐업신고 방법과 필요한 서류를 확인한다. 신고 제출과 구분한다.",
        "FILE_TAX_BUSINESS_CLOSURE",
        True,
    ),
    "FILE_TAX_BUSINESS_CLOSURE": ActionDefinition(
        "공식 근거와 확인한 요건에 따라 사업자 폐업신고를 제출한다. 방법을 묻는 행동과 구분한다.",
        "FILE_TAX_BUSINESS_CLOSURE",
        False,
    ),
    "CONFIRM_FOOD_SERVICE_CLOSURE_REQUIREMENTS": ActionDefinition(
        "관할 기관에 식품영업 폐업신고 방법과 필요한 서류를 확인한다. 신고 제출과 구분한다.",
        "FILE_FOOD_SERVICE_CLOSURE",
        True,
    ),
    "FILE_FOOD_SERVICE_CLOSURE": ActionDefinition(
        "공식 근거와 확인한 요건에 따라 식품영업 폐업신고를 제출한다. 방법을 묻는 행동과 구분한다.",
        "FILE_FOOD_SERVICE_CLOSURE",
        False,
    ),
    "CONFIRM_WORKPLACE_INSURANCE_CLOSURE_REQUIREMENTS": ActionDefinition(
        "담당 보험기관에 사업장 탈퇴 신고 방법과 필요한 서류를 확인한다. 신고 제출과 구분한다.",
        "REPORT_WORKPLACE_INSURANCE_CLOSURE",
        True,
    ),
    "REPORT_WORKPLACE_INSURANCE_CLOSURE": ActionDefinition(
        "공식 근거와 확인한 요건에 따라 사업장 탈퇴 신고를 제출한다. 방법을 묻는 행동과 구분한다.",
        "REPORT_WORKPLACE_INSURANCE_CLOSURE",
        False,
    ),
    "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS": ActionDefinition(
        "해당 지원사업의 공식 창구에 현재 조건과 신청 전 필요한 증빙을 확인한다. 신청이나 자격 확정이 아니다.",
        None,
        True,
    ),
}


def _evidence(
    refs: Sequence[str],
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> tuple[EvidenceRecord, ...]:
    if not refs or any(ref not in evidence_by_id for ref in refs):
        return ()
    expanded = expand_evidence([evidence_by_id[ref] for ref in refs], evidence_by_id)
    if any(
        parent not in evidence_by_id
        for item in expanded
        for parent in item.parent_evidence_refs
    ):
        return ()
    return (
        expanded
        if any(item.source_type in REQUIRED_CLAIM_SOURCES for item in expanded)
        else ()
    )


def build_action_candidates(
    sources: Sequence[ReviewSourceResult],
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> list[dict[str, Any]]:
    """List grounded action kinds; existing plan guards check Case constraints."""

    candidates: list[dict[str, Any]] = []

    def append(code: str, target: dict[str, Any]) -> None:
        definition = ACTION_DEFINITIONS[code]
        candidates.append(
            {
                "action_code": code,
                "target": target,
                "description": definition.description,
                "confirmation_only": definition.confirmation_only,
            }
        )

    for source in sources:
        output = source.output
        if isinstance(output, InfoAnalysisResult):
            for finding in output.procedure_findings:
                evidence = _evidence(finding.evidence_refs, evidence_by_id)
                if not evidence:
                    continue
                executable = (
                    finding.relevance == ProcedureRelevance.RELEVANT
                    and bool(finding.required_actions)
                    and all(
                        _evidence(action.evidence_refs, evidence_by_id)
                        for action in finding.required_actions
                    )
                    and all(
                        item.freshness_status == FreshnessStatus.CURRENT
                        for item in evidence
                    )
                )
                for code, definition in ACTION_DEFINITIONS.items():
                    if (
                        definition.procedure_step_code
                        == finding.procedure_step.step_code
                        and (definition.confirmation_only or executable)
                    ):
                        append(
                            code,
                            {
                                "target_kind": "PROCEDURE",
                                "procedure_step": finding.procedure_step.model_dump(
                                    mode="json"
                                ),
                            },
                        )
        elif isinstance(output, SupportAnalysisResult):
            for check in output.support_checks:
                if check.match_status != SupportMatchStatus.NOT_RELEVANT and _evidence(
                    check.evidence_refs, evidence_by_id
                ):
                    append(
                        "CONFIRM_SUPPORT_PROGRAM_REQUIREMENTS",
                        {
                            "target_kind": "SUPPORT_PROGRAM",
                            "support_program": check.support_program.model_dump(
                                mode="json"
                            ),
                        },
                    )
    return candidates
