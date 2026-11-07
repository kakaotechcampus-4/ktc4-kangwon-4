"""통합 폐업 신고 정보(폐업일·사유·주소)와 보증금 반환 결과를 저장하고 Case 조회에 다시 내려주는지.

준비물은 case_world.py. 요청 검사(필수·형식)는 요청 스키마만 보면 되어 DB 없이 돈다.
"""

from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session

from app.be.schemas.case import CaseClosureReportRequest
from app.be.services.case import get_case, update_case_closure_report, update_case_deposit_return

from case_world import case_engine, case_world  # noqa: F401 — 픽스처

REPORT = dict(
    closure_date=date(2026, 10, 31), closure_reason="BUSINESS_SLUMP",
    road_address="서울 마포구 망원로 52 (망원동)", address_detail="1층",
)


def detail_of(engine, member_id: int):
    with Session(engine) as session:
        return get_case(session, member_id).case


def test_the_closure_report_is_saved_and_shown_again(case_engine, case_world):
    """신고 요약을 다시 열어도 같은 값이 보여야 한다."""

    member_id, _, _ = case_world.sign_up()
    with Session(case_engine) as session:
        update_case_closure_report(session, member_id, CaseClosureReportRequest(**REPORT))

    case = detail_of(case_engine, member_id)

    assert (case.closure_date, case.closure_reason, case.road_address, case.address_detail) == (
        date(2026, 10, 31), "BUSINESS_SLUMP", "서울 마포구 망원로 52 (망원동)", "1층",
    )


def test_sending_the_report_again_overwrites_it(case_engine, case_world):
    member_id, _, _ = case_world.sign_up()
    with Session(case_engine) as session:
        update_case_closure_report(session, member_id, CaseClosureReportRequest(**REPORT))
        update_case_closure_report(session, member_id, CaseClosureReportRequest(
            **{**REPORT, "closure_reason": "PERSONAL", "address_detail": None},
        ))

    case = detail_of(case_engine, member_id)

    assert (case.closure_reason, case.address_detail) == ("PERSONAL", None)


def test_the_planned_date_from_sign_up_is_left_alone(case_engine, case_world):
    """가입 때 받은 예상일은 AI 판단에 쓰는 값이라, 신고할 실제 폐업일로 덮지 않는다."""

    member_id, case_id, _ = case_world.sign_up()
    with Session(case_engine) as session:
        update_case_closure_report(session, member_id, CaseClosureReportRequest(**REPORT))

    assert detail_of(case_engine, member_id).planned_closure_date is None


@pytest.mark.parametrize("result", ["FULL", "PARTIAL", "NONE"])
def test_the_deposit_return_result_is_saved(case_engine, case_world, result):
    member_id, _, _ = case_world.sign_up()
    with Session(case_engine) as session:
        update_case_deposit_return(session, member_id, result)

    assert detail_of(case_engine, member_id).deposit_return_result == result


def test_nothing_is_filled_before_the_owner_reports(case_engine, case_world):
    member_id, _, _ = case_world.sign_up()

    case = detail_of(case_engine, member_id)

    assert (case.closure_date, case.closure_reason, case.road_address, case.deposit_return_result) == (
        None, None, None, None,
    )


def test_someone_without_a_case_gets_404(case_engine, case_world):
    stranger = case_world.stranger()
    with Session(case_engine) as session:
        for call in (
            lambda: update_case_closure_report(session, stranger, CaseClosureReportRequest(**REPORT)),
            lambda: update_case_deposit_return(session, stranger, "FULL"),
        ):
            with pytest.raises(HTTPException) as error:
                call()
            assert error.value.status_code == 404


@pytest.mark.parametrize("broken", [
    {"closure_reason": "BANKRUPT"},   # 시안 보기 셋이 아닌 값
    {"road_address": ""},              # 주소 찾기를 안 하고 넘긴 경우
    {"closure_date": None},
])
def test_a_report_missing_what_the_screen_requires_is_rejected(broken):
    with pytest.raises(ValidationError):
        CaseClosureReportRequest(**{**REPORT, **broken})
