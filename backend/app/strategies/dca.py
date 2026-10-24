"""주간 정기 매수(DCA) + 목표 수익 매도 전략.

매주 정해진 요일과 시각(KST)에 정해진 원화 금액만큼 시장가 매수한다.
목표 수익을 켜 두면, 수수료를 양쪽 다 빼고도 평균 단가보다 목표 % 이상 높을 때
보유량의 일부를 팔아 수익을 확정한다.
기본값은 꺼짐이며, 모드는 모의투자(paper)로 시작한다.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from ..exchanges.base import Exchange, ExchangeError

KST = ZoneInfo("Asia/Seoul")

# 빗썸 원화 마켓 최소 주문 금액 (대략값, 공식 문서로 확인 필요)
MIN_ORDER_KRW = Decimal(5000)

WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


class WeeklyDcaConfig(BaseModel):
    enabled: bool = False
    mode: Literal["paper", "live"] = "paper"
    exchange: Literal["bithumb", "upbit"] = "bithumb"
    market: str = "KRW-BTC"
    weekday: int = Field(0, ge=0, le=6, description="0=월요일 … 6=일요일")
    run_time: time = time(9, 0)
    krw_amount: Decimal = Decimal(10000)
    max_total_krw: Decimal | None = Field(None, description="누적 매수 한도. 넘으면 자동으로 멈춘다")
    # 수수료율. 빗썸 기본 수수료(0.25%)로 잡아 두고, 쿠폰 등으로 낮으면 바꾼다
    fee_rate: Decimal = Field(Decimal("0.0025"), ge=0, le=Decimal("0.01"))
    # 목표 수익 매도. None이면 팔지 않는다
    take_profit_pct: Decimal | None = Field(None, gt=0, le=100, description="수수료를 뺀 뒤 평균 단가 대비 목표 수익률(%)")
    take_profit_sell_ratio: Decimal = Field(Decimal("0.5"), gt=0, le=1, description="목표 도달 시 파는 보유량 비율")
    take_profit_cooldown_hours: int = Field(24, ge=1, description="매도 후 다음 매도까지 최소 간격")

    @field_validator("krw_amount")
    @classmethod
    def _min_amount(cls, v: Decimal) -> Decimal:
        if v < MIN_ORDER_KRW:
            raise ValueError(f"1회 매수 금액은 {MIN_ORDER_KRW:,.0f}원 이상이어야 합니다.")
        return v

    @field_validator("market")
    @classmethod
    def _krw_market(cls, v: str) -> str:
        if not v.startswith("KRW-"):
            raise ValueError("원화(KRW) 마켓만 지원합니다. 예: KRW-BTC")
        return v

    def describe(self) -> str:
        hhmm = self.run_time.strftime("%H:%M")
        text = f"매주 {WEEKDAYS_KO[self.weekday]}요일 {hhmm}에 {self.market} {self.krw_amount:,.0f}원 매수"
        if self.take_profit_pct is not None:
            text += f", 수수료 제외 +{self.take_profit_pct}% 이상이면 보유량의 {self.take_profit_sell_ratio * 100:.0f}% 매도"
        return text


class DcaRun(BaseModel):
    """매수 또는 매도 한 건. krw_amount는 수수료를 뺀 거래 금액이다."""

    at: datetime
    market: str
    side: Literal["buy", "sell"] = "buy"
    krw_amount: Decimal
    mode: Literal["paper", "live"]
    order_id: str | None = None
    price: Decimal | None = None
    volume: Decimal = Decimal(0)
    fee_krw: Decimal = Decimal(0)
    ok: bool = True
    message: str = ""


class Position(BaseModel):
    """실행 기록으로 계산한 보유 현황 (평균 단가는 매수 수수료 포함)."""

    volume: Decimal = Decimal(0)
    cost_krw: Decimal = Decimal(0)  # 남은 보유량의 원가(수수료 포함)
    invested_krw: Decimal = Decimal(0)  # 매수에 쓴 총액(수수료 포함)
    realized_pnl_krw: Decimal = Decimal(0)  # 매도로 확정한 손익(수수료 제외 후)
    fees_krw: Decimal = Decimal(0)

    @property
    def avg_cost(self) -> Decimal | None:
        return self.cost_krw / self.volume if self.volume > 0 else None


def position_from_runs(runs: list[DcaRun]) -> Position:
    p = Position()
    for r in sorted((r for r in runs if r.ok and r.volume > 0), key=lambda r: r.at):
        if r.side == "buy":
            p.volume += r.volume
            p.cost_krw += r.krw_amount + r.fee_krw
            p.invested_krw += r.krw_amount + r.fee_krw
        else:
            sold = min(r.volume, p.volume)
            basis = p.cost_krw * sold / p.volume if p.volume > 0 else Decimal(0)
            p.realized_pnl_krw += r.krw_amount - r.fee_krw - basis
            p.cost_krw -= basis
            p.volume -= sold
        p.fees_krw += r.fee_krw
    return p


class DcaState(BaseModel):
    config: WeeklyDcaConfig = WeeklyDcaConfig()
    runs: list[DcaRun] = []

    @property
    def total_spent(self) -> Decimal:
        return sum((r.krw_amount for r in self.runs if r.ok and r.side == "buy"), Decimal(0))

    @property
    def last_run_at(self) -> datetime | None:
        """마지막 정기 매수 시도 시각 (실패 포함, 매도 제외)."""
        return max((r.at for r in self.runs if r.side == "buy"), default=None)

    @property
    def last_sell_at(self) -> datetime | None:
        """마지막 매도 시도 시각. 실패도 넣어 오류가 나도 매번 다시 시도하지 않게 한다."""
        return max((r.at for r in self.runs if r.side == "sell"), default=None)

    def position(self) -> Position:
        return position_from_runs(self.runs)


def scheduled_time(config: WeeklyDcaConfig, now: datetime) -> datetime:
    """now가 속한 주의 예정 시각(KST)."""
    now = now.astimezone(KST)
    monday = (now - timedelta(days=now.weekday())).date()
    day = monday + timedelta(days=config.weekday)
    return datetime.combine(day, config.run_time, tzinfo=KST)


def next_run(config: WeeklyDcaConfig, now: datetime) -> datetime:
    """now 이후 가장 가까운 예정 시각(KST)."""
    this_week = scheduled_time(config, now)
    return this_week if this_week > now else this_week + timedelta(weeks=1)


def is_due(state: DcaState, now: datetime) -> bool:
    """이번 주 예정 시각이 지났고 그 뒤로 아직 실행하지 않았으면 True."""
    if not state.config.enabled:
        return False
    due_at = scheduled_time(state.config, now)
    if now < due_at:
        return False
    last = state.last_run_at
    return last is None or last < due_at


def take_profit_price(cfg: WeeklyDcaConfig, position: Position) -> Decimal | None:
    """이 가격 이상이면 매도 수수료를 빼고도 목표 수익률을 넘는다."""
    avg = position.avg_cost
    if cfg.take_profit_pct is None or avg is None:
        return None
    return avg * (1 + cfg.take_profit_pct / 100) / (1 - cfg.fee_rate)


async def run_if_due(state: DcaState, exchange: Exchange, now: datetime) -> DcaRun | None:
    """예정 시각이 됐으면 한 번 매수하고 기록을 state에 추가한다."""
    if not is_due(state, now):
        return None
    cfg = state.config
    if cfg.max_total_krw is not None and state.total_spent + cfg.krw_amount > cfg.max_total_krw:
        state.config = cfg.model_copy(update={"enabled": False})
        run = DcaRun(
            at=now, market=cfg.market, krw_amount=Decimal(0), mode=cfg.mode, ok=False,
            message=f"누적 매수 한도 {cfg.max_total_krw:,.0f}원에 도달해 전략을 껐습니다.",
        )
        state.runs.append(run)
        return run

    # 수수료는 주문 금액 위에 붙는다고 보고, 거래 금액 = 설정 금액으로 기록한다
    fee = (cfg.krw_amount * cfg.fee_rate).quantize(Decimal("0.01"))
    try:
        [ticker] = await exchange.tickers([cfg.market])
        volume = cfg.krw_amount / ticker.price
        order_id = None
        if cfg.mode == "live":
            order = await exchange.buy_market(cfg.market, cfg.krw_amount)
            order_id = order.order_id
        run = DcaRun(
            at=now, market=cfg.market, side="buy", krw_amount=cfg.krw_amount, mode=cfg.mode,
            order_id=order_id, price=ticker.price, volume=volume, fee_krw=fee,
            message="실거래 매수 주문을 넣었습니다." if cfg.mode == "live" else "모의투자로 매수를 기록했습니다.",
        )
    except ExchangeError as exc:
        run = DcaRun(at=now, market=cfg.market, krw_amount=Decimal(0), mode=cfg.mode, ok=False, message=str(exc))
    state.runs.append(run)
    return run


async def take_profit_if_reached(state: DcaState, exchange: Exchange, now: datetime) -> DcaRun | None:
    """현재가가 목표 가격 이상이면 보유량의 일부를 시장가로 판다."""
    cfg = state.config
    if not cfg.enabled or cfg.take_profit_pct is None:
        return None
    last_sell = state.last_sell_at
    if last_sell is not None and now - last_sell < timedelta(hours=cfg.take_profit_cooldown_hours):
        return None
    position = state.position()
    target = take_profit_price(cfg, position)
    if target is None:
        return None

    [ticker] = await exchange.tickers([cfg.market])
    if ticker.price < target:
        return None
    volume = position.volume * cfg.take_profit_sell_ratio
    proceeds = volume * ticker.price
    if proceeds < MIN_ORDER_KRW:
        return None  # 최소 주문 금액보다 작으면 팔지 않는다

    fee = (proceeds * cfg.fee_rate).quantize(Decimal("0.01"))
    try:
        order_id = None
        if cfg.mode == "live":
            order = await exchange.sell_market(cfg.market, volume)
            order_id = order.order_id
        run = DcaRun(
            at=now, market=cfg.market, side="sell", krw_amount=proceeds, mode=cfg.mode,
            order_id=order_id, price=ticker.price, volume=volume, fee_krw=fee,
            message=f"목표 수익 도달(기준가 {target:,.0f}원)로 보유량의 {cfg.take_profit_sell_ratio * 100:.0f}%를 매도했습니다.",
        )
    except ExchangeError as exc:
        run = DcaRun(at=now, market=cfg.market, side="sell", krw_amount=Decimal(0), mode=cfg.mode, ok=False, message=str(exc))
    state.runs.append(run)
    return run
