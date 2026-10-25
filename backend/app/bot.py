"""텔레그램 봇 명령. 휴대폰에서 /상태 로 성적을 보고, /정지 로 긴급 정지한다.

.env의 TELEGRAM_CHAT_ID(내 텔레그램)에서 온 메시지에만 답한다. 다른 사람이 봇을 찾아 말을 걸어도 무시한다.
돈을 더 쓰게 하는 명령은 두지 않는다. 정지는 위험을 줄이는 쪽이라 인증번호 없이 받는다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal

import httpx

from . import config, notify
from .exchanges.base import ExchangeError
from .store import TraderStore
from .strategies.dca import KST
from .strategies.trader import TraderState, position_value, today_pnl

log = logging.getLogger("bot")

HELP = "명령어\n/상태 - 수익률과 보유 현황\n/정지 - 단기 매매 긴급 정지 (보유 코인을 팔고 멈춤)"


def _krw(v: Decimal) -> str:
    return f"{v:+,.0f}원" if v else "0원"


def status_text(state: TraderState, price: Decimal | None, now: datetime) -> str:
    cfg = state.config
    mode = "실거래" if cfg.mode == "live" else "모의투자"
    run = "켜짐" if cfg.enabled else "꺼짐"
    if state.halted_until is not None and now < state.halted_until:
        run = f"쉬는 중 ({state.halt_reason})"
    lines = [f"📊 단기 매매 · {mode} · {run}", f"{cfg.market} 현재가 {price:,.0f}원" if price else "현재가를 못 받았어요"]
    if price is not None:
        equity = state.cash_krw + position_value(state, price)
        lines.append(f"운용 자산 {equity:,.0f}원 (시작 {cfg.budget_krw:,.0f}원)")
        lines.append(f"전체 수익 {_krw(equity - cfg.budget_krw)} ({(equity / cfg.budget_krw - 1) * 100:+.2f}%)")
        lines.append(f"오늘 손익 {_krw(today_pnl(state, price, now))}")
    if state.position is not None:
        p = state.position
        change = f" ({(price / p.entry_price - 1) * 100:+.2f}%)" if price else ""
        lines.append(f"보유 중: {p.entry_price:,.0f}원에 매수{change}")
    else:
        lines.append("보유 중인 코인 없음 (매수 신호를 기다리는 중)")
    sells = [t for t in state.trades if t.ok and t.pnl_krw is not None]
    if sells:
        wins = sum(1 for t in sells if t.pnl_krw > 0)
        lines.append(f"거래 {len(sells)}번, 이긴 거래 {wins}번 · 수수료 {state.fees_krw:,.0f}원")
    return "\n".join(lines)


async def handle(text: str, store: TraderStore, exchange) -> str:
    cmd = text.strip().split()[0].lower() if text.strip() else ""
    if cmd in ("/상태", "상태", "/status"):
        state = store.load()
        price = None
        try:
            [ticker] = await exchange.tickers([state.config.market])
            price = ticker.price
        except ExchangeError:
            pass
        return status_text(state, price, datetime.now(KST))
    if cmd in ("/정지", "정지", "/stop"):
        with store.edit() as state:
            if not state.config.enabled and state.position is None:
                return "단기 매매는 이미 꺼져 있어요."
            state.stop_requested = True
        return "🛑 긴급 정지를 요청했어요. 보유 코인을 팔고 멈춘 뒤 다시 알려 드릴게요."
    return HELP


async def poll(store: TraderStore, exchange) -> None:
    """텔레그램에서 온 명령을 계속 받아 답한다. 엔진이 함께 실행한다."""
    if not notify.enabled():
        return
    api = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
    offset = None
    async with httpx.AsyncClient(timeout=40) as client:
        while True:
            try:
                params = {"timeout": 25, **({"offset": offset} if offset else {})}
                r = await client.get(f"{api}/getUpdates", params=params)
                r.raise_for_status()
                for u in r.json().get("result", []):
                    offset = u["update_id"] + 1
                    msg = u.get("message") or {}
                    if str(msg.get("chat", {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
                        continue  # 내 텔레그램이 아니면 답하지 않는다
                    reply = await handle(msg.get("text", ""), store, exchange)
                    await notify.send(reply)
            except httpx.HTTPStatusError as exc:
                hint = " (토큰이 바뀌었으면 connect.bat을 다시 실행하세요)" if exc.response.status_code == 401 else ""
                log.warning("텔레그램 명령 받기 실패: %s%s", exc.response.status_code, hint)
                await asyncio.sleep(60)
            except Exception as exc:  # 봇이 멈춰도 매매는 계속한다
                log.warning("텔레그램 명령 처리 실패: %s", notify.redact(str(exc)))
                await asyncio.sleep(30)
