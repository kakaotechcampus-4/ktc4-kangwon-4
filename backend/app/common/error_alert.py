"""서버 ERROR 로그를 Discord로 알린다. 서버에 들어가 로그를 보기 전에 장애를 먼저 알기 위해서다.

보내는 것은 로그 위치·우리가 쓴 한 줄(Case·판단 번호 정도)·오류 종류 이름·서버 버전·시각뿐이다.
예외 메시지와 스택은 보내지 않는다. 거기에는 사장님 글이나 서류 값이 섞일 수 있다.
Sentry 같은 서비스는 기본으로 요청 본문과 지역 변수까지 보내서 쓰지 않았다.

웹훅 주소(DISCORD_ERROR_WEBHOOK_URL)가 없으면 아무것도 달지 않는다. 로컬·CI는 그대로다.
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

# 같은 오류가 몰려도 이 간격에 한 번만 보낸다. Discord 채널이 도배되지 않게 한다
_SAME_ALERT_SECONDS = 60
_MAX_LINE = 200
_KST = timezone(timedelta(hours=9))


class DiscordErrorHandler(logging.Handler):
    def __init__(self, webhook_url: str, environment: str):
        super().__init__(level=logging.ERROR)
        self._webhook_url = webhook_url
        self._environment = environment
        self._last_sent: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def format_alert(self, record: logging.LogRecord) -> str:
        error = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None
        line = record.getMessage()[:_MAX_LINE]
        version = os.environ.get("APP_VERSION", "unknown")
        when = datetime.fromtimestamp(record.created, _KST).strftime("%Y-%m-%d %H:%M:%S KST")
        return f"🚨 [{self._environment} {version}] {record.name}\n{line}" + (f" ({error})" if error else "") + f"\n{when}"

    def emit(self, record: logging.LogRecord) -> None:
        key = (record.name, record.msg, record.exc_info[0] if record.exc_info else None)
        now = time.monotonic()
        with self._lock:
            if now - self._last_sent.get(key, -_SAME_ALERT_SECONDS) < _SAME_ALERT_SECONDS:
                return
            self._last_sent[key] = now
        content = self.format_alert(record)
        # 요청·판단을 기다리게 하지 않는다. 보내다 실패해도 서비스에는 아무 영향이 없어야 한다
        threading.Thread(target=self._send, args=(content,), daemon=True).start()

    def _send(self, content: str) -> None:
        try:
            httpx.post(self._webhook_url, json={"content": content}, timeout=3)
        except httpx.HTTPError:
            pass


def install_error_alert(webhook_url: str | None, environment: str) -> DiscordErrorHandler | None:
    if not webhook_url:
        return None
    app_logger = logging.getLogger("app")
    # 서버가 다시 시작돼도(테스트에서 앱을 여러 번 띄워도) 알림이 두 번씩 가지 않게 한 번만 단다
    installed = next((h for h in app_logger.handlers if isinstance(h, DiscordErrorHandler)), None)
    if installed is not None:
        return installed
    handler = DiscordErrorHandler(webhook_url, environment)
    # 지금 app.* 경고는 핸들러가 없을 때만 찍히는 파이썬 기본 출력으로 나온다. 핸들러를 하나라도 달면
    # 그 출력이 꺼지므로, 같은 모양의 화면 출력을 함께 달아 docker logs가 그대로 남게 한다
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.WARNING)
    app_logger.addHandler(console)
    app_logger.addHandler(handler)
    # 처리되지 않은 예외(500)는 uvicorn이 "uvicorn.error"로 남긴다. 이 로거는 app으로 오지 않는다
    logging.getLogger("uvicorn.error").addHandler(handler)
    return handler
