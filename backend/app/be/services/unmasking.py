"""과거 가림 값의 출처를 확인한다. 화면 응답은 이 복원 함수를 사용하지 않는다.

기존 고정 표식에 유일하게 대응하는 원문이 증명될 때만 내부 번호 호환에 사용한다.
DB 값이나 화면 응답을 원문으로 되돌리지는 않는다.
"""

from collections.abc import Iterable

from sqlmodel import Session

from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.crud import conflict_reference as conflict_reference_crud
from app.be.services.redaction import (
    fixed_placeholders,
    hidden_originals,
    numbered_placeholders,
)


class HiddenTextRestorer:
    """한 Case 안에서, 값을 만든 입력을 찾아 가림 문구를 되돌려 주는 호출기.

    입력 원문과 "어느 입력이 어느 값을 만들었는지"를 한 번에 읽어 둔다. 값마다 다시 읽으면
    화면 하나 그리는 데 질의가 값 개수만큼 늘어난다.
    """

    def __init__(self, session: Session, case_id: int) -> None:
        self._raw_input_by_history_id = {
            history.id: history.raw_input
            for history in case_history_crud.get_case_histories_by_case_id(session, case_id)
        }
        self._before_by_row_id: dict[int, int | None] = {}
        self._current_by_field: dict[str, int | None] = {}
        # 오래된 것부터 읽어 덮어쓰므로 마지막에 남는 것이 지금 Case에 있는 값이다.
        for row in case_field_history_crud.get_case_field_histories_by_case_id(session, case_id):
            self._before_by_row_id[row.id] = self._current_by_field.get(row.canonical_field)
            self._current_by_field[row.canonical_field] = row.case_history_id
        # 충돌 결정 이력에는 사장님이 쓴 글이 없다 — 버튼을 누른 것이라 raw_input이 NULL이다
        # (services/case.py의 submit_case_conflicts_decision). 그 결정이 바꾼 값은 충돌에 담겨
        # 있던 값이고, 충돌 줄에 어느 제출에서 나왔는지가 남아 있다. 그래서 값을 만든 이력에
        # 글이 없으면 그 결정이 닫은 충돌을 따라 제출의 원문을 찾는다.
        #
        # 칸 이름으로 찾지 않는다. 같은 칸을 두 번 결정하면 어느 결정이 지금 보는 값을 만들었는지
        # 가릴 수 없어서 다른 제출의 주소가 들어갔다(승준님 #158 리뷰). 결정 이력에서 출발하면
        # 그 결정이 닫은 충돌만 보므로 섞이지 않고, 충돌이 아니었던 칸도 같은 길로 되돌아온다
        # (현석님 #161 리뷰) — 그 값도 출처가 같은 결정 이력이기 때문이다.
        origins: dict[int, set[int]] = {}
        for conflict in conflict_reference_crud.get_decided_conflicts_by_case_id(session, case_id):
            if conflict.resolved_by_case_history_id is None:
                continue
            origins.setdefault(conflict.resolved_by_case_history_id, set()).add(
                conflict.case_history_id
            )
        # 확인을 기다리는 충돌이 있는 동안은 새 제출이 막히므로(submit_case_results의 409) 한
        # 결정이 닫는 충돌은 모두 같은 제출에서 나온다. 그래도 둘 이상이면 되돌리지 않는다 —
        # 틀린 주소를 보여주는 것은 [주소]를 보여주는 것보다 나쁘다(restore_hidden_text 설명).
        self._submission_by_decision = {
            decision: next(iter(submissions))
            for decision, submissions in origins.items()
            if len(submissions) == 1
        }

    def restore(self, value: str | None, case_history_id: int | None) -> str | None:
        """`case_history_id`는 이 값을 만든 입력. 모르면 되돌리지 않고 그대로 둔다.

        그 입력이 충돌 결정이면 글이 없으므로, 그 결정이 닫은 충돌을 따라 제출의 원문을 찾는다.
        """

        if value is None or "[" not in value or case_history_id is None:
            return value
        raw_input = self._raw_input_by_history_id.get(case_history_id)
        if raw_input is None:
            origin = self._submission_by_decision.get(case_history_id)
            raw_input = self._raw_input_by_history_id.get(origin) if origin is not None else None
        if raw_input is None:
            return value
        return restore_hidden_text(value, raw_input)

    def source_of_previous(self, row_id: int) -> int | None:
        """변경 이력 한 줄의 "그 전 값"을 만든 입력."""

        return self._before_by_row_id.get(row_id)

    def source_of_current(self, canonical_field: str) -> int | None:
        """지금 Case에 들어 있는 값을 만든 입력."""

        return self._current_by_field.get(canonical_field)


class _NothingToRestore:
    """가림 문구가 없는 화면에서 쓰는, 아무것도 하지 않는 되돌리개.

    "되돌릴 게 있으면 이렇게, 없으면 저렇게"를 호출부에 두면 응답을 만드는 코드가 두 벌이
    된다. 나중에 응답에 칸이 하나 늘 때 한 쪽을 빠뜨리면, 되돌릴 때만 값이 비는 버그가 난다.
    """

    def restore(self, value: str | None, case_history_id: int | None) -> str | None:
        return value

    def source_of_previous(self, row_id: int) -> int | None:
        return None

    def source_of_current(self, canonical_field: str) -> int | None:
        return None


def build_restorer(
    session: Session, case_id: int, values: Iterable[str | None]
) -> HiddenTextRestorer | _NothingToRestore:
    """화면에 낼 값들을 먼저 보고, 되돌릴 게 있을 때만 입력 원문을 읽어 온다.

    가림 문구는 항상 대괄호로 시작한다. 대부분의 화면은 여기서 끝나 질의가 늘지 않는다.
    """

    if any(value is not None and "[" in value for value in values):
        return HiddenTextRestorer(session, case_id)
    return _NothingToRestore()


def restore_hidden_text(value: str, raw_input: str) -> str:
    """값 안의 가림 문구를, 그 입력에서 가렸던 원래 글자로 바꾼다.

    한 종류를 여러 번 가렸는데 **가린 글자가 서로 다르면 그 종류는 손대지 않는다.** 값에
    남은 가림 문구가 그중 어느 것인지 알 방법이 없기 때문이다.

    나온 순서로 짝지어 보려 했지만 두 가지가 어긋났다(#109 리뷰). AI가 주소 둘 중 **뒤엣것만**
    값에 담으면 앞엣것이 들어가고, 둘 다 담되 **순서를 바꿔** 쓰면 서로 뒤바뀐다. AI가 값에
    쓰는 말은 원문 순서를 지킬 의무가 없어서, 개수를 맞춰 보는 것으로도 막히지 않는다.

    틀린 주소를 보여주는 것은 [주소]를 보여주는 것보다 나쁘다.
    """

    originals: dict[str, list[str]] = {}
    for placeholder, original in hidden_originals(raw_input):
        originals.setdefault(placeholder, []).append(original)

    restored = value
    for placeholder, texts in originals.items():
        if len(set(texts)) == 1:
            restored = restored.replace(placeholder, texts[0])
    return restored


def build_case_placeholders(session: Session, case_id: int) -> tuple[dict[tuple[str, str], str], bool]:
    """보존된 입력으로 번호를 재구성하고, 출처가 불명확한 과거 표식이 있는지도 돌려준다."""

    histories = sorted(case_history_crud.get_case_histories_by_case_id(session, case_id), key=lambda h: h.id)
    rows = case_field_history_crud.get_case_field_histories_by_case_id(session, case_id)
    legacy = [(row, fixed_placeholders(row.after_value or "")) for row in rows]
    originals: dict[str, set[str]] = {}
    unclear: set[str] = set()
    if any(placeholders for _, placeholders in legacy):
        restorer = HiddenTextRestorer(session, case_id)
        for row, placeholders in legacy:
            for placeholder in placeholders:
                original = restorer.restore(placeholder, row.case_history_id)
                if original == placeholder:
                    unclear.add(placeholder)
                else:
                    originals.setdefault(placeholder, set()).add(original)
    aliases = {}
    for placeholder, values in originals.items():
        if len(values) == 1 and placeholder not in unclear:
            aliases[(placeholder, next(iter(values)))] = placeholder
        else:
            unclear.add(placeholder)
    return numbered_placeholders((h.raw_input for h in histories), aliases=aliases), bool(unclear)


__all__ = ["HiddenTextRestorer", "build_case_placeholders", "build_restorer", "restore_hidden_text"]
