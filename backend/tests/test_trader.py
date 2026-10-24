from datetime import datetime, timedelta
from decimal import Decimal

from app.exchanges.base import Balance, Candle, ExchangeError, OrderResult, Side, Ticker
from app.strategies.dca import KST
from app.strategies.short_term import ShortTermParams
from app.strategies.trader import OpenPosition, TraderConfig, TraderState, step

PARAMS = ShortTermParams(fast=2, slow=3, rsi_period=2, rsi_max=100, stop_loss_pct=2, take_profit_pct=4)
NOW = datetime(2026, 10, 24, 12, 0, 30, tzinfo=KST)


def bars(closes, end=datetime(2026, 10, 24, 11, 0)):
    """1시간봉. 마지막 봉이 end에 시작한 봉(끝난 봉)이 되도록 만든다."""
    start = end - timedelta(hours=len(closes) - 1)
    return [
        Candle("KRW-BTC", start + timedelta(hours=i), Decimal(c), Decimal(c), Decimal(c), Decimal(c), Decimal(1))
        for i, c in enumerate(closes)
    ]


class FakeExchange:
    name = "fake"

    def __init__(self, price=100, closes=(100, 100, 100, 100)):
        self.price = Decimal(price)
        self.closes = list(closes)
        self.buys, self.sells = [], []
        self.coin = Decimal(0)
        self.fail_orders = False

    async def tickers(self, markets):
        return [Ticker(markets[0], self.price, Decimal(0), Decimal(0), Decimal(0), Decimal(0),
                       Decimal(0), Decimal(0), NOW)]

    async def candles(self, market, interval, count=200):
        # 진행 중인 봉(12시)도 함께 준다. 엔진은 이것을 빼야 한다
        return bars(self.closes) + [Candle(market, datetime(2026, 10, 24, 12), *(Decimal(1),) * 4, Decimal(1))]

    async def balances(self):
        return [Balance("BTC", self.coin, Decimal(0), Decimal(0))]

    async def buy_market(self, market, krw):
        if self.fail_orders:
            raise ExchangeError("주문 실패")
        self.buys.append(krw)
        self.coin += krw / self.price
        return OrderResult("b-1", market, Side.BUY, "price", "done", NOW)

    async def sell_market(self, market, volume):
        if self.fail_orders:
            raise ExchangeError("주문 실패")
        self.sells.append(volume)
        self.coin -= volume
        return OrderResult("s-1", market, Side.SELL, "market", "done", NOW)


def state(**kw):
    return TraderState(config=TraderConfig(enabled=True, params=PARAMS, **kw))


GOLDEN = (100, 100, 100, 90, 120)  # 마지막 봉에서 짧은 평균이 긴 평균을 위로 뚫음
DEAD = (100, 100, 100, 110, 80)


async def test_off_by_default_does_nothing():
    s = TraderState()
    assert s.config.enabled is False and s.config.mode == "paper"
    assert await step(s, FakeExchange(closes=GOLDEN), NOW) == []


async def test_buy_on_signal_uses_budget_with_fee_on_top():
    s, ex = state(), FakeExchange(closes=GOLDEN)
    [t] = await step(s, ex, NOW)
    assert t.ok and t.side == "buy"
    assert t.krw_amount == Decimal(99750)  # 100000 / 1.0025, 원 단위 내림
    assert t.krw_amount + t.fee_krw <= Decimal(100000)
    assert s.position is not None and s.cash_krw >= 0
    assert ex.buys == []  # 모의투자는 주문하지 않는다
    # 같은 봉에서는 다시 판단하지 않는다
    assert await step(s, ex, NOW + timedelta(seconds=30)) == []


async def test_in_progress_bar_is_ignored():
    s, ex = state(), FakeExchange(closes=GOLDEN)
    # 12시 봉이 진행 중이므로 마지막으로 끝난 봉은 11시 봉이다
    await step(s, ex, NOW)
    assert s.last_bar == datetime(2026, 10, 24, 11, 0)


async def test_sell_signal_records_pnl_after_fees():
    s, ex = state(), FakeExchange(closes=GOLDEN)
    await step(s, ex, NOW)
    # 한 시간 뒤, 12시 봉이 끝나며 데드 크로스
    ex.candles = lambda m, i, count=200: _async(bars(DEAD, end=datetime(2026, 10, 24, 12, 0)))
    [t] = await step(s, ex, NOW + timedelta(hours=1))
    assert t.side == "sell" and t.reason == "매도 신호"
    # 같은 가격에 사고팔면 수수료만큼 손해
    assert t.pnl_krw < 0 and abs(t.pnl_krw + (t.fee_krw + s.trades[0].fee_krw)) < 1
    assert s.position is None


async def _async(v):
    return v


async def test_stop_loss_on_current_price():
    s, ex = state(), FakeExchange(price=97)
    s.position = OpenPosition(entry_at=NOW, entry_price=Decimal(100), volume=Decimal(10), cost_krw=Decimal(1002.5))
    [t] = await step(s, ex, NOW)
    assert t.reason == "손절" and s.position is None


async def test_take_profit_on_current_price():
    s, ex = state(), FakeExchange(price=105)
    s.position = OpenPosition(entry_at=NOW, entry_price=Decimal(100), volume=Decimal(10), cost_krw=Decimal(1002.5))
    [t] = await step(s, ex, NOW)
    assert t.reason == "익절" and t.pnl_krw > 0


async def test_daily_loss_limit_sells_and_halts_until_midnight():
    # 손절은 넓게, 하루 손실 한도는 3% = 3,000원
    s = TraderState(config=TraderConfig(enabled=True, params=PARAMS.model_copy(update={"stop_loss_pct": Decimal(50)})))
    s.position = OpenPosition(entry_at=NOW, entry_price=Decimal(100), volume=Decimal(1000), cost_krw=Decimal(100250))
    ex = FakeExchange(price=96)
    [t] = await step(s, ex, NOW)
    assert t.reason == "하루 손실 한도"
    assert s.halted_until == datetime(2026, 10, 25, tzinfo=KST)
    ex.closes = GOLDEN
    assert await step(s, ex, NOW + timedelta(hours=1)) == []  # 멈춘 동안은 사지 않는다


async def test_emergency_stop_sells_and_disables():
    s, ex = state(), FakeExchange()
    s.position = OpenPosition(entry_at=NOW, entry_price=Decimal(100), volume=Decimal(10), cost_krw=Decimal(1002.5))
    s.stop_requested = True
    [t] = await step(s, ex, NOW)
    assert t.reason == "긴급 정지" and s.position is None
    assert s.config.enabled is False and s.stop_requested is False


async def test_live_buy_uses_balance_change_and_sell_sends_volume():
    s, ex = state(mode="live"), FakeExchange(closes=GOLDEN)
    ex.coin = Decimal(5)  # 원래 갖고 있던 코인은 건드리지 않는다
    [t] = await step(s, ex, NOW)
    assert ex.buys == [Decimal(99750)]
    assert t.volume == Decimal("997.5") and s.position.volume == Decimal("997.5")
    ex.price = Decimal(90)  # 손절
    await step(s, ex, NOW + timedelta(minutes=1))
    assert ex.sells == [Decimal("997.5")] and ex.coin == Decimal(5)


async def test_failed_order_pauses_trading():
    s, ex = state(mode="live"), FakeExchange(closes=GOLDEN)
    ex.fail_orders = True
    [t] = await step(s, ex, NOW)
    assert not t.ok and s.position is None
    s.last_bar = None
    assert await step(s, ex, NOW + timedelta(minutes=1)) == []  # 5분 동안 쉰다


async def test_breakout_buys_above_target_once_per_bar_and_sells_on_new_bar():
    p = PARAMS.model_copy(update={"strategy": "breakout", "k": Decimal("0.5")})
    s = TraderState(config=TraderConfig(enabled=True, params=p, daily_loss_limit_pct=Decimal(10)))
    ex = FakeExchange(price=104)
    prev = [Candle("KRW-BTC", datetime(2026, 10, 24, 10), *(Decimal(100),) * 4, Decimal(1)),
            Candle("KRW-BTC", datetime(2026, 10, 24, 11), Decimal(100), Decimal(105), Decimal(95), Decimal(100),
                   Decimal(1))]
    current = Candle("KRW-BTC", datetime(2026, 10, 24, 12), *(Decimal(100),) * 4, Decimal(1))
    ex.candles = lambda m, i, count=200: _async(prev + [current])
    assert await step(s, ex, NOW) == []  # 목표가 105 아래
    ex.price = Decimal(106)
    [t] = await step(s, ex, NOW + timedelta(minutes=1))
    assert t.side == "buy" and s.position is not None
    ex.price = Decimal(103)  # 손절가(2%) 아래지만, 변동성 돌파는 봉 중간에 팔지 않고 다음 봉 시가에 판다
    assert await step(s, ex, NOW + timedelta(minutes=2)) == []
    later = NOW + timedelta(hours=1)
    nxt = Candle("KRW-BTC", datetime(2026, 10, 24, 13), *(Decimal(100),) * 4, Decimal(1))
    ex.candles = lambda m, i, count=200: _async(prev + [current, nxt])
    ex.price = Decimal(107)
    [t] = await step(s, ex, later)
    assert t.side == "sell" and t.reason == "다음 봉 시가 청산"
