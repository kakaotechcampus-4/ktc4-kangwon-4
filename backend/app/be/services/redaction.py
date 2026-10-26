"""사장님이 쓴 글에서 개인정보를 지우고, 무엇을 어디서 지웠는지 함께 돌려준다.

AI 입구(app/agent/guardrails.py)는 주민등록번호·사업자등록번호·휴대폰번호·토큰이 보이면
판단을 거절한다. 그래서 여기서 가리는 범위를 그 검사보다 넓게 잡는다 — 하이픈을 안 쓴
형태까지 포함한다. 그러면 "사장님이 쓴 글 때문에 판단이 거절되는" 길이 닫힌다.

종류와 가림 문구는 AI팀 2026-10-26 답변을 따른다. 새 종류를 만들지 않고, 무엇을 가렸는지는
가림 문구로 구분한다. 위치(start_offset/end_offset)는 가린 뒤 글에서 가림 문구가 차지하는
자리이고 끝자리는 포함하지 않는다.

사람 이름은 가리지 않는다. 전화번호·이메일과 달리 "김철수"는 다른 두세 글자 말과 모양이
같아서 규칙으로 찾을 수 없다. 넣으려면 찾아주는 모델이 따로 필요하다.
"""

import re

from app.agent.schemas import Redaction, RedactionType

# 주소에서 남길 부분과 가릴 부분. 시·도와 시·군·구까지만 남긴다(AI팀 답변).
# 관할 구청이 어디인지가 폐업 절차를 가르기 때문에 통째로 지우면 안내가 틀어진다.
_SIDO = r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)(?:특별자치시|특별자치도|특별시|광역시|도)?"
_SIGUNGU = r"[가-힣]{1,5}(?:시|군|구)(?![가-힣])"
# 읍·면·동·리, 도로명, 번지·호·층처럼 "그 아래 단위"로 보이는 토막.
# 끝에 한글이 더 붙으면(예: 철거동의서) 주소가 아니므로 뺀다.
_ADDRESS_PART = r"(?:[가-힣A-Za-z0-9]+(?:읍|면|동|리|로|길)(?![가-힣])|\d+(?:-\d+)?(?:번지|호|층|동)?)"

_RULES: tuple[tuple[RedactionType, str, re.Pattern[str]], ...] = (
    # 긴 것부터 본다. 주민등록번호 앞 6자리를 전화번호로 먼저 집어가면 안 된다.
    (
        RedactionType.NATIONAL_ID,
        "[주민등록번호]",
        re.compile(r"(?<!\d)\d{6}\s*[- ]\s*[1-4]\d{6}(?!\d)|(?<!\d)\d{6}[1-4]\d{6}(?!\d)"),
    ),
    (
        RedactionType.OTHER,
        "[전화번호]",
        re.compile(r"(?<!\d)01[016789][-. ]?\d{3,4}[-. ]?\d{4}(?!\d)"),
    ),
    (
        RedactionType.OTHER,
        "[사업자등록번호]",
        re.compile(r"(?<!\d)\d{3}\s*-\s*\d{2}\s*-\s*\d{5}(?!\d)|(?<!\d)\d{10}(?!\d)"),
    ),
    (
        RedactionType.OTHER,
        "[이메일]",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ),
    (
        RedactionType.TOKEN,
        "[토큰]",
        re.compile(r"(?i)\b(?:bearer\s+[a-z0-9._~+/=-]{12,}|(?:sk|pk)-[a-z0-9_-]{12,})"),
    ),
)

# 시·도나 시·군·구 **다음에 오는** 상세 주소만 잡는다. 뒤에 상세 주소가 붙지 않으면
# 그냥 지역을 말한 것이라 가릴 게 없다.
_ADDRESS = re.compile(
    rf"(?:{_SIDO}\s*(?:{_SIGUNGU})?|{_SIGUNGU})\s*(?P<detail>{_ADDRESS_PART}(?:\s+{_ADDRESS_PART})*)"
)


def redact(text: str) -> tuple[str, list[Redaction]]:
    """가린 글과, 가린 자리 목록을 함께 돌려준다.

    목록의 위치는 **가린 뒤** 글 기준이다. AI 쪽 계약이 가림 문구와 그 자리 글자가
    똑같은지 검사하기 때문에(schemas.RedactedInput), 원문 기준으로 주면 거절당한다.
    """

    spans = _find_spans(text)

    masked_parts: list[str] = []
    redactions: list[Redaction] = []
    cursor = 0
    length = 0
    for start, end, redaction_type, placeholder in spans:
        kept = text[cursor:start]
        masked_parts.append(kept)
        length += len(kept)
        masked_parts.append(placeholder)
        redactions.append(
            Redaction(
                type=redaction_type,
                placeholder=placeholder,
                start_offset=length,
                end_offset=length + len(placeholder),
            )
        )
        length += len(placeholder)
        cursor = end
    masked_parts.append(text[cursor:])

    return "".join(masked_parts), redactions


def _find_spans(text: str) -> list[tuple[int, int, RedactionType, str]]:
    """가릴 자리를 원문 기준으로 모아, 겹치는 것을 걸러 앞에서부터 정렬해 돌려준다."""

    found: list[tuple[int, int, RedactionType, str]] = []
    for redaction_type, placeholder, pattern in _RULES:
        for match in pattern.finditer(text):
            found.append((match.start(), match.end(), redaction_type, placeholder))
    spans = _without_overlaps(found)
    # 주소는 마지막에 맞춘다. 주소 뒤에 번호가 바로 붙으면("… 12 010-1234-5678") 번호
    # 앞자리가 주소의 일부로 먼저 잡혀서, 번호가 반만 가려진 채 남는다. 번호 쪽이
    # 무엇인지 더 분명하므로 그쪽을 살리고 주소는 그 앞까지만 가린다.
    for match in _ADDRESS.finditer(text):
        start, end = match.span("detail")
        for taken_start, taken_end, _, _ in spans:
            if taken_start < end and start < taken_end:
                end = min(end, taken_start)
        end = len(text[start:end].rstrip()) + start
        if end > start:
            spans.append((start, end, RedactionType.ADDRESS, "[주소]"))
    return _without_overlaps(spans)


def _without_overlaps(
    spans: list[tuple[int, int, RedactionType, str]],
) -> list[tuple[int, int, RedactionType, str]]:
    """앞에서부터, 같은 자리면 긴 쪽을 남긴다.

    계약이 겹친 자리를 거절하고(schemas.RedactedInput), 한 번 가린 글자를 또 가릴 일도 없다.
    """

    kept: list[tuple[int, int, RedactionType, str]] = []
    previous_end = 0
    for span in sorted(spans, key=lambda item: (item[0], -item[1])):
        if span[0] < previous_end:
            continue
        kept.append(span)
        previous_end = span[1]
    return kept


__all__ = ["redact"]
