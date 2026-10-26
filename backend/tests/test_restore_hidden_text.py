"""화면에 돌려줄 때만 가림 문구를 원래 글자로 되돌리는지. DB 연결 없이 crud만 바꿔 끼운다.

AI는 가린 글을 보고 값을 쓰므로 자유 글 칸에 가림 문구가 섞여 들어온다. 저장은 가린 채로
두고(그래야 다음 판단에 개인정보가 다시 안 나간다) 화면에 낼 때만 되돌린다. 여기서 틀리면
사장님이 남의 주소를 자기 것으로 보게 된다.
"""

from types import SimpleNamespace

import pytest
from sqlmodel import Session
from unittest.mock import MagicMock

from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
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
    monkeypatch.setattr(case_history_crud, "get_case_histories_by_case_id", lambda *_: histories())
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_id", lambda *_: rows
    )
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_history_id",
        lambda _session, case_history_id: [r for r in rows if r.case_history_id == case_history_id],
    )
    return rows


def test_the_old_value_is_restored_from_the_submission_that_made_it(case_with_two_submissions):
    """이전 값과 새 값을 같은 입력으로 되돌리면, 이전 값 자리에 새 주소가 들어간다."""

    changes = case_service._field_changes(MagicMock(spec=Session), CASE_ID, 22)

    assert changes[0].stored_value == "서울특별시 마포구 월드컵북로 12 1층 전체"
    assert changes[0].new_value == "서울특별시 강남구 테헤란로 5 2층만"


def test_a_conflict_shows_each_side_with_its_own_submission(monkeypatch):
    """확인 전이라 두 번째 제출의 값은 아직 이력에 없다. Case에는 첫 제출의 값이 남아 있다."""

    monkeypatch.setattr(case_history_crud, "get_case_histories_by_case_id", lambda *_: histories())
    monkeypatch.setattr(
        case_field_history_crud, "get_case_field_histories_by_case_id",
        lambda *_: [field_row(1, 11, None, "서울특별시 마포구 [주소] 전체")],
    )
    conflict = SimpleNamespace(
        id=3, case_history_id=22, canonical_field="restoration_scope_detail",
        committed_value="서울특별시 마포구 [주소] 전체",
        proposed_value="서울특별시 강남구 [주소]만",
    )

    items = case_service._conflict_items(MagicMock(spec=Session), CASE_ID, [conflict])

    assert items[0].stored_value == "서울특별시 마포구 월드컵북로 12 1층 전체"
    assert items[0].proposed_value == "서울특별시 강남구 테헤란로 5 2층만"


def test_the_case_itself_shows_the_restored_free_text(case_with_two_submissions):
    case = SimpleNamespace(
        id=CASE_ID,
        model_dump=lambda: dict(
            id=CASE_ID, member_id=1, business_type="한식음식점", franchise_status=False,
            employee_count=2, lease_status="LEASED_PAID", restoration_status="IN_PROGRESS",
            restoration_scope="PARTIAL", restoration_scope_detail="서울특별시 강남구 [주소]만",
            demolition_required="NOT_REQUIRED", planned_closure_date=None,
        ),
    )

    detail = case_service._case_detail(MagicMock(spec=Session), case)

    assert detail.restoration_scope_detail == "서울특별시 강남구 테헤란로 5 2층만"


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

    changes = case_service._field_changes(MagicMock(spec=Session), CASE_ID, 11)

    assert changes[0].new_value == "PARTIAL"


def test_more_hidden_spots_than_the_input_had_are_left_as_they_are():
    # 어느 주소와 짝인지 알 수 없다. 틀린 주소를 보여주는 것은 [주소]를 보여주는 것보다 나쁘다.
    value = "[주소]와 [주소]"

    assert restore_hidden_text(value, "마포구 월드컵북로 12에서 장사했습니다") == value


def test_two_hidden_spots_are_paired_in_the_order_they_appeared():
    restored = restore_hidden_text(
        "[주소]에서 [주소]로 옮겼어요", "마포구 월드컵북로 12에서 강남구 테헤란로 5로 옮겼어요"
    )

    assert restored == "월드컵북로 12에서 테헤란로 5로 옮겼어요"


def test_an_unknown_submission_leaves_the_value_hidden(monkeypatch):
    # 어느 입력에서 나온 값인지 모르면 되돌릴 짝도 없다. 가린 채로 두는 쪽이 안전하다.
    monkeypatch.setattr(case_history_crud, "get_case_histories_by_case_id", lambda *_: histories())
    restorer = HiddenTextRestorer(MagicMock(spec=Session), CASE_ID)

    assert restorer.restore("마포구 [주소] 전체", None) == "마포구 [주소] 전체"
    assert restorer.restore("마포구 [주소] 전체", 999) == "마포구 [주소] 전체"
