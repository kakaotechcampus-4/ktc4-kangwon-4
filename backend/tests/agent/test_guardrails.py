from datetime import datetime, timezone
from uuid import UUID

import pytest
from app.agent.guardrails import (
    GuardrailViolation,
    canonical_json,
    ensure_known_refs,
    ensure_no_sensitive_text,
    exact_span,
    sha256_digest,
)

pytestmark = pytest.mark.real_data


def test_canonical_digest_is_stable_across_mapping_order() -> None:
    instant = datetime(2026, 9, 14, 1, 2, 3, tzinfo=timezone.utc)
    identifier = UUID("00000000-0000-0000-0000-000000000001")

    left = {"b": identifier, "a": instant}
    right = {"a": instant, "b": identifier}

    assert canonical_json(left) == canonical_json(right)
    assert sha256_digest(left) == sha256_digest(right)
    assert sha256_digest(left).startswith("sha256:")


def test_exact_span_rejects_model_text_not_in_input() -> None:
    assert exact_span("철거가 필요하다고 합니다.", "철거가 필요") == (0, 6)

    with pytest.raises(GuardrailViolation, match="not present"):
        exact_span("철거 여부는 모릅니다.", "철거가 필요")


def test_unknown_reference_is_rejected() -> None:
    with pytest.raises(GuardrailViolation, match="evidence"):
        ensure_known_refs(["evidence:made-up"], ["evidence:known"], label="evidence")


@pytest.mark.parametrize(
    "value",
    [
        "주민번호 900101-1234567",
        "사업자등록번호 123-45-67890 입니다",
        "Authorization: Bearer abcdefghijklmnop",
        "키는 sk-abcdefghijklmnop 입니다",
    ],
)
def test_obvious_sensitive_output_is_rejected(value: str) -> None:
    with pytest.raises(GuardrailViolation, match="sensitive output"):
        ensure_no_sensitive_text([value])


@pytest.mark.parametrize(
    "value",
    [
        # A run's own grounding: an evidence digest and an official document
        # link. Both contain 3-2-5 digit runs once spaces are allowed as
        # separators, so a wider business-number pattern would reject them.
        "sha256:a455e29c4868005c74711d0130145877ff1cdb3e9aa83a5bcfd4",
        "https://1350.moel.go.kr/rtmview.do?id=1000281283",
        "지원 한도는 300만원이고 접수는 2026년 3월 2일까지입니다",
        "문의는 063-717-1313 또는 1588-0700입니다",
    ],
)
def test_real_source_material_is_not_treated_as_sensitive(value: str) -> None:
    """Grounding and contact details have to survive the check.

    Blocking these would not protect anyone: they are what the answer is built
    from, and losing them means the user cannot be told where to apply.
    """

    ensure_no_sensitive_text([value])
