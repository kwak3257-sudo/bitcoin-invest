"""텔레그램 알림. .env에 TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID가 있을 때만 보낸다.

알림이 실패해도 매매는 멈추지 않는다.
"""

from __future__ import annotations

import logging

import httpx

from . import config

log = logging.getLogger("notify")


def enabled() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


async def send(text: str) -> None:
    if not enabled():
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text})
            r.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("텔레그램 알림 실패: %s", exc)
