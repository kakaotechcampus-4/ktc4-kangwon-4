"""Pin the current behaviour of the deterministic claim policy.

The mentor asked that this module's design and implementation be left alone
until after the MVP release, so nothing here changes it.  These tests record
what it does today: the regular expressions are the part hardest to reason
about, several of them had no direct coverage at all, and a later hardening
pass needs a way to see what it moved.

Each case states the intent, not just the string, so a future change can tell
"this was deliberate" from "this broke".
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.agent.claim_safety import (
    expand_evidence,
    has_confirmation_caveat,
    has_explicit_eligibility_language,
    has_procedure_language,
    has_support_action_language,
    high_risk_metadata,
    is_overconfident,
    references_other_known_label,
    required_sources_for_claim,
)
from app.agent.schemas import ClaimType, EvidenceRecord, EvidenceSourceType

NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)
OFFICIAL = frozenset(
    {EvidenceSourceType.OFFICIAL_DOCUMENT, EvidenceSourceType.OFFICIAL_API}
)
NO_PROGRAMS: frozenset[str] = frozenset()


def evidence(evidence_id: str, *parents: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type="OFFICIAL_DOCUMENT",
        source_ref="https://www.easylaw.go.kr/CSP/x.laf",
        source_version=None,
        locator="https://www.easylaw.go.kr/CSP/x.laf",
        excerpt="공식 안내 발췌",
        parent_evidence_refs=list(parents),
        published_at=None,
        retrieved_at=NOW,
        freshness_status="UNKNOWN",
        content_hash=None,
    )


@pytest.mark.parametrize(
    "text",
    ["철거비 1,200,000원", "지원금 300만원", "1억원", "수수료 30000 원"],
)
def test_money_amounts_demand_an_official_source(text: str) -> None:
    risks, required = high_risk_metadata(text, NO_PROGRAMS)

    assert ClaimType.AMOUNT in risks
    assert required == OFFICIAL


@pytest.mark.parametrize(
    "text",
    [
        "철거비 1,200,000원이 듭니다",
        "지원금 300만원을 받습니다",
        "보증금 1억원은 별도입니다",
        "수수료 30000원입니다",
    ],
)
def test_known_gap_an_amount_followed_by_a_particle_is_missed(text: str) -> None:
    """KNOWN GAP, recorded rather than fixed.

    ``_AMOUNT_PATTERN`` ends in ``\b`` after the currency unit.  Korean
    particles are word characters, so ``원이``/``원을``/``원입니다`` leave no
    boundary and the amount is not detected -- which is most real sentences.

    The mentor asked that this module be left as it is until after the MVP
    release, so this pins the hole instead of closing it.  Review still has to
    catch these; the deterministic layer does not.  When the pattern is
    hardened, this test should start failing, and that is the signal to move
    these cases into the test above.
    """

    risks, _ = high_risk_metadata(text, NO_PROGRAMS)

    assert ClaimType.AMOUNT not in risks


@pytest.mark.parametrize(
    "text",
    ["2026-09-30까지", "2026년 9월 30일", "2026.9.30", "25일 이내", "3개월 후"],
)
def test_dates_and_relative_deadlines_demand_an_official_source(text: str) -> None:
    risks, required = high_risk_metadata(text, NO_PROGRAMS)

    assert ClaimType.DATE_OR_DEADLINE in risks
    assert required == OFFICIAL


@pytest.mark.parametrize(
    "text",
    ["세법상 신고 대상입니다", "부가세 확정신고", "종합소득세 신고", "세금 문제"],
)
def test_tax_wording_demands_an_official_source(text: str) -> None:
    risks, required = high_risk_metadata(text, NO_PROGRAMS)

    assert ClaimType.TAX in risks
    assert required == OFFICIAL


@pytest.mark.parametrize(
    "text",
    ["법적으로 필요합니다", "법적 의무입니다", "위법 소지", "배상 책임", "소송"],
)
def test_legal_wording_demands_an_official_source(text: str) -> None:
    risks, _ = high_risk_metadata(text, NO_PROGRAMS)

    assert ClaimType.LEGAL in risks


def test_eligibility_wording_raises_both_support_and_eligibility_risk() -> None:
    risks, required = high_risk_metadata("지원 대상 여부", NO_PROGRAMS)

    assert {ClaimType.SUPPORT_PROGRAM, ClaimType.ELIGIBILITY} <= risks
    assert required == OFFICIAL


def test_naming_a_known_program_is_risky_even_without_eligibility_wording() -> None:
    risks, _ = high_risk_metadata(
        "희망리턴패키지를 확인해 보세요",
        frozenset({"희망리턴패키지"}),
    )

    assert ClaimType.SUPPORT_PROGRAM in risks
    # A program name alone is not a conclusion about this user.
    assert not has_explicit_eligibility_language("희망리턴패키지를 확인해 보세요")


def test_plain_text_carries_no_risk_and_needs_no_source() -> None:
    assert high_risk_metadata("임대인과 일정을 조율해 보세요", NO_PROGRAMS) == (
        frozenset(),
        frozenset(),
    )


@pytest.mark.parametrize(
    "text",
    [
        "지원 대상입니다",
        "자격이 있습니다",
        "확정되었습니다",
        "보장됩니다",
        "무조건 받을 수 있습니다",
        "법적으로 문제없습니다",
    ],
)
def test_settled_sounding_wording_is_rejected(text: str) -> None:
    assert is_overconfident(text)


@pytest.mark.parametrize(
    "text",
    ["지원 대상인지 확인이 필요합니다", "달라질 수 있습니다", "세무서에 문의하세요"],
)
def test_hedged_wording_is_not_rejected(text: str) -> None:
    assert not is_overconfident(text)
    assert has_confirmation_caveat(text)


def test_text_with_no_hedge_is_reported_as_having_none() -> None:
    assert not has_confirmation_caveat("폐업 신고를 합니다")


def test_procedure_wording_is_recognised() -> None:
    assert has_procedure_language("홈택스에서 폐업 신고를 합니다")
    assert has_procedure_language("정부24 민원 신청")


def test_support_wording_alone_is_not_treated_as_a_procedure() -> None:
    # "온라인 신청" is only a weak signal, and a support context outranks it, so
    # applying for a grant is not mistaken for a closure filing.
    assert not has_procedure_language("지원금 온라인 신청")
    assert has_support_action_language("지원금 온라인 신청")


def test_a_weak_signal_counts_as_a_procedure_without_a_support_context() -> None:
    assert has_procedure_language("온라인으로 신청")


def test_support_wording_is_absent_from_a_plain_procedure_sentence() -> None:
    assert not has_support_action_language("세무서에 폐업 신고서를 제출")


def test_a_mention_of_another_known_program_is_detected() -> None:
    assert references_other_known_label(
        "희망리턴패키지와 재도전장려금을 비교했습니다",
        selected_labels=["희망리턴패키지"],
        known_labels=["희망리턴패키지", "재도전장려금"],
    )


def test_the_selected_program_alone_is_not_reported_as_another_one() -> None:
    assert not references_other_known_label(
        "희망리턴패키지를 안내했습니다",
        selected_labels=["희망리턴패키지"],
        known_labels=["희망리턴패키지", "재도전장려금"],
    )


def test_a_longer_program_name_is_matched_before_its_shorter_prefix() -> None:
    assert references_other_known_label(
        "희망리턴패키지 원스톱폐업지원 안내",
        selected_labels=["희망리턴패키지"],
        known_labels=["희망리턴패키지", "희망리턴패키지 원스톱폐업지원"],
    )


@pytest.mark.parametrize("claim_type", list(ClaimType))
def test_every_claim_type_currently_requires_an_official_source(
    claim_type: ClaimType,
) -> None:
    # Today the claim type is not consulted; every type gets the same official
    # allowlist. Pinned so a future per-type policy is a visible change rather
    # than a silent one.
    assert required_sources_for_claim(claim_type) == OFFICIAL


def test_evidence_expansion_follows_parents_and_stops_on_a_cycle() -> None:
    child = evidence("ev:child", "ev:parent")
    parent = evidence("ev:parent", "ev:child")
    expanded = expand_evidence([child], {"ev:child": child, "ev:parent": parent})

    assert {item.evidence_id for item in expanded} == {"ev:child", "ev:parent"}


def test_evidence_expansion_ignores_a_parent_it_was_not_given() -> None:
    child = evidence("ev:child", "ev:missing")
    expanded = expand_evidence([child], {"ev:child": child})

    assert [item.evidence_id for item in expanded] == ["ev:child"]
