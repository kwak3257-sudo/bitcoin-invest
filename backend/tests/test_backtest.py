from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest import BacktestCosts, run_backtest
from app.exchanges.base import Candle
from app.strategies.short_term import ShortTermParams, rsi, signals, sma


def candles_from(closes, start=datetime(2026, 1, 1)):
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(Candle("KRW-BTC", start + timedelta(hours=i), Decimal(str(o)), Decimal(str(max(o, c))),
                          Decimal(str(min(o, c))), Decimal(str(c)), Decimal(1)))
        prev = c
    return out


def test_sma():
    assert sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]


def test_rsi_bounds():
    up = rsi([float(i) for i in range(30)], 14)
    assert up[14] == 100.0
    down = rsi([float(30 - i) for i in range(30)], 14)
    assert down[-1] == 0.0


def test_params_validation():
    with pytest.raises(ValueError):
        ShortTermParams(fast=30, slow=10)


P = ShortTermParams(fast=2, slow=4, rsi_period=2, rsi_max=Decimal(101) - 1, stop_loss_pct=Decimal(50), take_profit_pct=Decimal(200))


def test_cross_signals():
    closes = [10, 10, 10, 10, 9, 8, 9, 11, 13, 12, 10, 8]
    s = signals(closes, P)
    b = s.index("buy")
    assert closes[b] > closes[b - 1]  # 오르는 봉에서 상향 교차
    assert "sell" in s[b + 1:]  # 이후 하향 교차로 청산 신호


def test_fees_make_flat_market_lose_money():
    # 오르내림만 반복하는 시장: 매매할수록 수수료만 나간다
    closes = [100, 100, 100, 100] + [100, 104, 108, 104, 100, 96, 92, 96] * 6
    costs = BacktestCosts(fee_rate=Decimal("0.0025"), slippage_pct=Decimal("0.05"))
    r = run_backtest(candles_from(closes), P, costs)
    assert r.trade_count > 0
    assert r.fees_krw > 0
    free = run_backtest(candles_from(closes), P, BacktestCosts(fee_rate=Decimal(0), slippage_pct=Decimal(0)))
    assert r.final_krw < free.final_krw


def test_entry_is_next_bar_open_and_stop_loss():
    # 상승 교차 뒤 급락 → 다음 봉 시가 진입, 손절로 청산
    closes = [100, 100, 100, 100, 99, 98, 101, 105, 80, 80, 80]
    p = P.model_copy(update={"stop_loss_pct": Decimal(5)})
    r = run_backtest(candles_from(closes), p, BacktestCosts(fee_rate=Decimal(0), slippage_pct=Decimal(0)))
    first = r.trades[0]
    i = signals([float(c) for c in closes], p).index("buy")
    assert first.entry_price == pytest.approx(closes[i])  # 다음 봉 시가 = 신호 봉 종가
    assert first.reason == "손절"
    assert first.pnl_pct == pytest.approx(-5, abs=0.01)


def test_too_few_candles():
    with pytest.raises(ValueError):
        run_backtest(candles_from([1, 2, 3]), ShortTermParams(), BacktestCosts())


def test_metrics_shape():
    closes = [100 + (i % 10) * 2 for i in range(200)]
    r = run_backtest(candles_from(closes), ShortTermParams(fast=3, slow=8), BacktestCosts())
    assert len(r.equity) == 200
    assert 0 <= r.max_drawdown_pct <= 100
    assert 0 <= r.win_rate_pct <= 100
