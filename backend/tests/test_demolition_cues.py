"""Particle-only differences must not change which demolition fact is extracted.

``철거해야`` was accepted and ``철거를 해야`` was not, so a user who wrote the
sentence the second way had nothing extracted at all. These checks pin both
directions: the added particle forms are accepted, and every negated or
uncertain phrasing still fails.
"""

import pytest

from app.agent.info_agent.agent import ExtractedFactDraft, InfoAnalysisAgent


def fact(value, source_text):
    return ExtractedFactDraft(
        operation="SET",
        field_path="demolition_required",
        value_type="ENUM",
        value=value,
        source_text=source_text,
        confidence_bps=9000,
        requires_confirmation=False,
        reason_summary="임대인 확인 결과",
    )


def supports(value, sentence):
    return InfoAnalysisAgent._fact_source_supports_value(
        fact(value, sentence), input_text=sentence
    )


@pytest.mark.parametrize(
    "sentence",
    [
        "임대인이 철거해야 한다고 했어요.",
        "임대인이 철거를 해야 한다고 했어요.",
        "임대인이 철거가 필요하다고 했어요.",
        "임대인이 철거는 필요하다고 했어요.",
        "철거도 필요합니다.",
    ],
)
def test_particle_variants_assert_demolition_required(sentence):
    assert supports("REQUIRED", sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "임대인이 철거는 필요하지 않다고 했어요.",
        "임대인이 철거가 필요하지 않다고 했어요.",
        "임대인이 철거는 필요없다고 했어요.",
        "임대인이 철거하지 않아도 된다고 했어요.",
        "임대인이 철거는 불필요하다고 했어요.",
        "철거도 필요하지 않습니다.",
    ],
)
def test_negated_phrasings_never_assert_required(sentence):
    # The whole point of widening the cue list is that it must not start
    # reading a refusal as a requirement.
    assert not supports("REQUIRED", sentence)
    assert supports("NOT_REQUIRED", sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "임대인이 철거를 해야 하는지 모르겠어요.",
        "철거가 필요한지 여부를 아직 못 들었어요.",
        "임대인에게 철거해야 하는지 확인해야 해요.",
    ],
)
def test_uncertain_phrasings_assert_nothing(sentence):
    assert not supports("REQUIRED", sentence)
    assert not supports("NOT_REQUIRED", sentence)


@pytest.mark.parametrize("sentence", [
    "철거도 필요하지 않은 것은 아닙니다.",
    "철거도 필요하지 않을 수도 있습니다.",
    "철거도 필요하지 않은 것 같습니다.",
    "철거도 필요하지 않나요.",
])
def test_unconfirmed_demolition_with_additive_particle_is_not_asserted(sentence):
    assert not supports("REQUIRED", sentence)
    assert not supports("NOT_REQUIRED", sentence)


def test_short_quote_cannot_hide_demolition_negation():
    assert not InfoAnalysisAgent._fact_source_supports_value(
        fact("REQUIRED", "철거도 필요"), input_text="철거도 필요하지 않습니다."
    )
