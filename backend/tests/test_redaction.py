"""AI에게 넘기기 전에 개인정보가 지워지는지. 모델도 DB도 부르지 않는다.

여기서 못 지우면 두 가지가 같이 깨진다. 사장님 개인정보가 모델 요청에 그대로 들어가고,
AI 입구 검사(app/agent/guardrails.py)에 걸려 판단 자체가 거절된다.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.agent.guardrails import GuardrailViolation, ensure_no_sensitive_text
from app.agent.schemas import EvidenceSourceType, RedactionType
from app.be.models.mixins import KST
from app.be.services.case_snapshot import _build_evidence_record, build_user_input
from app.be.services.redaction import redact

SUBMITTED_AT = datetime(2026, 10, 26, 9, 0, 0)


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        pytest.param("연락처는 010-1234-5678이에요", "연락처는 [전화번호]이에요", id="전화번호"),
        pytest.param("01012345678로 주세요", "[전화번호]로 주세요", id="하이픈 없는 전화번호"),
        pytest.param("사업자 123-45-67890입니다", "사업자 [사업자등록번호]입니다", id="사업자등록번호"),
        pytest.param("900101-1234567", "[주민등록번호]", id="주민등록번호"),
        pytest.param("boss@example.com으로", "[이메일]으로", id="이메일"),
    ],
)
def test_written_personal_information_is_replaced(written, expected):
    assert redact(written)[0] == expected


def test_address_keeps_the_district_because_the_procedure_depends_on_it():
    # 관할 구청이 어디인지가 폐업 절차를 가른다. 주소를 통째로 지우면 안내가 틀어진다.
    masked, redactions = redact("서울특별시 마포구 월드컵북로 12 3층에서 장사했습니다")

    assert masked == "서울특별시 마포구 [주소]에서 장사했습니다"
    assert [r.type for r in redactions] == [RedactionType.ADDRESS]


@pytest.mark.parametrize(
    "written",
    [
        pytest.param("다시 확인했는데 당시 건물주가 철거동의서가 필요하다고 했어요", id="시/가로 끝나는 보통 말"),
        pytest.param("임대인이 3월 31일까지 비우라고 했어요", id="날짜"),
        pytest.param("권리금 2000만원을 못 받았습니다", id="금액"),
        pytest.param("서울 마포구에서 장사했어요", id="상세 주소가 없는 지역"),
    ],
)
def test_ordinary_sentences_are_left_alone(written):
    # 멀쩡한 말을 가리면 AI가 판단할 근거를 잃는다. 덜 가리는 것보다 이쪽이 더 조용히 나쁘다.
    assert redact(written)[0] == written


def test_what_we_hide_covers_what_the_agent_refuses():
    # 가리는 범위가 AI 입구 검사보다 좁으면, 사장님이 쓴 글 때문에 판단이 거절된다.
    written = "010-1234-5678, 123-45-67890, 900101-1234567, bearer abcdefghijkl1234"

    with pytest.raises(GuardrailViolation):
        ensure_no_sensitive_text([written])
    ensure_no_sensitive_text([redact(written)[0]])


def test_the_marked_spots_point_at_the_hidden_text_not_the_original():
    """위치는 가린 뒤 글 기준이다. 원문 기준으로 주면 AI 계약이 입력을 거절한다."""

    user_input = build_user_input(1, "제 번호 010-1234-5678과 메일 boss@example.com", SUBMITTED_AT)

    assert [r.placeholder for r in user_input.redactions] == ["[전화번호]", "[이메일]"]
    for redaction in user_input.redactions:
        span = user_input.redacted_text[redaction.start_offset : redaction.end_offset]
        assert span == redaction.placeholder


def test_the_original_submitted_time_is_kept():
    assert build_user_input(1, "철거해야 한대요", SUBMITTED_AT).submitted_at == SUBMITTED_AT.replace(tzinfo=KST)


def evidence(excerpt: str, source_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=1, evidence_id="ev_1", source_type=source_type, source_ref="case_history",
        source_version=None, locator=None, excerpt=excerpt, published_at=None,
        retrieved_at=SUBMITTED_AT, freshness_status="CURRENT", content_hash=None,
    )


def test_a_stored_user_sentence_is_hidden_too():
    # 최신 입력만 가려도 같은 글이 근거로 남아 있으면 검수 모델이 원문을 그대로 받는다.
    record = _build_evidence_record(evidence("010-1234-5678로 연락왔어요", "USER_INPUT"), [])

    assert record.excerpt == "[전화번호]로 연락왔어요"


def test_official_source_text_is_not_touched():
    # 공식 자료는 사람이 쓴 글이 아니고, 가리면 같이 저장된 content_hash와 어긋난다.
    official = "폐업신고는 관할 세무서 126-00-00000 담당 창구에서 접수한다"
    record = _build_evidence_record(evidence(official, EvidenceSourceType.OFFICIAL_DOCUMENT), [])

    assert record.excerpt == official


def test_a_number_right_after_an_address_is_not_half_swallowed():
    # 주소 뒤에 번호가 바로 붙으면 앞자리가 주소로 먼저 잡혀 번호가 반만 가려질 수 있다.
    masked, redactions = redact("마포구 월드컵북로 12 010-1234-5678")

    assert masked == "마포구 [주소] [전화번호]"
    # 계약은 겹친 자리를 거절한다. 두 규칙이 같은 글자를 가리키면 입력이 통째로 막힌다.
    build_user_input(1, "마포구 월드컵북로 12 010-1234-5678", SUBMITTED_AT)


def test_two_rules_matching_the_same_text_do_not_both_mark_it():
    # 토큰과 이메일처럼 모양이 겹치는 글자가 있다. 둘 다 적으면 계약이 입력을 거절한다.
    user_input = build_user_input(1, "열쇠 sk-abcdefghijklmn@x.com 입니다", SUBMITTED_AT)

    assert "sk-abcdefghijklmn" not in user_input.redacted_text
    assert len(user_input.redactions) == 1


@pytest.mark.parametrize(
    "written",
    [
        pytest.param("서울 마포구 2명 있습니다", id="직원 수"),
        pytest.param("마포구 3월 31일 철거해야 합니다", id="기한"),
        pytest.param("마포구 4대보험 정리해야 해요", id="보험"),
        pytest.param("2026-10-26까지 비워야 해요", id="날짜"),
        pytest.param("저희 사장님이 그랬어요", id="직함만 부른 말"),
        pytest.param("임대인님이 철거하래요", id="관계를 부른 말"),
        pytest.param("이사님께 물어봤어요", id="성씨처럼 보이는 직함"),
        pytest.param("손님이 많았어요", id="성씨처럼 보이는 보통 말"),
        pytest.param("건물주님이 거절했어요", id="성씨가 아닌 말로 시작하는 호칭"),
        pytest.param("회계사님께 물어봤어요", id="목록에 없는 직함"),
        pytest.param("어머님이 보증 서주셨어요", id="가족을 부르는 말"),
        pytest.param("마포구 12명 일했어요", id="지역 뒤 두 자리 숫자"),
    ],
)
def test_numbers_and_titles_next_to_a_district_are_not_addresses_or_names(written):
    """지역 뒤 숫자를 주소로, 직함을 이름으로 보면 AI가 판단할 근거를 잃는다(승준님 #109 리뷰)."""

    assert redact(written)[0] == written


def test_a_national_id_is_hidden_even_when_the_back_part_starts_with_other_digits():
    # AI 입구 검사는 뒷자리를 따지지 않는다. 여기서 좁히면 안 가려진 채 거절당한다.
    masked = redact("900101-5234567")[0]

    assert masked == "[주민등록번호]"
    ensure_no_sensitive_text([masked])


def test_a_building_name_in_the_middle_does_not_stop_the_address():
    masked = redact("서울특별시 마포구 월드컵북로 12 가온빌딩 305호예요")[0]

    assert masked == "서울특별시 마포구 [주소]예요"


def test_an_account_number_is_hidden():
    assert redact("계좌번호는 110-123-456789입니다")[0] == "계좌번호는 [계좌번호]입니다"


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        pytest.param("제 이름은 김철수입니다", "제 이름은 [이름]입니다", id="밝히고 쓴 이름"),
        pytest.param("김철수씨가 왔어요", "[이름]씨가 왔어요", id="씨를 붙여 부른 이름"),
        pytest.param("김철수 사장님이 그랬어요", "[이름] 사장님이 그랬어요", id="직함을 붙여 부른 이름"),
    ],
)
def test_a_name_is_hidden_where_it_is_clearly_a_name(written, expected):
    # 이름은 다른 말과 모양이 같아서, 이름이라고 밝혔거나 부르는 자리에서만 가린다.
    assert redact(written)[0] == expected
