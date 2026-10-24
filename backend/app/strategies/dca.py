"""주간 정기 매수(DCA) 전략.

매주 정해진 요일과 시각(KST)에 정해진 원화 금액만큼 시장가 매수한다.
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
        return f"매주 {WEEKDAYS_KO[self.weekday]}요일 {hhmm}에 {self.market} {self.krw_amount:,.0f}원 매수"


class DcaRun(BaseModel):
    at: datetime
    market: str
    krw_amount: Decimal
    mode: Literal["paper", "live"]
    order_id: str | None = None
    price: Decimal | None = None
    ok: bool = True
    message: str = ""


class DcaState(BaseModel):
    config: WeeklyDcaConfig = WeeklyDcaConfig()
    runs: list[DcaRun] = []

    @property
    def total_spent(self) -> Decimal:
        return sum((r.krw_amount for r in self.runs if r.ok), Decimal(0))

    @property
    def last_run_at(self) -> datetime | None:
        return max((r.at for r in self.runs), default=None)


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

    try:
        [ticker] = await exchange.tickers([cfg.market])
        if cfg.mode == "live":
            order = await exchange.buy_market(cfg.market, cfg.krw_amount)
            run = DcaRun(
                at=now, market=cfg.market, krw_amount=cfg.krw_amount, mode="live",
                order_id=order.order_id, price=ticker.price, message="실거래 매수 주문을 넣었습니다.",
            )
        else:
            run = DcaRun(
                at=now, market=cfg.market, krw_amount=cfg.krw_amount, mode="paper",
                price=ticker.price, message="모의투자로 매수를 기록했습니다.",
            )
    except ExchangeError as exc:
        run = DcaRun(at=now, market=cfg.market, krw_amount=Decimal(0), mode=cfg.mode, ok=False, message=str(exc))
    state.runs.append(run)
    return run
