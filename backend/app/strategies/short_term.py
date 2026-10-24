"""단기 매매 전략: 이동평균 교차 + RSI 필터, 손절·익절.

롱(매수) 전용이다. 한 번에 한 포지션만 잡는다.
- 진입: 짧은 이동평균이 긴 이동평균을 아래에서 위로 뚫고, RSI가 상한보다 낮을 때
- 청산: 짧은 이동평균이 긴 이동평균 아래로 내려가거나, 손절가·익절가에 닿을 때
신호는 봉이 끝난 뒤 계산하고, 주문은 다음 봉 시가에 낸다 (미래 정보를 쓰지 않기 위해).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class ShortTermParams(BaseModel):
    fast: int = Field(9, ge=2, le=100, description="짧은 이동평균 기간(봉 수)")
    slow: int = Field(26, ge=3, le=300, description="긴 이동평균 기간(봉 수)")
    rsi_period: int = Field(14, ge=2, le=100)
    rsi_max: Decimal = Field(Decimal(70), gt=0, le=100, description="RSI가 이보다 높으면 과열로 보고 진입하지 않는다")
    stop_loss_pct: Decimal = Field(Decimal(2), gt=0, le=50, description="진입가 대비 손절(%)")
    take_profit_pct: Decimal = Field(Decimal(4), gt=0, le=200, description="진입가 대비 익절(%)")

    @model_validator(mode="after")
    def _fast_lt_slow(self):
        if self.fast >= self.slow:
            raise ValueError("짧은 이동평균 기간은 긴 이동평균 기간보다 작아야 합니다.")
        return self


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def rsi(values: list[float], period: int) -> list[float | None]:
    """와일더(Wilder) 방식 RSI."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def signals(closes: list[float], p: ShortTermParams) -> list[str | None]:
    """각 봉이 끝난 시점의 신호: 'buy', 'sell', None."""
    f, s, r = sma(closes, p.fast), sma(closes, p.slow), rsi(closes, p.rsi_period)
    out: list[str | None] = [None] * len(closes)
    for i in range(1, len(closes)):
        if None in (f[i], s[i], f[i - 1], s[i - 1]):
            continue
        if f[i - 1] <= s[i - 1] and f[i] > s[i] and r[i] is not None and r[i] < float(p.rsi_max):
            out[i] = "buy"
        elif f[i - 1] >= s[i - 1] and f[i] < s[i]:
            out[i] = "sell"
    return out
