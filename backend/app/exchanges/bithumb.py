"""빗썸 API 2.0 어댑터.

공개 API(마켓, 현재가, 캔들)는 키 없이 호출하고,
개인 API(잔고, 주문)는 Access/Secret Key로 만든 JWT를 붙인다.
엔드포인트마다 버전(/v1, /v2)이 다르다. 주문은 /v2/orders.
참고: https://apidocs.bithumb.com
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from .base import Balance, Candle, ExchangeError, Market, OrderResult, Side, Ticker

BASE_URL = "https://api.bithumb.com"

# 화면에서 쓰는 이름 → 빗썸 캔들 경로
CANDLE_PATHS = {
    "1m": "/v1/candles/minutes/1",
    "3m": "/v1/candles/minutes/3",
    "5m": "/v1/candles/minutes/5",
    "15m": "/v1/candles/minutes/15",
    "30m": "/v1/candles/minutes/30",
    "1h": "/v1/candles/minutes/60",
    "4h": "/v1/candles/minutes/240",
    "1d": "/v1/candles/days",
    "1w": "/v1/candles/weeks",
    "1M": "/v1/candles/months",
}


def _d(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


class BithumbExchange:
    name = "bithumb"

    def __init__(
        self,
        access_key: str | None = None,
        secret_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._access_key = access_key
        self._secret_key = secret_key
        self._client = client or httpx.AsyncClient(base_url=BASE_URL, timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    # ---- 인증 ----

    def _auth_header(self, params: dict[str, Any] | None = None) -> dict[str, str]:
        if not self._access_key or not self._secret_key:
            raise ExchangeError("빗썸 API 키가 설정되지 않았습니다. 설정 화면에서 키를 등록해 주세요.")
        payload: dict[str, Any] = {
            "access_key": self._access_key,
            "nonce": str(uuid.uuid4()),
            "timestamp": round(time.time() * 1000),
        }
        if params:
            query = urlencode(params).encode()
            payload["query_hash"] = hashlib.sha512(query).hexdigest()
            payload["query_hash_alg"] = "SHA512"
        token = jwt.encode(payload, self._secret_key, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    # ---- 요청 ----

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        private: bool = False,
    ) -> Any:
        headers = self._auth_header(body or params) if private else {}
        try:
            resp = await self._client.request(method, path, params=params, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ExchangeError(f"빗썸 서버에 연결하지 못했습니다: {exc}") from exc
        data = resp.json() if resp.content else None
        if resp.status_code >= 400:
            err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
            raise ExchangeError(
                f"빗썸 API 오류: {err.get('message') or resp.text}",
                status=resp.status_code,
                code=err.get("name"),
            )
        return data

    # ---- 공개 API ----

    async def markets(self, quote: str = "KRW") -> list[Market]:
        rows = await self._request("GET", "/v1/market/all", params={"isDetails": "false"})
        return [
            Market(code=r["market"], korean_name=r.get("korean_name", ""), english_name=r.get("english_name", ""))
            for r in rows
            if r["market"].startswith(f"{quote}-")
        ]

    async def tickers(self, markets: list[str]) -> list[Ticker]:
        if not markets:
            return []
        rows = await self._request("GET", "/v1/ticker", params={"markets": ",".join(markets)})
        return [
            Ticker(
                market=r["market"],
                price=_d(r["trade_price"]),
                change_rate=_d(r.get("signed_change_rate")),
                change_price=_d(r.get("signed_change_price")),
                high=_d(r.get("high_price")),
                low=_d(r.get("low_price")),
                volume_24h=_d(r.get("acc_trade_volume_24h")),
                value_24h=_d(r.get("acc_trade_price_24h")),
                timestamp=datetime.fromtimestamp(r["timestamp"] / 1000, tz=timezone.utc),
            )
            for r in rows
        ]

    async def candles(self, market: str, interval: str, count: int = 200) -> list[Candle]:
        path = CANDLE_PATHS.get(interval)
        if path is None:
            raise ExchangeError(f"지원하지 않는 캔들 간격입니다: {interval}")
        rows = await self._request("GET", path, params={"market": market, "count": min(count, 200)})
        candles = [
            Candle(
                market=r["market"],
                time_kst=datetime.fromisoformat(r["candle_date_time_kst"]),
                open=_d(r["opening_price"]),
                high=_d(r["high_price"]),
                low=_d(r["low_price"]),
                close=_d(r["trade_price"]),
                volume=_d(r["candle_acc_trade_volume"]),
            )
            for r in rows
        ]
        # 빗썸은 최신순으로 주므로 차트용으로 시간순 정렬
        return sorted(candles, key=lambda c: c.time_kst)

    # ---- 개인 API ----

    async def balances(self) -> list[Balance]:
        rows = await self._request("GET", "/v1/accounts", private=True)
        return [
            Balance(
                currency=r["currency"],
                balance=_d(r["balance"]),
                locked=_d(r.get("locked")),
                avg_buy_price=_d(r.get("avg_buy_price")),
            )
            for r in rows
        ]

    async def buy_market(self, market: str, krw_amount: Decimal) -> OrderResult:
        """원화 금액만큼 시장가 매수한다 (POST /v2/orders, order_type=price)."""
        if krw_amount <= 0:
            raise ExchangeError("주문 금액은 0원보다 커야 합니다.")
        body = {"market": market, "side": Side.BUY.value, "order_type": "price", "price": str(krw_amount)}
        r = await self._request("POST", "/v2/orders", body=body, private=True)
        # v2 응답 형식은 문서에 표가 없어, v1 필드 이름(uuid, ord_type)도 함께 받는다
        created = r.get("created_at")
        return OrderResult(
            order_id=r.get("order_id") or r["uuid"],
            market=r.get("market", market),
            side=Side.BUY,
            ord_type=r.get("order_type") or r.get("ord_type", "price"),
            state=r.get("state", ""),
            created_at=datetime.fromisoformat(created) if created else datetime.now(timezone.utc),
        )
