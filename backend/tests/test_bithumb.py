import hashlib
import json
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import jwt
import pytest
import respx

from app.exchanges.base import ExchangeError
from app.exchanges.bithumb import BASE_URL, BithumbExchange


@pytest.fixture
async def ex():
    e = BithumbExchange("ak", "sk")
    yield e
    await e.close()


@respx.mock
async def test_markets_filters_krw(ex):
    respx.get(f"{BASE_URL}/v1/market/all").respond(json=[
        {"market": "KRW-BTC", "korean_name": "비트코인", "english_name": "Bitcoin"},
        {"market": "BTC-ETH", "korean_name": "이더리움", "english_name": "Ethereum"},
    ])
    rows = await ex.markets()
    assert [m.code for m in rows] == ["KRW-BTC"]
    assert rows[0].korean_name == "비트코인"


@respx.mock
async def test_tickers_parse(ex):
    route = respx.get(f"{BASE_URL}/v1/ticker").respond(json=[{
        "market": "KRW-BTC", "trade_price": 150000000, "signed_change_rate": 0.0123,
        "signed_change_price": 1800000, "high_price": 151000000, "low_price": 147000000,
        "acc_trade_volume_24h": 1234.5, "acc_trade_price_24h": 185000000000, "timestamp": 1761177600000,
    }])
    [t] = await ex.tickers(["KRW-BTC"])
    assert route.calls.last.request.url.params["markets"] == "KRW-BTC"
    assert t.price == Decimal("150000000")
    assert t.change_rate == Decimal("0.0123")


@respx.mock
async def test_candles_sorted_oldest_first(ex):
    def row(ts, close):
        return {"market": "KRW-BTC", "candle_date_time_kst": ts, "opening_price": 1, "high_price": 2,
                "low_price": 1, "trade_price": close, "candle_acc_trade_volume": 3}
    respx.get(f"{BASE_URL}/v1/candles/days").respond(json=[row("2026-10-22T09:00:00", 2), row("2026-10-21T09:00:00", 1)])
    rows = await ex.candles("KRW-BTC", "1d")
    assert [c.close for c in rows] == [Decimal(1), Decimal(2)]


async def test_candles_rejects_unknown_interval(ex):
    with pytest.raises(ExchangeError):
        await ex.candles("KRW-BTC", "7m")


@respx.mock
async def test_buy_market_signs_body(ex):
    route = respx.post(f"{BASE_URL}/v2/orders").respond(201, json={
        "order_id": "o-1", "market": "KRW-BTC", "side": "bid", "order_type": "price",
        "state": "wait", "created_at": "2026-10-22T09:00:00+09:00",
    })
    order = await ex.buy_market("KRW-BTC", Decimal(10000))
    assert order.order_id == "o-1"
    req = route.calls.last.request
    token = req.headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, "sk", algorithms=["HS256"])
    body = {"market": "KRW-BTC", "side": "bid", "order_type": "price", "price": "10000"}
    assert json.loads(req.content) == body
    assert claims["access_key"] == "ak"
    assert claims["query_hash"] == hashlib.sha512(urlencode(body).encode()).hexdigest()


@respx.mock
async def test_api_error_message(ex):
    respx.get(f"{BASE_URL}/v1/accounts").respond(401, json={"error": {"name": "invalid_access_key", "message": "잘못된 키"}})
    with pytest.raises(ExchangeError) as e:
        await ex.balances()
    assert e.value.status == 401 and "잘못된 키" in str(e.value)


async def test_private_call_without_keys():
    e = BithumbExchange()
    with pytest.raises(ExchangeError, match="API 키"):
        await e.balances()
    await e.close()


@respx.mock
async def test_buy_market_accepts_v1_style_response(ex):
    respx.post(f"{BASE_URL}/v2/orders").respond(201, json={"uuid": "o-2", "market": "KRW-BTC", "ord_type": "price"})
    order = await ex.buy_market("KRW-BTC", Decimal(5000))
    assert order.order_id == "o-2" and order.ord_type == "price"


@respx.mock
async def test_candle_history_pages_backwards(ex):
    def row(ts):
        return {"market": "KRW-BTC", "candle_date_time_kst": ts, "opening_price": 1, "high_price": 1,
                "low_price": 1, "trade_price": 1, "candle_acc_trade_volume": 1}

    def handler(request):
        to = request.url.params.get("to")
        if to is None:
            return httpx.Response(200, json=[row("2026-10-22T03:00:00"), row("2026-10-22T02:00:00")])
        if to == "2026-10-22 02:00:00":
            return httpx.Response(200, json=[row("2026-10-22T01:00:00")])
        return httpx.Response(200, json=[])

    respx.get(f"{BASE_URL}/v1/candles/minutes/60").mock(side_effect=handler)
    rows = await ex.candle_history("KRW-BTC", "1h", 10)
    assert [c.time_kst.hour for c in rows] == [1, 2, 3]
