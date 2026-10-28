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
# 상세 주소는 **반드시 읍·면·동·리나 "도로명 + 건물번호"에서 시작한다**. 숫자만 보고
# 주소로 치면 "마포구 2명 있습니다"의 직원 수까지 지워진다(승준님 #109 리뷰).
#
# 앞에 두 글자 이상을 요구하는 것은 조사 때문이다. "가면"은 면으로 끝나지만 동네 이름이
# 아니고, 실제 읍·면·동·리 이름은 그 앞이 두 글자 이상이다.
_DONG = r"[가-힣A-Za-z0-9]{2,}(?:읍|면|동|리)(?![가-힣])"
# 도로명은 건물번호가 뒤따를 때만 주소로 본다. "고용센터로 가면"의 "로"는 조사라서,
# 번호를 요구하지 않으면 기관 이름이 주소로 가려진다(승준님 #109 리뷰).
# 번호에는 조사가 붙을 수 있다("12에서"). 도로명 뒤라는 자리가 이미 번호임을 말해 준다.
_ROAD = r"[가-힣A-Za-z0-9]{2,}(?:로|길)\s*\d+(?:-\d+)?"
# 번지·호·층은 단위가 붙어 있어 그 자체로 주소의 일부로 읽힌다.
_NUMBERED = r"\d+(?:-\d+)?(?:번지|호|층)"
# 주소 안에서 이어지는 번호. 뒤에 글자가 붙으면(2명, 3월) 주소가 아니다.
_BARE_NUMBER = r"\d+(?:-\d+)?(?![\d가-힣])"
_PLACE = rf"(?:{_ROAD}|{_DONG})"

# 흔한 성씨. 이름을 찾을 때 "성씨로 시작하는가"만 본다. 여기 없는 성씨는 못 찾는다.
_SURNAME = (
    r"(?:남궁|황보|제갈|독고|선우|서문|김|이|박|최|정|강|조|윤|장|임|오|한|신|서|권|황|안|송|"
    r"류|유|홍|전|고|문|손|양|배|백|허|남|심|노|하|곽|성|차|주|우|구|민|진|지|엄|채|원|천|방|"
    r"공|현|함|변|염|여|추|도|소|석|선|설|마|길|연|위|표|명|기|반|왕|금|옥|육|인|맹|제|모|탁)"
)

# 이름 뒤에 올 수 있는 말. 이름이 어디서 끝나는지 정하는 데만 쓴다.
_AFTER_NAME = r"(?:\s|$|[,.·!?]|입니다|이고|이에요|예요|라고|씨|님|은|는|이|가|를|과|와|도)"

_RULES: tuple[tuple[RedactionType, str, re.Pattern[str]], ...] = (
    # 위에 있을수록 먼저 가져간다. 모양이 겹치는 번호들이 있어서(사업자등록번호와 계좌번호,
    # 전화번호와 계좌번호) 무엇으로 볼지 여기 순서로 정한다.
    (
        RedactionType.NATIONAL_ID,
        "[주민등록번호]",
        # 하이픈이 있으면 뒷자리를 따지지 않는다. AI 입구 검사가 그렇게 보기 때문에,
        # 여기서 좁히면 900101-5234567 같은 글이 안 가려진 채 거절당한다(승준님 #109 리뷰).
        # 하이픈이 없을 때만 일곱 번째 자리로 가려, 긴 숫자를 주민번호로 오인하지 않는다.
        re.compile(r"(?<!\d)\d{6}\s*[- ]\s*\d{7}(?!\d)|(?<!\d)\d{6}[1-4]\d{6}(?!\d)"),
    ),
    (
        RedactionType.OTHER,
        "[전화번호]",
        re.compile(r"(?<!\d)01[016789][-. ]?\d{3,4}[-. ]?\d{4}(?!\d)|(?<!\d)0\d{1,2}-\d{3,4}-\d{4}(?!\d)"),
    ),
    (
        RedactionType.OTHER,
        "[사업자등록번호]",
        re.compile(r"(?<!\d)\d{3}\s*-\s*\d{2}\s*-\s*\d{5}(?!\d)|(?<!\d)\d{10}(?!\d)"),
    ),
    (
        RedactionType.ACCOUNT,
        "[계좌번호]",
        # 끝자리를 네 자리 이상으로 묶어 2026-10-26 같은 날짜를 계좌로 보지 않게 한다.
        re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{4,8}(?!\d)"),
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
    (
        RedactionType.OTHER,
        "[이름]",
        # 밝히고 쓴 이름. "이름은" 자체는 남겨야 AI가 무슨 말인지 안다.
        # 뒤에 올 수 있는 말을 정해 둬서, 두 글자 이름의 다음 글자까지 가져가지 않는다
        # ("이수입니다"의 "입"까지 가리면 문장이 깨진다 — 승준님 #109 리뷰).
        re.compile(
            rf"이름은?\s*(?P<mask>{_SURNAME}[가-힣]{{1,2}})"
            rf"(?={_AFTER_NAME})"
        ),
    ),
    (
        RedactionType.OTHER,
        "[이름]",
        # 부르는 자리의 이름. 성씨로 시작할 때만 본다 — 사람 이름은 다른 말과 모양이
        # 같아서, 이 조건이 없으면 "저희 사장님"의 "저희"까지 가려진다.
        re.compile(rf"(?<![가-힣]){_SURNAME}[가-힣]{{1,2}}(?=\s?(?:씨|님))"),
    ),
    (
        RedactionType.OTHER,
        "[이름]",
        # 직함을 붙여 부르는 자리("김철수 사장님").
        re.compile(rf"(?<![가-힣]){_SURNAME}[가-힣]{{1,2}}(?=\s?(?:사장|대표|이사|부장|과장|팀장|소장|실장))"),
    ),
)

# 성씨+한두 글자로 보이지만 사람 이름이 아닌 말. 이걸 가리면 AI가 누가 한 말인지 잃는다.
_NOT_NAMES = frozenset({
    "사장", "대표", "이사", "부장", "과장", "차장", "팀장", "실장", "국장", "소장",
    "임대인", "임차인", "건물주", "집주인", "손님", "고객", "직원", "알바", "기사",
    "선생", "변호사", "세무사", "노무사", "법무사", "공무원", "담당자", "관리자",
})

# 시·도나 시·군·구 **다음에 오는** 상세 주소만 잡는다. 뒤에 상세 주소가 붙지 않으면
# 그냥 지역을 말한 것이라 가릴 게 없다. 중간에 건물명이 끼어도("월드컵북로 12 가온빌딩
# 305호") 이어서 가리도록, 모르는 토막 하나는 건너뛴다(승준님 #109 리뷰).
_DETAIL_TAIL = rf"(?:\s+(?:{_PLACE}|{_NUMBERED}|{_BARE_NUMBER})|\s+\S+\s+(?:{_PLACE}|{_NUMBERED}))*"  # noqa: E501
_ADDRESS = re.compile(
    rf"(?:{_SIDO}\s*(?:{_SIGUNGU})?|{_SIGUNGU})\s*(?P<detail>{_PLACE}{_DETAIL_TAIL})"
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
    for start, end, redaction_type, placeholder, _ in spans:
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


def _find_spans(text: str) -> list[tuple[int, int, RedactionType, str, int]]:
    """가릴 자리를 원문 기준으로 모아, 겹치는 것을 걸러 앞에서부터 정렬해 돌려준다."""

    found: list[tuple[int, int, RedactionType, str, int]] = []
    for priority, (redaction_type, placeholder, pattern) in enumerate(_RULES):
        for match in pattern.finditer(text):
            # 규칙이 "밝힌 부분"만 가리고 싶을 때는 mask 자리를 따로 표시해 둔다.
            start, end = match.span("mask" if "mask" in pattern.groupindex else 0)
            if text[start:end] in _NOT_NAMES:
                continue
            found.append((start, end, redaction_type, placeholder, priority))
    spans = _without_overlaps(found)
    # 주소는 마지막에 맞춘다. 주소 뒤에 번호가 바로 붙으면("… 12 010-1234-5678") 번호
    # 앞자리가 주소의 일부로 먼저 잡혀서, 번호가 반만 가려진 채 남는다. 번호 쪽이
    # 무엇인지 더 분명하므로 그쪽을 살리고 주소는 그 앞까지만 가린다.
    for match in _ADDRESS.finditer(text):
        start, end = match.span("detail")
        for taken_start, taken_end, *_ in spans:
            if taken_start < end and start < taken_end:
                end = min(end, taken_start)
        end = len(text[start:end].rstrip()) + start
        if end > start:
            spans.append((start, end, RedactionType.ADDRESS, "[주소]", len(_RULES)))
    return _without_overlaps(spans)


def _without_overlaps(
    spans: list[tuple[int, int, RedactionType, str, int]],
) -> list[tuple[int, int, RedactionType, str, int]]:
    """앞에서부터, 같은 자리면 긴 쪽을 남긴다.

    계약이 겹친 자리를 거절하고(schemas.RedactedInput), 한 번 가린 글자를 또 가릴 일도 없다.
    """

    kept: list[tuple[int, int, RedactionType, str, int]] = []
    previous_end = 0
    # 같은 자리를 두 규칙이 가리키면 긴 쪽, 그래도 같으면 _RULES에서 위에 있는 쪽.
    for span in sorted(spans, key=lambda item: (item[0], -item[1], item[4])):
        if span[0] < previous_end:
            continue
        kept.append(span)
        previous_end = span[1]
    return kept


def hidden_originals(text: str) -> list[tuple[str, str]]:
    """이 글에서 무엇을 가렸는지를 (가림 문구, 원래 글자) 짝으로, 나온 순서대로 돌려준다.

    화면에 돌려줄 때 되돌리는 쪽이 쓴다(services.unmasking). redact가 주는 위치는 가린 뒤
    글 기준이라 원래 글자를 못 찾는다. 같은 규칙으로 한 번 더 훑어 원문 쪽 자리를 준다.
    """

    return [(placeholder, text[start:end]) for start, end, _, placeholder, _ in _find_spans(text)]


__all__ = ["hidden_originals", "redact"]
