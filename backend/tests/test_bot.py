from datetime import datetime
from decimal import Decimal

from app import bot
from app.store import TraderStore
from app.strategies.dca import KST
from app.strategies.trader import OpenPosition, TraderConfig

from .test_trader import FakeExchange

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=KST)


def test_status_text_shows_return_and_position(tmp_path):
    store = TraderStore(tmp_path / "trader.json")
    with store.edit() as s:
        s.config = TraderConfig(enabled=True, mode="live")
        s.position = OpenPosition(entry_at=NOW, entry_price=Decimal(100), volume=Decimal(1000), cost_krw=Decimal(100250))
    text = bot.status_text(store.load(), Decimal(110), NOW)
    assert "실거래 · 켜짐" in text and "(+10.00%)" in text and "보유 중" in text


async def test_stop_command_requests_emergency_stop(tmp_path):
    store = TraderStore(tmp_path / "trader.json")
    with store.edit() as s:
        s.config = TraderConfig(enabled=True)
    reply = await bot.handle("/정지", store, FakeExchange())
    assert "긴급 정지" in reply and store.load().stop_requested
    assert "상태" in await bot.handle("hi", store, FakeExchange())
    assert "단기 매매" in await bot.handle("/상태", store, FakeExchange())


def test_analysis_explains_waiting_for_cross(tmp_path):
    from app.strategies.short_term import ShortTermParams

    from .test_trader import bars

    store = TraderStore(tmp_path / "trader.json")
    with store.edit() as s:
        s.config = TraderConfig(enabled=True, params=ShortTermParams(fast=2, slow=3, rsi_period=2, rsi_max=100,
                                                                     trend_period=3))
    text = bot.analysis_text(store.load(), bars((100, 100, 100, 110, 80)))
    assert "🔎 분석" in text and "❌ 2봉 평균" in text and "기다림" in text
    golden = bot.analysis_text(store.load(), bars((100, 100, 100, 90, 120)))
    assert "매수 신호" in golden


def test_buy_price_makes_the_next_bar_a_golden_cross():
    from app.strategies.short_term import ShortTermParams, buy_price, signals

    p = ShortTermParams(fast=2, slow=3, rsi_period=2, rsi_max=100, trend_period=3)
    closes = [100.0, 100, 100, 110, 80]
    x = buy_price(closes, p)
    assert signals(closes + [x + 1], p)[-1] == "buy"
    assert signals(closes + [x - 1], p)[-1] != "buy"
