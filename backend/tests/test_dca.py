from datetime import datetime, time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.exchanges.base import ExchangeError, OrderResult, Side, Ticker
from app.strategies.dca import (
    KST, DcaRun, DcaState, WeeklyDcaConfig, is_due, next_run, position_from_runs, run_if_due,
    take_profit_if_reached, take_profit_price,
)


class FakeExchange:
    name = "fake"

    def __init__(self, fail=False, price=100):
        self.orders = []
        self.sells = []
        self.fail = fail
        self.price = Decimal(price)

    async def tickers(self, markets):
        if self.fail:
            raise ExchangeError("연결 실패")
        return [Ticker(markets[0], self.price, Decimal(0), Decimal(0), Decimal(0), Decimal(0),
                       Decimal(0), Decimal(0), datetime.now(KST))]

    async def buy_market(self, market, krw_amount):
        self.orders.append((market, krw_amount))
        return OrderResult("o-1", market, Side.BUY, "price", "wait", datetime.now(KST))

    async def sell_market(self, market, volume):
        self.sells.append((market, volume))
        return OrderResult("s-1", market, Side.SELL, "market", "wait", datetime.now(KST))


def kst(*args):
    return datetime(*args, tzinfo=KST)


# 2026-10-19는 월요일
MON_9 = WeeklyDcaConfig(enabled=True, weekday=0, run_time=time(9, 0))


def test_defaults_off_and_paper():
    cfg = WeeklyDcaConfig()
    assert cfg.enabled is False and cfg.mode == "paper"
    assert cfg.describe() == "매주 월요일 09:00에 KRW-BTC 10,000원 매수"


def test_min_amount_and_krw_only():
    with pytest.raises(ValidationError):
        WeeklyDcaConfig(krw_amount=Decimal(1000))
    with pytest.raises(ValidationError):
        WeeklyDcaConfig(market="BTC-ETH")


def test_next_run():
    assert next_run(MON_9, kst(2026, 10, 19, 8, 59)) == kst(2026, 10, 19, 9, 0)
    assert next_run(MON_9, kst(2026, 10, 19, 9, 0)) == kst(2026, 10, 26, 9, 0)
    assert next_run(MON_9, kst(2026, 10, 22, 12, 0)) == kst(2026, 10, 26, 9, 0)


def test_is_due_once_per_week():
    state = DcaState(config=MON_9)
    assert not is_due(state, kst(2026, 10, 19, 8, 59))
    assert is_due(state, kst(2026, 10, 19, 9, 0))
    assert not is_due(DcaState(config=WeeklyDcaConfig(weekday=0)), kst(2026, 10, 19, 9, 0))  # 꺼짐


async def test_paper_run_records_without_ordering():
    state, ex = DcaState(config=MON_9), FakeExchange()
    run = await run_if_due(state, ex, kst(2026, 10, 19, 9, 0, 30))
    assert run.mode == "paper" and run.ok and ex.orders == []
    assert await run_if_due(state, ex, kst(2026, 10, 19, 9, 1)) is None  # 같은 주에 두 번 실행하지 않음
    assert (await run_if_due(state, ex, kst(2026, 10, 26, 9, 0))).ok
    assert state.total_spent == Decimal(20000)


async def test_live_run_places_order():
    state = DcaState(config=MON_9.model_copy(update={"mode": "live"}))
    ex = FakeExchange()
    run = await run_if_due(state, ex, kst(2026, 10, 19, 9, 0))
    assert ex.orders == [("KRW-BTC", Decimal(10000))] and run.order_id == "o-1"


async def test_cap_turns_strategy_off():
    state = DcaState(config=MON_9.model_copy(update={"max_total_krw": Decimal(15000)}))
    ex = FakeExchange()
    assert (await run_if_due(state, ex, kst(2026, 10, 19, 9, 0))).ok
    run = await run_if_due(state, ex, kst(2026, 10, 26, 9, 0))
    assert not run.ok and state.config.enabled is False


async def test_error_is_recorded_and_not_retried_same_week():
    state, ex = DcaState(config=MON_9), FakeExchange(fail=True)
    run = await run_if_due(state, ex, kst(2026, 10, 19, 9, 0))
    assert not run.ok and "연결 실패" in run.message
    assert await run_if_due(state, ex, kst(2026, 10, 19, 9, 5)) is None


def buy(at, krw, price, fee_rate=Decimal("0.0025")):
    krw, price = Decimal(krw), Decimal(price)
    return DcaRun(at=at, market="KRW-BTC", side="buy", krw_amount=krw, mode="paper",
                  price=price, volume=krw / price, fee_krw=krw * fee_rate)


def test_paper_buy_records_volume_and_fee():
    import asyncio
    state = DcaState(config=MON_9)
    run = asyncio.run(run_if_due(state, FakeExchange(price=50), kst(2026, 10, 19, 9, 0)))
    assert run.volume == Decimal(200) and run.fee_krw == Decimal("25.00")


def test_position_average_cost_and_realized_pnl():
    runs = [buy(kst(2026, 10, 5, 9), 10000, 100), buy(kst(2026, 10, 12, 9), 10000, 50)]
    p = position_from_runs(runs)
    assert p.volume == Decimal(300)
    assert p.invested_krw == Decimal(20050)  # 수수료 50원 포함
    # 절반을 개당 120원에 팔면: 받는 돈 18000 - 수수료 45 - 원가 10025
    runs.append(DcaRun(at=kst(2026, 10, 13, 9), market="KRW-BTC", side="sell", krw_amount=Decimal(18000),
                       mode="paper", price=Decimal(120), volume=Decimal(150), fee_krw=Decimal(45)))
    p = position_from_runs(runs)
    assert p.volume == Decimal(150)
    assert p.realized_pnl_krw == Decimal(18000) - 45 - Decimal(10025)
    assert p.fees_krw == Decimal(95)


TP = MON_9.model_copy(update={"take_profit_pct": Decimal(10), "take_profit_sell_ratio": Decimal("0.5")})


def test_take_profit_price_covers_both_fees():
    state = DcaState(config=TP, runs=[buy(kst(2026, 10, 5, 9), 10000, 100)])
    target = take_profit_price(TP, state.position())
    # 평균 단가 100.25(매수 수수료 포함) × 1.1 ÷ (1 - 0.0025)
    assert round(target, 4) == round(Decimal("100.25") * Decimal("1.1") / Decimal("0.9975"), 4)


async def test_take_profit_sells_half_once_then_cools_down():
    state = DcaState(config=TP, runs=[buy(kst(2026, 10, 5, 9), 10000, 100)])
    assert await take_profit_if_reached(state, FakeExchange(price=110), kst(2026, 10, 6, 9)) is None  # 수수료 때문에 아직 부족
    ex = FakeExchange(price=111)
    run = await take_profit_if_reached(state, ex, kst(2026, 10, 6, 9))
    assert run.side == "sell" and run.volume == Decimal(50) and ex.sells == []  # 모의투자는 주문 안 함
    assert await take_profit_if_reached(state, ex, kst(2026, 10, 6, 20)) is None  # 24시간 대기
    assert state.position().realized_pnl_krw > 0


async def test_take_profit_live_places_sell_order():
    cfg = TP.model_copy(update={"mode": "live"})
    state = DcaState(config=cfg, runs=[buy(kst(2026, 10, 5, 9), 10000, 100)])
    ex = FakeExchange(price=200)
    await take_profit_if_reached(state, ex, kst(2026, 10, 6, 9))
    assert ex.sells == [("KRW-BTC", Decimal(50))]


async def test_take_profit_off_by_default():
    state = DcaState(config=MON_9, runs=[buy(kst(2026, 10, 5, 9), 10000, 100)])
    assert await take_profit_if_reached(state, FakeExchange(price=1000), kst(2026, 10, 6, 9)) is None
