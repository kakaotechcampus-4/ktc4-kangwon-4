"""화면 응답은 저장된 가림 문구를 유지한다. 기존 복원 함수의 보호 회귀도 함께 둔다."""

from types import SimpleNamespace

import pytest
from sqlmodel import Session
from unittest.mock import MagicMock

from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.services import case as case_service
from app.be.services.unmasking import HiddenTextRestorer, restore_hidden_text

CASE_ID = 7
FIRST_INPUT = "원상복구 범위는 서울특별시 마포구 월드컵북로 12 1층 전체입니다"
SECOND_INPUT = "다시 확인했더니 서울특별시 강남구 테헤란로 5 2층만 하면 된대요"


def histories():
    return [
        SimpleNamespace(id=11, raw_input=FIRST_INPUT),
        SimpleNamespace(id=22, raw_input=SECOND_INPUT),
    ]


def fail_original_lookup(*_args):
    raise AssertionError("화면 응답을 만들며 입력 원문을 읽었다")


def field_row(row_id: int, case_history_id: int, before: str | None, after: str | None):
    return SimpleNamespace(
        id=row_id, case_history_id=case_history_id, canonical_field="restoration_scope_detail",
        before_value=before, after_value=after,
    )


@pytest.fixture
def case_with_two_submissions(monkeypatch):
    """같은 칸을 두 번 바꾼 Case. 이전 값과 새 값이 서로 다른 제출에서 나온다."""

    rows = [
        field_row(1, 11, None, "서울특별시 마포구 [주소] 전체"),
        field_row(2, 22, "서울특별시 마포구 [주소] 전체", "서울특별시 강남구 [주소]만"),
    ]
    monkeypatch.setattr(case_history_crud, "get_case_histories_by_case_id", fail_original_lookup)
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_id", lambda *_: rows
    )
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_history_id",
        lambda _session, case_history_id: [r for r in rows if r.case_history_id == case_history_id],
    )
    return rows


def test_changes_keep_both_stored_values_hidden(case_with_two_submissions):
    """입력 원문이 있어도 화면 응답은 저장된 가림 문구를 그대로 쓴다(#258)."""

    changes = case_service._field_changes(MagicMock(spec=Session), 22)

    assert changes[0].stored_value == "서울특별시 마포구 [주소] 전체"
    assert changes[0].new_value == "서울특별시 강남구 [주소]만"


def test_a_conflict_keeps_both_sides_hidden(monkeypatch):
    """확인 전이라 두 번째 제출의 값은 아직 이력에 없다. Case에는 첫 제출의 값이 남아 있다."""

    monkeypatch.setattr(case_history_crud, "get_case_histories_by_case_id", fail_original_lookup)
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_id",
        lambda *_: [field_row(1, 11, None, "서울특별시 마포구 [주소] 전체")],
    )
    conflict = SimpleNamespace(
        id=3, case_history_id=22, canonical_field="restoration_scope_detail",
        committed_value="서울특별시 마포구 [주소] 전체",
        proposed_value="서울특별시 강남구 [주소]만",
    )

    items = case_service._conflict_items([conflict])

    assert items[0].stored_value == "서울특별시 마포구 [주소] 전체"
    assert items[0].proposed_value == "서울특별시 강남구 [주소]만"


def test_the_case_itself_keeps_free_text_hidden(case_with_two_submissions):
    case = SimpleNamespace(
        id=CASE_ID,
        model_dump=lambda: dict(
            id=CASE_ID, member_id=1, store_name=None, business_type="한식음식점", franchise_status=False,
            employee_count=2, has_business_loan=None, has_service_contracts=None,
            lease_status="LEASED_PAID", restoration_clause="UNKNOWN", restoration_status="IN_PROGRESS",
            restoration_scope="PARTIAL", restoration_scope_detail="서울특별시 강남구 [주소]만",
            demolition_required="NOT_REQUIRED", planned_closure_date=None,
            planned_closure_month=None, case_status="IN_PROGRESS", completed_at=None,
            closure_date=None, closure_reason=None,
            road_address=None, address_detail=None, deposit_return_result=None,
        ),
    )

    detail = case_service._case_detail(case)

    assert detail.restoration_scope_detail == "서울특별시 강남구 [주소]만"


def test_a_value_without_a_hidden_spot_is_left_alone(monkeypatch):
    """되돌릴 게 없으면 입력 원문을 읽지 않는다. 화면마다 질의가 늘면 안 된다."""

    def fail(*_args, **_kwargs):
        raise AssertionError("되돌릴 게 없는데 입력 원문을 읽었다")

    rows = [field_row(1, 11, "FULL", "PARTIAL")]
    monkeypatch.setattr(case_history_crud, "get_case_histories_by_case_id", fail)
    monkeypatch.setattr(case_field_history_crud, "get_case_field_histories_by_case_id", fail)
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_history_id", lambda *_: rows
    )

    changes = case_service._field_changes(MagicMock(spec=Session), 11)

    assert changes[0].new_value == "PARTIAL"


def test_only_part_of_the_hidden_addresses_ends_up_in_the_value(monkeypatch):
    """AI가 주소 둘 중 뒤엣것만 값에 담으면, 순서로 짝지을 때 앞엣것이 들어간다(현석님 #111 리뷰)."""

    raw_input = (
        "지금 매장은 서울특별시 마포구 월드컵북로 12 1층인데, "
        "원상복구 범위는 서울특별시 강남구 테헤란로 5 2층 전체래요."
    )
    value = "서울특별시 강남구 [주소] 전체"

    assert restore_hidden_text(value, raw_input) == value


def test_the_value_puts_the_hidden_addresses_in_a_different_order(monkeypatch):
    """개수가 같아도 AI가 순서를 바꿔 쓰면 서로 뒤바뀐다(승준님 #111 리뷰).

    AI가 값에 쓰는 말은 원문 순서를 지킬 의무가 없다. 그래서 개수를 맞춰 보는 것으로는
    막히지 않고, 가린 글자가 서로 다르면 손대지 않는 수밖에 없다.
    """

    raw_input = (
        "원상복구 제외 범위는 서울특별시 마포구 월드컵북로 12 1층이고, "
        "포함 범위는 서울특별시 강남구 테헤란로 5 2층입니다."
    )
    value = "포함: 서울특별시 강남구 [주소], 제외: 서울특별시 마포구 [주소]"

    assert restore_hidden_text(value, raw_input) == value


def test_the_same_text_hidden_twice_is_still_restored():
    # 가린 글자가 같으면 어느 것과 짝지어도 결과가 같다. 이때까지 막을 이유는 없다.
    restored = restore_hidden_text(
        "[주소]에서 [주소]로", "마포구 월드컵북로 12에서 마포구 월드컵북로 12로"
    )

    assert restored == "월드컵북로 12에서 월드컵북로 12로"


def test_one_kind_being_unclear_does_not_block_the_others():
    restored = restore_hidden_text(
        "[주소] / [전화번호]", "마포구 월드컵북로 12 그리고 010-1234-5678과 02-123-4567"
    )

    assert restored == "월드컵북로 12 / [전화번호]"


def test_an_unknown_submission_leaves_the_value_hidden(monkeypatch):
    # 어느 입력에서 나온 값인지 모르면 되돌릴 짝도 없다. 가린 채로 두는 쪽이 안전하다.
    monkeypatch.setattr(case_history_crud, "get_case_histories_by_case_id", lambda *_: histories())
    monkeypatch.setattr(case_field_history_crud, "get_case_field_histories_by_case_id", lambda *_: [])
    restorer = HiddenTextRestorer(MagicMock(spec=Session), CASE_ID)

    assert restorer.restore("마포구 [주소] 전체", None) == "마포구 [주소] 전체"
    assert restorer.restore("마포구 [주소] 전체", 999) == "마포구 [주소] 전체"


@pytest.fixture
def case_whose_last_change_came_from_a_conflict_decision(monkeypatch):
    """충돌 결정으로 값이 바뀐 Case. 그 이력에는 사장님이 쓴 글이 없다.

    충돌 결정은 버튼을 누른 것이라 raw_input이 NULL이다(services/case.py의
    submit_case_conflicts_decision). 되돌릴 원문을 그 이력에서 찾으면 없다.
    """

    rows = [
        field_row(1, 11, None, "서울특별시 마포구 [주소] 전체"),
        field_row(2, 33, "서울특별시 마포구 [주소] 전체", "서울특별시 마포구 [주소] 일부"),
    ]
    monkeypatch.setattr(
        case_history_crud, "get_case_histories_by_case_id",
        fail_original_lookup,
    )
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_id", lambda *_: rows
    )
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_history_id",
        lambda _session, case_history_id: [r for r in rows if r.case_history_id == case_history_id],
    )
    # 결정이 끝난 충돌 한 줄. "이 칸의 값이 11번 제출에서 나왔다"가 여기 남아 있다.
    monkeypatch.setattr(
        conflict_reference_crud, "get_decided_conflicts_by_case_id",
        lambda *_: [SimpleNamespace(
            canonical_field="restoration_scope_detail", case_history_id=11,
            status="CONFIRMED", resolved_by_case_history_id=33,
        )],
    )
    return rows


def test_a_conflict_decision_keeps_changed_values_hidden(
    case_whose_last_change_came_from_a_conflict_decision
):
    """충돌 결정이 바꾼 값도 원문을 찾아 복원하지 않는다."""

    changes = case_service._field_changes(MagicMock(spec=Session), 33)

    assert changes[0].stored_value == "서울특별시 마포구 [주소] 전체"
    assert changes[0].new_value == "서울특별시 마포구 [주소] 일부"


def decided(case_history_id: int, closed_by: int, status: str = "CONFIRMED"):
    """결정이 끝난 충돌 한 줄. 어느 제출에서 나왔고 어느 결정이 닫았는지가 들어 있다."""
    return SimpleNamespace(
        canonical_field="restoration_scope_detail",
        case_history_id=case_history_id,
        status=status,
        resolved_by_case_history_id=closed_by,
    )


def restorer_with(monkeypatch, conflicts):
    """결정 이력 둘(22·44)이 섞인 Case. 22번이 만든 값을 되돌려 본다."""
    monkeypatch.setattr(
        case_history_crud, "get_case_histories_by_case_id",
        lambda *_: [
            SimpleNamespace(id=11, raw_input=FIRST_INPUT),
            SimpleNamespace(id=22, raw_input=None),
            SimpleNamespace(id=33, raw_input=SECOND_INPUT),
            SimpleNamespace(id=44, raw_input=None),
        ],
    )
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_id", lambda *_: []
    )
    monkeypatch.setattr(
        conflict_reference_crud, "get_decided_conflicts_by_case_id", lambda *_: conflicts
    )
    return HiddenTextRestorer(MagicMock(spec=Session), CASE_ID)


def test_the_same_field_decided_twice_still_restores_each_from_its_own_submission(monkeypatch):
    """같은 칸을 두 번 결정해도 각 결정이 자기 제출의 글로 되돌린다.

    전에는 칸 이름으로 충돌을 찾아서 어느 결정이 지금 보는 값을 만들었는지 가릴 수 없었고,
    "마포구 테헤란로 5 2층"처럼 두 주소가 섞인 글자가 나왔다(승준님 #158 리뷰). 지금은
    충돌 줄에 닫은 결정이 적혀 있어서 결정에서 제출로 바로 간다.
    """
    restorer = restorer_with(monkeypatch, [decided(11, closed_by=22), decided(33, closed_by=44)])

    assert restorer.restore("서울특별시 마포구 [주소] 전체", 22) == (
        "서울특별시 마포구 월드컵북로 12 1층 전체"
    )
    assert restorer.restore("서울특별시 강남구 [주소]만", 44) == "서울특별시 강남구 테헤란로 5 2층만"


def test_a_rejected_proposal_does_not_reach_another_decision(monkeypatch):
    """거절한 제안의 글이 다른 결정이 만든 값에 섞이지 않는다.

    채택·거절을 가르지 않아도 된다. 거절한 충돌은 그것을 닫은 결정에만 달려 있고, 그 결정이
    바꾼 값은 어차피 같은 제출에서 나온 것이기 때문이다.
    """
    restorer = restorer_with(
        monkeypatch, [decided(11, closed_by=22), decided(33, closed_by=44, status="REJECTED")]
    )

    assert restorer.restore("서울특별시 마포구 [주소] 전체", 22) == (
        "서울특별시 마포구 월드컵북로 12 1층 전체"
    )


def test_a_fact_that_was_not_a_conflict_is_restored_too(monkeypatch):
    """충돌이 아니었던 칸도 같은 길로 되돌아온다(현석님 #161 리뷰).

    한 글에서 하나만 충돌이면 나머지는 보관됐다 결정 뒤 재판단에서 저장된다(#161). 그 값의
    출처도 결정 이력이라 글이 없는데, 전에는 "그 칸의 충돌"을 찾는 방식이라 애초에 충돌이
    아니었던 칸은 걸리지 않아 [주소]가 그대로 보였다.
    """
    restorer = restorer_with(monkeypatch, [decided(11, closed_by=22)])

    # 임대차 형태가 충돌이었고, 원상복구 범위는 같은 글에 있었을 뿐 충돌이 아니었다.
    restored = restorer.restore("서울특별시 마포구 [주소] 전체", 22)

    assert restored == "서울특별시 마포구 월드컵북로 12 1층 전체"


def test_a_decision_that_closed_two_submissions_restores_nothing(monkeypatch):
    """한 결정이 서로 다른 제출의 충돌을 닫았으면 되돌리지 않는다.

    확인을 기다리는 충돌이 있는 동안은 새 제출이 막혀서(submit_case_results의 409) 지금은
    나지 않는 모양이다. 그래도 어느 글이 그 값을 만들었는지 가릴 수 없으면 가린 채로 둔다.
    """
    restorer = restorer_with(monkeypatch, [decided(11, closed_by=22), decided(33, closed_by=22)])

    assert restorer.restore("서울특별시 마포구 [주소] 전체", 22) == "서울특별시 마포구 [주소] 전체"


def test_a_conflict_closed_before_this_link_existed_stays_hidden(monkeypatch):
    """이 칸이 생기기 전에 닫힌 충돌은 NULL이라 따라갈 데가 없다."""

    restorer = restorer_with(monkeypatch, [decided(11, closed_by=None)])

    assert restorer.restore("서울특별시 마포구 [주소] 전체", 22) == "서울특별시 마포구 [주소] 전체"
