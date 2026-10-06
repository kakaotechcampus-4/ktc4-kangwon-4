import pytest

from scripts.refresh_procedures import RefreshError, excerpt_between


def test_excerpt():
    assert excerpt_between("앞 시작 내용 끝 뒤", "시작", "끝") == "시작 내용 끝"


@pytest.mark.parametrize("text,start,end", [
    ("시작 뿐", "시작", "끝"),
    ("시작 시작 끝", "시작", "끝"),
    ("끝 시작", "시작", "끝"),
    ("시작" + "가" * 6000 + "끝", "시작", "끝"),
    ("가가가 끝", "가가", "끝"),
    ("신고 절차 끝", "절차", "신고 절차"),
])
def test_invalid_range(text, start, end):
    with pytest.raises(RefreshError):
        excerpt_between(text, start, end)
