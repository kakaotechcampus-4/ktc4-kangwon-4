class RefreshError(RuntimeError):
    """발췌 오류."""


def excerpt_between(text: str, start: str, end: str) -> str:
    for marker in (start, end):
        if not marker or marker not in text or text.find(marker) != text.rfind(marker):
            raise RefreshError("표식 누락·중복")
    left, right = text.index(start), text.index(end)
    if right < left + len(start) or right + len(end) - left > 6000:
        raise RefreshError("발췌 범위 오류")
    return text[left : right + len(end)]
