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


def test_trend_filter_blocks_buys_in_downtrend():
    from app.strategies.short_term import signals

    # 긴 하락 뒤 잠깐 반등: 교차는 나오지만 200봉 평균 아래라 사지 않는다
    closes = [300 - i for i in range(250)] + [50, 50, 50, 40, 70]
    base = ShortTermParams(fast=2, slow=3, rsi_period=2, rsi_max=100)
    assert "buy" in signals(closes, base)
    assert "buy" not in signals(closes, base.model_copy(update={"trend_period": 200}))


def test_trade_from_ignores_earlier_bars():
    candles = candles_from([100] * 30 + [110] * 30)
    p = ShortTermParams(fast=2, slow=3, rsi_period=2)
    r = run_backtest(candles, p, BacktestCosts(), trade_from=40)
    assert r.equity[0]["time"] == candles[40].time_kst
    assert all(t.entry_time >= candles[40].time_kst for t in r.trades)


def test_optimize_reports_train_and_test(monkeypatch):
    import math

    from app import backtest

    monkeypatch.setattr(backtest, "GRID", {
        "fast": [3, 5], "slow": [10], "trend_period": [None], "stop_loss_pct": [2], "take_profit_pct": [4],
    })
    closes = [100 + 10 * math.sin(i / 8) for i in range(400)]
    out = backtest.optimize(candles_from(closes), BacktestCosts())
    assert out["tested"] == 2 and len(out["picks"]) == 2
    first = out["picks"][0]
    assert first["train"]["return_pct"] >= out["picks"][1]["train"]["return_pct"]
    assert "return_pct" in first["test"]


def bar(i, o, h, lo, c):
    return Candle("KRW-BTC", datetime(2026, 1, 1) + timedelta(days=i), Decimal(o), Decimal(h), Decimal(lo), Decimal(c),
                  Decimal(1))


def test_breakout_buys_at_target_and_sells_next_open():
    candles = [bar(0, 100, 105, 95, 100), bar(1, 100, 110, 99, 108), bar(2, 108, 109, 107, 108)]
    p = ShortTermParams(strategy="breakout", k=Decimal("0.5"))
    r = run_backtest(candles, p, BacktestCosts(fee_rate=Decimal(0), slippage_pct=Decimal(0)))
    [t] = r.trades
    assert t.entry_price == 105 and t.exit_price == 108 and t.reason == "다음 봉 시가 청산"
    assert round(r.final_krw) == round(100000 * 108 / 105)


def test_breakout_no_entry_below_target_and_stop_on_close():
    flat = [bar(0, 100, 105, 95, 100), bar(1, 100, 104, 99, 101), bar(2, 101, 102, 100, 101)]
    p = ShortTermParams(strategy="breakout", k=Decimal("0.5"), stop_loss_pct=Decimal(2))
    assert run_backtest(flat, p, BacktestCosts()).trade_count == 0
    crash = [bar(0, 100, 105, 95, 100), bar(1, 100, 106, 90, 91), bar(2, 91, 92, 90, 91)]
    [t] = run_backtest(crash, p, BacktestCosts(fee_rate=Decimal(0), slippage_pct=Decimal(0))).trades
    assert t.reason == "손절" and t.exit_price == 105 * 0.98
