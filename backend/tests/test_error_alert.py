"""서버 ERROR 로그를 Discord로 알릴 때, 개인정보를 빼고 몰린 오류는 한 번만 보내는지.

실제 Discord는 부르지 않는다.
"""

import logging

import pytest

from app.common import error_alert
from app.common.error_alert import DiscordErrorHandler, install_error_alert


@pytest.fixture
def clean_loggers():
    """설치한 핸들러가 다른 테스트로 새지 않게 원래대로 돌려놓는다."""
    loggers = [logging.getLogger("app"), logging.getLogger("uvicorn.error")]
    before = [list(logger.handlers) for logger in loggers]
    yield
    for logger, handlers in zip(loggers, before):
        logger.handlers = handlers


@pytest.fixture
def sent(monkeypatch):
    """보내는 대신 내용만 모은다. 스레드도 바로 실행해 결과를 곧장 본다."""
    contents = []
    monkeypatch.setattr(DiscordErrorHandler, "_send", lambda self, content: contents.append(content))

    class RunNow:
        def __init__(self, target, args, daemon):
            self._run = lambda: target(*args)

        def start(self):
            self._run()

    monkeypatch.setattr(error_alert.threading, "Thread", RunNow)
    return contents


def _error_record(message, *args, error=None):
    exc_info = None
    if error is not None:
        try:
            raise error
        except type(error):
            import sys
            exc_info = sys.exc_info()
    return logging.LogRecord("app.be.services.judgment", logging.ERROR, __file__, 1, message, args, exc_info)


def test_without_webhook_nothing_is_installed(clean_loggers):
    handlers = list(logging.getLogger("app").handlers)

    assert install_error_alert(None, "prod") is None
    assert install_error_alert("", "prod") is None
    assert logging.getLogger("app").handlers == handlers


def test_alert_keeps_our_line_and_error_name_but_not_the_error_message(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "6b9b810")
    handler = DiscordErrorHandler("https://discord.invalid/webhook", "prod")

    # 예외 메시지에는 사장님 글이 섞일 수 있다. 오류 종류 이름만 보낸다
    content = handler.format_alert(_error_record("case_history %s 판단 실패", 85, error=ValueError("사장님이 쓴 글")))

    assert "case_history 85 판단 실패 (ValueError)" in content
    assert "[prod 6b9b810] app.be.services.judgment" in content
    assert "사장님이 쓴 글" not in content


def test_same_error_is_sent_once_a_minute(sent):
    handler = DiscordErrorHandler("https://discord.invalid/webhook", "prod")

    handler.emit(_error_record("case_history %s 판단 실패", 85, error=ValueError()))
    handler.emit(_error_record("case_history %s 판단 실패", 86, error=ValueError()))
    handler.emit(_error_record("서류 처리 실패", error=ValueError()))

    # 같은 자리의 같은 오류는 판단 번호가 달라도 한 번만, 다른 자리 오류는 따로 보낸다
    assert len(sent) == 2


def test_installing_keeps_warnings_in_the_server_log_and_alerts_errors_once(clean_loggers, sent, capsys):
    handler = install_error_alert("https://discord.invalid/webhook", "prod")
    # 다시 시작해도 두 번 달리지 않는다
    assert install_error_alert("https://discord.invalid/webhook", "prod") is handler

    logging.getLogger("app.be.services.auth").warning("카카오 토큰 요청 거절: %s", 400)
    logging.getLogger("app.be.services.judgment").error("case_history %s 판단 실패", 85)

    # 핸들러를 달면 파이썬 기본 출력이 꺼진다. 경고도 오류도 그대로 서버 로그에 남아야 한다
    stderr = capsys.readouterr().err
    assert "카카오 토큰 요청 거절: 400" in stderr
    assert "case_history 85 판단 실패" in stderr
    # Discord에는 ERROR만 간다
    assert len(sent) == 1 and "case_history 85 판단 실패" in sent[0]
