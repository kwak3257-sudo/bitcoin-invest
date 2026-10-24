"""백테스트: 과거 캔들로 단기 매매 전략을 돌려 수수료·슬리피지를 뺀 성과를 계산한다.

가정 (보수적으로 잡았다):
- 신호는 봉이 끝난 뒤 계산하고, 주문은 다음 봉 시가에 체결된다.
- 손절·익절은 봉의 저가·고가로 판단한다. 한 봉에서 둘 다 닿으면 손절이 먼저라고 본다.
- 가격이 손절가 아래(익절가 위)에서 시작하면 그 시가에 체결된다.
- 매수·매도 모두 수수료와 슬리피지(불리한 방향으로 가격이 밀림)를 낸다.
- 매수할 때는 가진 현금을 모두 쓴다. 한 번에 한 포지션만 잡는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from .exchanges.base import Candle
from .strategies.short_term import ShortTermParams, signals


class BacktestCosts(BaseModel):
    fee_rate: Decimal = Field(Decimal("0.0025"), ge=0, le=Decimal("0.01"))
    slippage_pct: Decimal = Field(Decimal("0.05"), ge=0, le=5, description="체결 때 불리하게 밀리는 가격(%)")
    initial_krw: Decimal = Field(Decimal(100000), gt=0)


@dataclass
class Trade:
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    reason: str = ""
    pnl_krw: float = 0.0
    pnl_pct: float = 0.0
    fees_krw: float = 0.0


@dataclass
class BacktestResult:
    initial_krw: float
    final_krw: float
    return_pct: float
    buy_hold_pct: float
    max_drawdown_pct: float
    trade_count: int
    win_rate_pct: float
    fees_krw: float
    exposure_pct: float
    trades: list[Trade]
    equity: list[dict]  # [{"time", "equity", "buy_hold"}]


def run_backtest(
    candles: list[Candle], params: ShortTermParams, costs: BacktestCosts, trade_from: int = 0
) -> BacktestResult:
    """trade_from보다 앞의 봉은 지표 계산에만 쓰고, 거래와 성과는 그 봉부터 센다."""
    need = params.warmup + 1
    if len(candles) - trade_from < 2 or len(candles) < need:
        raise ValueError(f"캔들이 너무 적습니다. 최소 {need}개가 필요합니다(현재 {len(candles)}개).")

    o = [float(c.open) for c in candles]
    h = [float(c.high) for c in candles]
    lo = [float(c.low) for c in candles]
    cl = [float(c.close) for c in candles]
    t = [c.time_kst for c in candles]
    sig = signals(cl, params)

    fee = float(costs.fee_rate)
    slip = float(costs.slippage_pct) / 100
    stop = float(params.stop_loss_pct) / 100
    take = float(params.take_profit_pct) / 100
    initial = float(costs.initial_krw)

    cash, qty = initial, 0.0
    open_trade: Trade | None = None
    cost_basis = 0.0  # 진입에 쓴 돈(수수료 포함)
    trades: list[Trade] = []
    fees = 0.0
    equity: list[dict] = []
    in_market_bars = 0
    hold_qty = initial / (o[trade_from] * (1 + slip) * (1 + fee))  # 비교용: 첫 봉에 전부 사서 보유

    def buy(i: int, price: float) -> None:
        nonlocal cash, qty, open_trade, cost_basis, fees
        fill = price * (1 + slip)
        qty = cash / (fill * (1 + fee))
        f = qty * fill * fee
        fees += f
        cost_basis = cash
        cash = 0.0
        open_trade = Trade(entry_time=t[i], entry_price=fill, fees_krw=f)

    def sell(i: int, price: float, reason: str) -> None:
        nonlocal cash, qty, open_trade, fees
        fill = price * (1 - slip)
        gross = qty * fill
        f = gross * fee
        fees += f
        cash = gross - f
        assert open_trade is not None
        open_trade.exit_time, open_trade.exit_price, open_trade.reason = t[i], fill, reason
        open_trade.fees_krw += f
        open_trade.pnl_krw = cash - cost_basis
        open_trade.pnl_pct = open_trade.pnl_krw / cost_basis * 100
        trades.append(open_trade)
        open_trade, qty = None, 0.0

    for i in range(trade_from, len(candles)):
        # 1) 직전 봉 신호를 이번 봉 시가에 체결
        if i > trade_from:
            if sig[i - 1] == "buy" and open_trade is None:
                buy(i, o[i])
            elif sig[i - 1] == "sell" and open_trade is not None:
                sell(i, o[i], "신호 청산")

        # 2) 봉 안에서 손절·익절 (손절 우선)
        if open_trade is not None:
            stop_px = open_trade.entry_price * (1 - stop)
            take_px = open_trade.entry_price * (1 + take)
            if lo[i] <= stop_px:
                sell(i, min(o[i], stop_px), "손절")
            elif h[i] >= take_px:
                sell(i, max(o[i], take_px), "익절")

        if open_trade is not None:
            in_market_bars += 1
        value = cash + qty * cl[i] * (1 - fee)
        equity.append({"time": t[i], "equity": value, "buy_hold": hold_qty * cl[i] * (1 - fee)})

    # 마지막에 들고 있으면 종가로 정리해 성과에 반영
    if open_trade is not None:
        sell(len(candles) - 1, cl[-1], "기간 종료")
        equity[-1]["equity"] = cash

    peak, mdd = 0.0, 0.0
    for e in equity:
        peak = max(peak, e["equity"])
        mdd = max(mdd, (peak - e["equity"]) / peak * 100 if peak else 0)

    wins = sum(1 for tr in trades if tr.pnl_krw > 0)
    return BacktestResult(
        initial_krw=initial,
        final_krw=cash,
        return_pct=(cash / initial - 1) * 100,
        buy_hold_pct=(equity[-1]["buy_hold"] / initial - 1) * 100,
        max_drawdown_pct=mdd,
        trade_count=len(trades),
        win_rate_pct=wins / len(trades) * 100 if trades else 0.0,
        fees_krw=fees,
        exposure_pct=in_market_bars / len(equity) * 100,
        trades=trades,
        equity=equity,
    )


# ---- 자동 최적화 ----

GRID = {
    "fast": [5, 9, 12, 20],
    "slow": [20, 26, 50, 100],
    "trend_period": [None, 100, 200],
    "stop_loss_pct": [2, 3, 5],
    "take_profit_pct": [4, 6, 10],
}
MIN_TRADES = 3  # 앞 기간에 이보다 적게 거래한 설정은 우연일 수 있어 뺀다


def optimize(candles: list[Candle], costs: BacktestCosts, train_ratio: float = 0.7, top: int = 5) -> dict:
    """여러 설정을 앞 기간(학습)에서 돌려 고르고, 고른 설정을 뒤 기간(검증)에서 다시 돌린다.

    검증 기간 성과는 고를 때 쓰지 않은 데이터라서, 과거에만 맞춘 설정인지 가려낼 수 있다.
    """
    split = int(len(candles) * train_ratio)
    train = candles[:split]
    results = []
    for fast in GRID["fast"]:
        for slow in GRID["slow"]:
            if fast >= slow:
                continue
            for trend in GRID["trend_period"]:
                for stop in GRID["stop_loss_pct"]:
                    for take in GRID["take_profit_pct"]:
                        p = ShortTermParams(fast=fast, slow=slow, trend_period=trend,
                                            stop_loss_pct=stop, take_profit_pct=take)
                        if len(train) < p.warmup + 50 or split < p.warmup:
                            continue
                        r = run_backtest(train, p, costs)
                        if r.trade_count >= MIN_TRADES:
                            results.append((p, r))
    if not results:
        raise ValueError("최적화할 데이터가 모자랍니다. 기간(봉 개수)을 늘려 주세요.")
    results.sort(key=lambda x: x[1].return_pct, reverse=True)

    def summary(r: BacktestResult) -> dict:
        return {k: getattr(r, k) for k in (
            "return_pct", "buy_hold_pct", "max_drawdown_pct", "trade_count", "win_rate_pct", "fees_krw")}

    picks = []
    for p, r in results[:top]:
        test = run_backtest(candles, p, costs, trade_from=split)
        picks.append({"params": p, "train": summary(r), "test": summary(test)})
    return {
        "tested": len(results),
        "train_from": candles[0].time_kst,
        "test_from": candles[split].time_kst,
        "to": candles[-1].time_kst,
        "picks": picks,
    }
