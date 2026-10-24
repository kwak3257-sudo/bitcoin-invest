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


def run_backtest(candles: list[Candle], params: ShortTermParams, costs: BacktestCosts) -> BacktestResult:
    if len(candles) < params.slow + 2:
        raise ValueError(f"캔들이 너무 적습니다. 최소 {params.slow + 2}개가 필요합니다(현재 {len(candles)}개).")

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
    hold_qty = initial / (o[0] * (1 + slip) * (1 + fee))  # 비교용: 첫 봉에 전부 사서 보유

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

    for i in range(len(candles)):
        # 1) 직전 봉 신호를 이번 봉 시가에 체결
        if i > 0:
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
        exposure_pct=in_market_bars / len(candles) * 100,
        trades=trades,
        equity=equity,
    )
