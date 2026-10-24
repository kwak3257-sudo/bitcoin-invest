"""단기 매매 자동 운영: 백테스트와 같은 전략(short_term)을 실시간으로 돌린다.

- 봉이 끝날 때마다 신호를 계산해 매수·매도한다. 진행 중인 봉은 쓰지 않는다.
- 엔진이 확인할 때마다(기본 30초) 현재가로 손절·익절을 확인한다.
- 운용 금액(budget_krw) 안에서만 산다. 실현 손익은 운용 금액에 더해지고 빠진다.
- 오늘(KST) 손실이 한도를 넘으면 보유분을 팔고 다음 날 0시까지 멈춘다.
- 긴급 정지를 누르면 보유분을 팔고 전략을 끈다.
기본값은 꺼짐, 모의투자(paper)다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..exchanges.base import Exchange, ExchangeError
from .dca import KST, MIN_ORDER_KRW
from .short_term import ShortTermParams, signals

INTERVAL_MINUTES = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
# 주문이 실패하면 이 시간 동안 새 주문을 내지 않는다 (같은 오류 반복과 알림 폭탄 방지)
ERROR_PAUSE = timedelta(minutes=5)


class TraderConfig(BaseModel):
    enabled: bool = False
    mode: Literal["paper", "live"] = "paper"
    market: str = "KRW-BTC"
    interval: Literal["15m", "30m", "1h", "4h"] = "1h"
    params: ShortTermParams = ShortTermParams()
    budget_krw: Decimal = Field(Decimal(100000), description="이 전략이 쓸 수 있는 최대 원화")
    daily_loss_limit_pct: Decimal = Field(Decimal(3), gt=0, le=50, description="운용 금액 대비 하루 손실 한도(%)")
    fee_rate: Decimal = Field(Decimal("0.0025"), ge=0, le=Decimal("0.01"))

    @field_validator("budget_krw")
    @classmethod
    def _min_budget(cls, v: Decimal) -> Decimal:
        if v < MIN_ORDER_KRW * 2:
            raise ValueError(f"운용 금액은 {MIN_ORDER_KRW * 2:,.0f}원 이상이어야 합니다.")
        return v

    @field_validator("market")
    @classmethod
    def _krw_market(cls, v: str) -> str:
        if not v.startswith("KRW-"):
            raise ValueError("원화(KRW) 마켓만 지원합니다. 예: KRW-BTC")
        return v


class OpenPosition(BaseModel):
    entry_at: datetime
    entry_price: Decimal
    volume: Decimal
    cost_krw: Decimal  # 매수 금액 + 매수 수수료


class TraderTrade(BaseModel):
    at: datetime
    market: str
    side: Literal["buy", "sell"]
    mode: Literal["paper", "live"]
    reason: str
    price: Decimal | None = None
    volume: Decimal = Decimal(0)
    krw_amount: Decimal = Decimal(0)  # 수수료를 뺀 거래 금액
    fee_krw: Decimal = Decimal(0)
    pnl_krw: Decimal | None = None  # 매도일 때: 매도 수수료까지 뺀 확정 손익
    order_id: str | None = None
    ok: bool = True
    message: str = ""


class TraderState(BaseModel):
    config: TraderConfig = TraderConfig()
    position: OpenPosition | None = None
    trades: list[TraderTrade] = []
    last_bar: datetime | None = None
    halted_until: datetime | None = None
    halt_reason: str | None = None
    stop_requested: bool = False

    @property
    def realized_pnl(self) -> Decimal:
        return sum((t.pnl_krw for t in self.trades if t.ok and t.pnl_krw is not None), Decimal(0))

    @property
    def fees_krw(self) -> Decimal:
        return sum((t.fee_krw for t in self.trades if t.ok), Decimal(0))

    @property
    def cash_krw(self) -> Decimal:
        """전략 장부상 남은 원화: 운용 금액 + 실현 손익 - 보유 중인 원가."""
        held = self.position.cost_krw if self.position else Decimal(0)
        return self.config.budget_krw + self.realized_pnl - held

    def realized_on(self, day) -> Decimal:
        return sum(
            (t.pnl_krw for t in self.trades if t.ok and t.pnl_krw is not None and t.at.astimezone(KST).date() == day),
            Decimal(0),
        )

    def last_error_at(self) -> datetime | None:
        return max((t.at for t in self.trades if not t.ok), default=None)


def position_value(state: TraderState, price: Decimal) -> Decimal:
    """지금 전부 팔면 받을 돈 (매도 수수료 제외)."""
    if state.position is None:
        return Decimal(0)
    return state.position.volume * price * (1 - state.config.fee_rate)


def unrealized_pnl(state: TraderState, price: Decimal) -> Decimal:
    if state.position is None:
        return Decimal(0)
    return position_value(state, price) - state.position.cost_krw


def today_pnl(state: TraderState, price: Decimal | None, now: datetime) -> Decimal:
    unreal = unrealized_pnl(state, price) if price is not None else Decimal(0)
    return state.realized_on(now.astimezone(KST).date()) + unreal


def daily_loss_limit_krw(cfg: TraderConfig) -> Decimal:
    return cfg.budget_krw * cfg.daily_loss_limit_pct / 100


async def _coin_balance(exchange: Exchange, market: str) -> Decimal:
    coin = market.split("-", 1)[1]
    for b in await exchange.balances():
        if b.currency == coin:
            return b.balance
    return Decimal(0)


async def _buy(state: TraderState, exchange: Exchange, price: Decimal, now: datetime, reason: str) -> TraderTrade:
    cfg = state.config
    # 수수료는 주문 금액 위에 붙는다고 보고, 수수료까지 장부 현금 안에 들어가게 주문한다
    krw = (state.cash_krw / (1 + cfg.fee_rate)).quantize(Decimal(1), rounding=ROUND_DOWN)
    if krw < MIN_ORDER_KRW:
        return TraderTrade(at=now, market=cfg.market, side="buy", mode=cfg.mode, reason=reason, ok=False,
                           message=f"남은 운용 금액({state.cash_krw:,.0f}원)이 최소 주문 금액보다 적습니다.")
    fee = (krw * cfg.fee_rate).quantize(Decimal("0.01"))
    volume = krw / price
    order_id = None
    try:
        if cfg.mode == "live":
            before = await _coin_balance(exchange, cfg.market)
            order = await exchange.buy_market(cfg.market, krw)
            order_id = order.order_id
    except ExchangeError as exc:
        return TraderTrade(at=now, market=cfg.market, side="buy", mode=cfg.mode, reason=reason, ok=False, message=str(exc))
    if cfg.mode == "live":
        # 시장가 체결 수량은 주문 응답에 없을 수 있어 잔고 변화로 확인한다. 확인이 안 되면 현재가로 추정한다
        try:
            got = await _coin_balance(exchange, cfg.market) - before
        except ExchangeError:
            got = Decimal(0)
        if got > 0:
            volume = got
            price = krw / volume
    state.position = OpenPosition(entry_at=now, entry_price=price, volume=volume, cost_krw=krw + fee)
    return TraderTrade(at=now, market=cfg.market, side="buy", mode=cfg.mode, reason=reason, price=price, volume=volume,
                       krw_amount=krw, fee_krw=fee, order_id=order_id,
                       message=f"{reason}: {price:,.0f}원에 {krw:,.0f}원어치 매수")


async def _sell(state: TraderState, exchange: Exchange, price: Decimal, now: datetime, reason: str) -> TraderTrade:
    cfg = state.config
    pos = state.position
    assert pos is not None
    volume = pos.volume
    order_id = None
    try:
        if cfg.mode == "live":
            # 기록과 실제 잔고가 다를 수 있어, 실제 잔고 중 기록한 만큼까지만 판다
            volume = min(volume, await _coin_balance(exchange, cfg.market))
            order = await exchange.sell_market(cfg.market, volume)
            order_id = order.order_id
    except ExchangeError as exc:
        return TraderTrade(at=now, market=cfg.market, side="sell", mode=cfg.mode, reason=reason, ok=False, message=str(exc))
    proceeds = volume * price
    fee = (proceeds * cfg.fee_rate).quantize(Decimal("0.01"))
    pnl = proceeds - fee - pos.cost_krw
    state.position = None
    return TraderTrade(at=now, market=cfg.market, side="sell", mode=cfg.mode, reason=reason, price=price, volume=volume,
                       krw_amount=proceeds, fee_krw=fee, pnl_krw=pnl, order_id=order_id,
                       message=f"{reason}: {price:,.0f}원에 매도, 손익 {pnl:+,.0f}원")


def _completed(candles, interval: str, now: datetime):
    """끝난 봉만 남긴다. 캔들 시각은 시간대 없는 KST다."""
    step = timedelta(minutes=INTERVAL_MINUTES[interval])
    now_kst = now.astimezone(KST).replace(tzinfo=None)
    return [c for c in candles if c.time_kst + step <= now_kst]


def _next_midnight(now: datetime) -> datetime:
    day = now.astimezone(KST).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=KST)


async def step(state: TraderState, exchange: Exchange, now: datetime) -> list[TraderTrade]:
    """엔진이 주기적으로 부른다. 새로 생긴 거래(실패 포함)를 돌려준다."""
    cfg = state.config
    done: list[TraderTrade] = []

    def record(trade: TraderTrade) -> None:
        state.trades.append(trade)
        done.append(trade)

    if state.stop_requested:
        state.stop_requested = False
        if state.position is not None:
            [ticker] = await exchange.tickers([cfg.market])
            trade = await _sell(state, exchange, ticker.price, now, "긴급 정지")
            record(trade)
            if not trade.ok:
                state.stop_requested = True  # 다음 확인 때 다시 판다
                return done
        state.config = cfg.model_copy(update={"enabled": False})
        return done

    if not cfg.enabled:
        return done
    if state.halted_until is not None:
        if now < state.halted_until:
            return done
        state.halted_until = state.halt_reason = None
    last_error = state.last_error_at()
    if last_error is not None and now - last_error < ERROR_PAUSE:
        return done

    [ticker] = await exchange.tickers([cfg.market])
    price = ticker.price

    # 1) 손절·익절: 현재가 기준
    pos = state.position
    if pos is not None:
        p = cfg.params
        if price <= pos.entry_price * (1 - p.stop_loss_pct / 100):
            record(await _sell(state, exchange, price, now, "손절"))
        elif price >= pos.entry_price * (1 + p.take_profit_pct / 100):
            record(await _sell(state, exchange, price, now, "익절"))

    if done and not done[-1].ok:
        return done  # 손절·익절 주문이 실패하면 잠시 쉰다

    # 2) 하루 손실 한도
    limit = daily_loss_limit_krw(cfg)
    if today_pnl(state, price, now) <= -limit:
        if state.position is not None:
            trade = await _sell(state, exchange, price, now, "하루 손실 한도")
            record(trade)
            if not trade.ok:
                return done
        state.halted_until = _next_midnight(now)
        state.halt_reason = f"오늘 손실이 한도({limit:,.0f}원)에 닿아 내일 0시까지 멈춥니다."
        return done
    if done:
        return done  # 이번에 이미 팔았으면 신호 확인은 다음 차례에

    # 3) 봉이 새로 끝났으면 신호 확인
    need = cfg.params.warmup + 50
    if need > 200:
        candles = await exchange.candle_history(cfg.market, cfg.interval, need)
    else:
        candles = await exchange.candles(cfg.market, cfg.interval, need)
    bars = _completed(candles, cfg.interval, now)
    if len(bars) < cfg.params.warmup or bars[-1].time_kst == state.last_bar:
        return done
    state.last_bar = bars[-1].time_kst
    sig = signals([float(c.close) for c in bars], cfg.params)[-1]
    if sig == "buy" and state.position is None:
        record(await _buy(state, exchange, price, now, "매수 신호"))
    elif sig == "sell" and state.position is not None:
        record(await _sell(state, exchange, price, now, "매도 신호"))
    return done
