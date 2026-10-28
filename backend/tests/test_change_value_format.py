"""바뀐 값·충돌 값을 어떤 글자로 적어 내보내는지. DB 연결 없이 crud만 바꿔 끼운다.

화면이 이 글자를 보고 문구를 고른다(#110의 adapters/results.ts). 여기 형식이 바뀌면 BE는
아무 데도 안 터지고 화면에만 "확인 필요"가 뜬다. 그래서 형식을 여기에 못 박아 둔다.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session

from app.agent.schemas import CaseFieldKey, FactOperation, FactValueType
from app.be.crud import case as case_crud
from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import evidence as evidence_crud
from app.be.services import decision_record


def fact_change(field: CaseFieldKey, value_type: FactValueType, proposed):
    return SimpleNamespace(
        field_path=field, value_type=value_type, operation=FactOperation.SET,
        proposed_value=proposed, source_evidence_refs=["ev_1"],
        source_type=SimpleNamespace(value="INFO_ANALYSIS"), reason_summary="합성",
    )


@pytest.fixture
def saved_change(monkeypatch):
    """바뀐 값 하나를 저장하고, 이력에 적힌 글자를 돌려주는 호출기."""

    def save(field: CaseFieldKey, value_type: FactValueType, proposed, stored=None):
        case = SimpleNamespace(id=1, **{field.value: stored})
        rows: list = []
        monkeypatch.setattr(case_crud, "get_case_by_id", lambda *_: case)
        monkeypatch.setattr(
            case_field_history_crud, "create_case_field_history",
            lambda _session, row: rows.append(row),
        )
        decision_record._apply_fact_changes(
            MagicMock(spec=Session), SimpleNamespace(id=9, case_id=1),
            [fact_change(field, value_type, proposed)],
        )
        return rows[0]

    return save


@pytest.mark.parametrize(
    ("field", "value_type", "proposed", "expected"),
    [
        pytest.param(CaseFieldKey.FRANCHISE_STATUS, FactValueType.BOOLEAN, True, "True", id="참"),
        pytest.param(CaseFieldKey.FRANCHISE_STATUS, FactValueType.BOOLEAN, False, "False", id="거짓"),
        pytest.param(CaseFieldKey.EMPLOYEE_COUNT, FactValueType.INTEGER, 3, "3", id="숫자"),
        pytest.param(
            CaseFieldKey.PLANNED_CLOSURE_DATE, FactValueType.DATE, date(2026, 10, 4),
            "2026-10-04", id="날짜",
        ),
        pytest.param(
            CaseFieldKey.RESTORATION_SCOPE, FactValueType.ENUM, "FULL", "FULL", id="정해진 값",
        ),
    ],
)
def test_a_changed_value_is_written_the_way_the_screen_reads_it(
    saved_change, field, value_type, proposed, expected
):
    assert saved_change(field, value_type, proposed).after_value == expected


def test_an_empty_previous_value_is_left_null_not_the_word_unknown(saved_change):
    # changes의 빈 값은 null이다. 화면은 null을 "미확인"으로 읽는다.
    row = saved_change(CaseFieldKey.RESTORATION_SCOPE, FactValueType.ENUM, "FULL", stored=None)

    assert row.before_value is None


def test_an_unknown_enum_is_an_empty_previous_value_too(saved_change):
    # 세 칸은 글자 "UNKNOWN"이 미확인을 뜻한다. 그 글자를 그대로 내보내면 화면이 값으로 읽는다.
    row = saved_change(
        CaseFieldKey.RESTORATION_SCOPE, FactValueType.ENUM, "FULL", stored="UNKNOWN"
    )

    assert row.before_value is None


@pytest.fixture
def saved_conflict(monkeypatch):
    """충돌 하나를 저장하고, 보관된 값을 돌려주는 호출기."""

    def save(committed, proposed):
        saved: list = []
        monkeypatch.setattr(decision_record, "_save_evidence_records", lambda *_: None)
        monkeypatch.setattr(
            evidence_crud, "create_conflict_reference",
            lambda _session, reference: saved.append(reference),
        )
        conflict = SimpleNamespace(
            conflict_ref="cr_1", field_path=CaseFieldKey.RESTORATION_SCOPE,
            committed_value=committed, proposed_value=proposed,
            conflict_digest="sha256:" + "0" * 64,
            model_dump=lambda **_: {"conflict_ref": "cr_1"},
        )
        decision_record.save_conflict(
            MagicMock(spec=Session), SimpleNamespace(id=9, case_id=1),
            SimpleNamespace(conflicts=[conflict], evidence_records=[]),
        )
        return saved[0]

    return save


def test_a_conflict_writes_an_empty_value_as_the_word_unknown(saved_conflict):
    """충돌 값은 NULL을 못 받는 칸이라 빈 값도 글자로 적는다. 화면이 그 글자를 미확인으로 읽는다."""

    reference = saved_conflict(committed=None, proposed="FULL")

    assert reference.committed_value == "UNKNOWN"
    assert reference.proposed_value == "FULL"


def test_a_conflict_writes_other_values_the_same_way_as_changes(saved_conflict):
    reference = saved_conflict(committed=False, proposed=True)

    assert (reference.committed_value, reference.proposed_value) == ("False", "True")
