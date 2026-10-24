"""거래소 공통 인터페이스.

전략 코드와 화면은 이 모듈의 타입과 Exchange 프로토콜만 사용한다.
거래소별 차이(빗썸, 업비트)는 각 어댑터 안에서만 처리한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol


class Side(str, Enum):
    BUY = "bid"
    SELL = "ask"


@dataclass(frozen=True)
class Market:
    code: str  # 예: "KRW-BTC"
    korean_name: str
    english_name: str

    @property
    def quote(self) -> str:
        return self.code.split("-", 1)[0]

    @property
    def base(self) -> str:
        return self.code.split("-", 1)[1]


@dataclass(frozen=True)
class Ticker:
    market: str
    price: Decimal
    change_rate: Decimal  # 전일 대비 등락률, 0.0123 = +1.23%
    change_price: Decimal
    high: Decimal
    low: Decimal
    volume_24h: Decimal
    value_24h: Decimal  # 24시간 거래대금(원)
    timestamp: datetime


@dataclass(frozen=True)
class Candle:
    market: str
    time_kst: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class Balance:
    currency: str
    balance: Decimal
    locked: Decimal
    avg_buy_price: Decimal


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    market: str
    side: Side
    ord_type: str
    state: str
    created_at: datetime


class ExchangeError(Exception):
    """거래소 API 오류. message는 화면에 그대로 보여 줄 한국어 문장이다."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class Exchange(Protocol):
    name: str

    async def markets(self, quote: str = "KRW") -> list[Market]: ...

    async def tickers(self, markets: list[str]) -> list[Ticker]: ...

    async def candles(self, market: str, interval: str, count: int = 200) -> list[Candle]: ...

    async def balances(self) -> list[Balance]: ...

    async def buy_market(self, market: str, krw_amount: Decimal) -> OrderResult: ...

    async def sell_market(self, market: str, volume: Decimal) -> OrderResult: ...

    async def close(self) -> None: ...
