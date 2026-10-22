from datetime import datetime, time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.exchanges.base import ExchangeError, OrderResult, Side, Ticker
from app.strategies.dca import KST, DcaState, WeeklyDcaConfig, is_due, next_run, run_if_due


class FakeExchange:
    name = "fake"

    def __init__(self, fail=False):
        self.orders = []
        self.fail = fail

    async def tickers(self, markets):
        if self.fail:
            raise ExchangeError("연결 실패")
        return [Ticker(markets[0], Decimal(100), Decimal(0), Decimal(0), Decimal(0), Decimal(0),
                       Decimal(0), Decimal(0), datetime.now(KST))]

    async def buy_market(self, market, krw_amount):
        self.orders.append((market, krw_amount))
        return OrderResult("o-1", market, Side.BUY, "price", "wait", datetime.now(KST))


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
