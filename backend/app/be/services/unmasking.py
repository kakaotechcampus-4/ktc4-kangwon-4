"""화면에 돌려줄 때만 가림 문구를 원래 글자로 되돌린다.

AI는 가린 글을 보고 판단하므로, 자유 글 칸에 들어가는 값에 가림 문구가 그대로 섞여
나온다(실측: restoration_scope_detail = "서울특별시 마포구 [주소] 전체"). 그 값을
그대로 보여주면 사장님은 자기가 쓴 주소 대신 [주소]를 보게 된다.

**저장은 가린 채로 둔다.** 되돌려 저장하면 다음 판단 때 그 Case 값이 사실로 다시 AI에
넘어가면서(case_snapshot._build_fact) 이번에 가린 개인정보가 그대로 나간다. 또 같은 주소를
다시 말했을 때 한쪽만 되돌아 있으면 같은 주소가 다른 값으로 보여 충돌로 잡힌다.
"""

from collections.abc import Iterable

from sqlmodel import Session

from app.be.crud import case_field_history as case_field_history_crud
from app.be.crud import case_history as case_history_crud
from app.be.services.redaction import hidden_originals


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

    def restore(self, value: str | None, case_history_id: int | None) -> str | None:
        """`case_history_id`는 이 값을 만든 입력. 모르면 되돌리지 않고 그대로 둔다."""

        if value is None or "[" not in value or case_history_id is None:
            return value
        raw_input = self._raw_input_by_history_id.get(case_history_id)
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


__all__ = ["HiddenTextRestorer", "build_restorer", "restore_hidden_text"]
