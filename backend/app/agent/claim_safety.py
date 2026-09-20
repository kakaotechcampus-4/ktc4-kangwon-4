"""Shared deterministic policy for high-risk, user-visible Agent claims."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from app.agent.schemas import ClaimType, EvidenceRecord, EvidenceSourceType

# Korean particles are word characters, so a Unicode word boundary alone
# misses monetary claims in sentences. Keep an explicit suffix allowlist to
# avoid treating any word beginning with 원 as a currency expression.
_AMOUNT_PATTERN = re.compile(
    r"(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:억원|만원|원)"
    r"(?=\W|$|은|는|이|가|을|를|의|에|과|와|도|만|씩|부터|까지|보다|으로)"
)
_DATE_PATTERN = re.compile(
    r"(?:\b20\d{2}[-./]\d{1,2}(?:[-./]\d{1,2})?\b|"
    r"20\d{2}년\s*\d{1,2}월(?:\s*\d{1,2}일)?|"
    r"\b\d+\s*(?:일|개월|년)\s*(?:이내|전|후)\b)"
)
_LEGAL_PATTERN = re.compile(r"(?:법적으로|법적 의무|위법|합법|소송|배상 책임)")
_TAX_PATTERN = re.compile(r"(?:세법상|세금|부가세|소득세|종합소득세)")
_ELIGIBILITY_PATTERN = re.compile(
    r"(?:지원\s*(?:가능|대상|자격)|수령\s*(?:가능|확정)|자격(?:이|은)\s*(?:있|된다))"
)
_OVERCONFIDENT_PATTERN = re.compile(
    r"(?:확정입니다|확정되었습니다|확정됐습니다|보장됩니다|무조건|"
    r"반드시\s+받을\s+수|자격(?:이|은)\s+있습니다|"
    r"지원(?:금)?\s*가능합니다|지원\s*대상입니다|"
    r"법적으로\s+문제없습니다)"
)
_CONFIRMATION_CAVEAT_PATTERN = re.compile(
    r"(?:확인(?:이|을|해|하|해야|하세요|할|할지|필요)|문의|검토|"
    r"(?:인지|여부)|가능성|추정|예상|변경될\s*수|달라질\s*수|"
    r"정확한|최신\s*(?:공고|정보|기준)|confirm|verify|may|might)",
    re.IGNORECASE,
)
_PROCEDURE_PATTERN = re.compile(
    r"(?:폐업(?!\s*(?:지원|보조|장려|융자|컨설팅))|"
    r"휴업(?!\s*(?:지원|보조|장려|융자|컨설팅))|"
    r"철거(?!\s*(?:비|지원|보조|장려|융자))|"
    r"원상복구(?!\s*(?:비|지원|보조|장려|융자))|"
    r"사업자\s*등록|신고서|구비\s*서류|"
    r"관할\s*기관|허가\s*관청|신고\s*관청|홈택스|세무서|4대\s*보험|"
    r"사업장\s*소멸|행정\s*절차|"
    r"CLOSURE|DEMOLITION|RESTORATION|REPORT_CLOSURE|FILE_CLOSURE)"
)
_STRONG_PROCEDURE_ACTION_PATTERN = re.compile(
    r"(?:정부\s*24|민원\s*(?:신청|접수)|"
    r"(?:영업\s*)?(?:허가증|신고증|등록증)(?:을|를)?\s*(?:제출|반납)?|"
    r"(?:영업|사업)?\s*(?:허가|면허)(?:증)?(?:을|를)?\s*"
    r"(?:취소|해지|폐기|반납|말소|변경|신고|신청|접수|제출)|"
    r"(?:영업\s*)?신고(?:를|을)?\s*(?:취소|폐지|변경|접수|제출)|"
    r"(?:다음\s*)?(?:행정\s*)?(?:단계|절차)(?:를|을)?\s*"
    r"(?:진행|완료|끝내|이행)|"
    r"(?:CANCEL|CLOSE|TERMINATE|FILE|SUBMIT|RETURN)_"
    r"(?:BUSINESS_)?(?:REPORT|LICENSE|PERMIT|REGISTRATION))"
)
_WEAK_PROCEDURE_ACTION_PATTERN = re.compile(
    r"(?:온라인(?:으로)?\s*(?:신청|접수)|ONLINE_(?:FILE|SUBMIT))"
)
_SUPPORT_ACTION_CONTEXT_PATTERN = re.compile(
    r"(?:지원금|지원\s*사업|보조금|융자|장려금|SUPPORT_(?:PROGRAM|GRANT)|GRANT)"
)


def required_sources_for_claim(
    claim_type: ClaimType,
) -> frozenset[EvidenceSourceType]:
    """Return the Review-authoritative source allowlist for a claim type."""

    official = frozenset(
        {
            EvidenceSourceType.OFFICIAL_DOCUMENT,
            EvidenceSourceType.OFFICIAL_API,
        }
    )
    return official


def high_risk_metadata(
    text: str,
    support_program_names: frozenset[str],
) -> tuple[frozenset[ClaimType], frozenset[EvidenceSourceType]]:
    """Classify visible text using the exact policy shared by Supervisor/Review."""

    risk_types: set[ClaimType] = set()
    required: set[EvidenceSourceType] = set()
    official = {
        EvidenceSourceType.OFFICIAL_DOCUMENT,
        EvidenceSourceType.OFFICIAL_API,
    }
    if _AMOUNT_PATTERN.search(text):
        risk_types.add(ClaimType.AMOUNT)
        required.update(official)
    if _DATE_PATTERN.search(text):
        risk_types.add(ClaimType.DATE_OR_DEADLINE)
        required.update(official)
    if _LEGAL_PATTERN.search(text):
        risk_types.add(ClaimType.LEGAL)
        required.update(official)
    if _TAX_PATTERN.search(text):
        risk_types.add(ClaimType.TAX)
        required.update(official)
    if _ELIGIBILITY_PATTERN.search(text) or any(
        program_name in text for program_name in support_program_names
    ):
        risk_types.update({ClaimType.SUPPORT_PROGRAM, ClaimType.ELIGIBILITY})
        required.update(official)
    return frozenset(risk_types), frozenset(required)


def is_overconfident(text: str) -> bool:
    """Return whether text uses language Review always rejects."""

    return _OVERCONFIDENT_PATTERN.search(text) is not None


def has_confirmation_caveat(text: str) -> bool:
    """Return whether non-current high-risk text visibly signals uncertainty."""

    return _CONFIRMATION_CAVEAT_PATTERN.search(text) is not None


def has_explicit_eligibility_language(text: str) -> bool:
    """Return whether visible text itself makes a support-eligibility claim.

    A support-program name alone is not an eligibility conclusion.  Keeping
    this predicate separate prevents a generic ``SUPPORT_PROGRAM`` claim from
    satisfying the stricter ``ELIGIBILITY`` confirmation rule.
    """

    return _ELIGIBILITY_PATTERN.search(text) is not None


def has_procedure_language(*values: str) -> bool:
    """Return whether user-visible action text describes a closure procedure."""

    combined = " ".join(values)
    if (
        _PROCEDURE_PATTERN.search(combined) is not None
        or _STRONG_PROCEDURE_ACTION_PATTERN.search(combined) is not None
    ):
        return True
    if _SUPPORT_ACTION_CONTEXT_PATTERN.search(combined) is not None:
        return False
    return _WEAK_PROCEDURE_ACTION_PATTERN.search(combined) is not None


def has_support_action_language(*values: str) -> bool:
    """Return whether action text contains an explicit support-program signal.

    This is a deterministic defense-in-depth check for free text.  The typed
    action target remains the machine-authoritative scope, while independent
    Review handles meanings that cannot be proven from lexical signals alone.
    """

    return _SUPPORT_ACTION_CONTEXT_PATTERN.search(" ".join(values)) is not None


def references_other_known_label(
    text: str,
    *,
    selected_labels: Iterable[str],
    known_labels: Iterable[str],
) -> bool:
    """Detect an explicit known label other than the selected target labels.

    Labels are matched longest-first so overlapping names are unambiguous.  For
    example, selecting ``희망리턴패키지`` does not hide an explicit mention of
    ``희망리턴패키지 원스톱폐업지원``, while selecting the longer name does not
    falsely report its shorter substring as another target.
    """

    selected = {label for label in selected_labels if label}
    labels = sorted(
        {label for label in known_labels if label},
        key=lambda label: (-len(label), label),
    )
    if not labels:
        return False
    pattern = re.compile("|".join(re.escape(label) for label in labels))
    return any(match.group(0) not in selected for match in pattern.finditer(text))


def expand_evidence(
    evidence_records: Sequence[EvidenceRecord],
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> tuple[EvidenceRecord, ...]:
    """Expand evidence through its transitive parent links without looping."""

    expanded: list[EvidenceRecord] = []
    pending = list(evidence_records)
    seen: set[str] = set()
    while pending:
        evidence = pending.pop()
        if evidence.evidence_id in seen:
            continue
        seen.add(evidence.evidence_id)
        expanded.append(evidence)
        pending.extend(
            evidence_by_id[parent_ref]
            for parent_ref in evidence.parent_evidence_refs
            if parent_ref in evidence_by_id
        )
    return tuple(expanded)


__all__ = [
    "expand_evidence",
    "has_confirmation_caveat",
    "has_explicit_eligibility_language",
    "has_procedure_language",
    "has_support_action_language",
    "high_risk_metadata",
    "is_overconfident",
    "references_other_known_label",
    "required_sources_for_claim",
]
