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
from .strategies.short_term import analysis
from .strategies.trader import TraderState, _completed, position_value, today_pnl

log = logging.getLogger("bot")

HELP = "명령어\n/상태 - 수익률, 보유 현황, 매수 조건 분석\n/정지 - 단기 매매 긴급 정지 (보유 코인을 팔고 멈춤)"


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


def _won(v: float | None) -> str:
    return f"{v:,.0f}원" if v is not None else "계산 중"


def analysis_text(state: TraderState, bars) -> str:
    """마지막으로 끝난 봉을 보고 왜 사는지/안 사는지 설명한다."""
    p = state.config.params
    if len(bars) < p.warmup:
        return "분석에 필요한 봉이 아직 모자라요."
    closes = [float(c.close) for c in bars]
    if p.strategy == "breakout":
        last = bars[-1]
        return (f"🔎 분석 (변동성 돌파, k={p.k})\n직전 봉 고가 {last.high:,.0f}원 · 저가 {last.low:,.0f}원\n"
                f"이번 봉 시가에서 (고가-저가)×{p.k}만큼 오르면 삽니다.")
    a = analysis(closes, p)
    ok = lambda b: "✅" if b else "❌"  # noqa: E731
    lines = [
        f"🔎 분석 ({bars[-1].time_kst:%m/%d %H시} 봉 기준)",
        f"종가 {_won(a['close'])} · RSI {a['rsi']:.0f}" if a["rsi"] is not None else f"종가 {_won(a['close'])}",
        f"{ok(a['fast_above'])} {p.fast}봉 평균 {_won(a['fast'])} {'>' if a['fast_above'] else '<'} {p.slow}봉 평균 {_won(a['slow'])}",
        f"{ok(a['rsi_ok'])} RSI {p.rsi_max} 아래 (너무 오른 상태가 아님)",
    ]
    if p.trend_period:
        lines.append(f"{ok(a['trend_ok'])} 종가가 {p.trend_period}봉 평균 {_won(a['trend'])} 위 (큰 흐름 상승)")
    if a["signal"] == "buy":
        lines.append("➡️ 매수 신호")
    elif a["signal"] == "sell" and state.position is not None:
        lines.append("➡️ 매도 신호")
    elif state.position is None:
        if not a["fast_above"]:
            lines.append(f"➡️ 기다림: {p.fast}봉 평균이 {p.slow}봉 평균을 아래에서 위로 뚫는 날 삽니다.")
            if a["buy_above"]:
                gap = (a["buy_above"] / a["close"] - 1) * 100
                when = "내일" if state.config.interval == "1d" else "다음 봉"
                lines.append(f"🎯 {when} 종가가 약 {_won(a['buy_above'])} 이상이면 매수 신호 (지금보다 {gap:+.1f}%)")
                lines.append("   가격이 천천히 오르면 이 기준도 매일 내려와요.")
        else:
            lines.append("➡️ 기다림: 이미 위에 있어서, 한 번 내려갔다 다시 뚫을 때 삽니다.")
    else:
        lines.append("➡️ 보유 유지: 평균이 꺾이거나 손절·익절가에 닿으면 팝니다.")
    return "\n".join(lines)


async def analysis_report(store: TraderStore, exchange) -> str:
    state = store.load()
    cfg = state.config
    need = cfg.params.warmup + 50
    if need > 200:
        candles = await exchange.candle_history(cfg.market, cfg.interval, need)
    else:
        candles = await exchange.candles(cfg.market, cfg.interval, need)
    return analysis_text(state, _completed(candles, cfg.interval, datetime.now(KST)))


async def briefing(store: TraderStore, exchange) -> str:
    """아침 브리핑: 현황 + 분석."""
    state = store.load()
    price = None
    try:
        [ticker] = await exchange.tickers([state.config.market])
        price = ticker.price
    except ExchangeError:
        pass
    text = "☀️ 오늘의 브리핑\n" + status_text(state, price, datetime.now(KST))
    try:
        text += "\n\n" + await analysis_report(store, exchange)
    except ExchangeError:
        pass
    return text


async def handle(text: str, store: TraderStore, exchange) -> str:
    cmd = text.strip().split()[0].lower() if text.strip() else ""
    if cmd in ("/상태", "상태", "/status"):
        return (await briefing(store, exchange)).replace("☀️ 오늘의 브리핑\n", "", 1)
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
