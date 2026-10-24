"""API 서버. 화면(웹, 앱)이 이 서버를 통해 시세와 전략 설정을 다룬다.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .exchanges.base import ExchangeError
from .exchanges.bithumb import CANDLE_PATHS, BithumbExchange
from .store import DcaStore
from .strategies.dca import KST, WeeklyDcaConfig, next_run, position_from_runs, take_profit_price

DEFAULT_MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.exchange = BithumbExchange(config.BITHUMB_ACCESS_KEY, config.BITHUMB_SECRET_KEY)
    app.state.dca_store = DcaStore(config.DATA_DIR / "dca.json")
    yield
    await app.state.exchange.close()


app = FastAPI(title="비트코인 투자 프로그램 API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ExchangeError)
async def exchange_error_handler(request, exc: ExchangeError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/api/health")
async def health():
    return {"ok": True, "time_kst": datetime.now(KST).isoformat()}


@app.get("/api/markets")
async def markets():
    rows = await app.state.exchange.markets("KRW")
    return [{"code": m.code, "korean_name": m.korean_name, "english_name": m.english_name} for m in rows]


@app.get("/api/tickers")
async def tickers(markets: str = Query(",".join(DEFAULT_MARKETS), description="쉼표로 구분한 마켓 코드")):
    codes = [m.strip() for m in markets.split(",") if m.strip()]
    return await app.state.exchange.tickers(codes)


@app.get("/api/candles")
async def candles(market: str = "KRW-BTC", interval: str = "1d", count: int = Query(200, ge=1, le=200)):
    if interval not in CANDLE_PATHS:
        raise HTTPException(400, f"interval은 {', '.join(CANDLE_PATHS)} 중 하나여야 합니다.")
    return await app.state.exchange.candles(market, interval, count)


def _dca_view(state) -> dict:
    cfg = state.config
    return {
        "config": cfg,
        "summary": cfg.describe(),
        "next_run": next_run(cfg, datetime.now(KST)) if cfg.enabled else None,
        "take_profit_price": take_profit_price(cfg, state.position()),
        "total_spent": state.total_spent,
        "runs": list(reversed(state.runs[-20:])),
    }


@app.get("/api/strategies/dca")
def get_dca():
    return _dca_view(app.state.dca_store.load())


@app.put("/api/strategies/dca")
def put_dca(cfg: WeeklyDcaConfig):
    if cfg.mode == "live" and not (config.BITHUMB_ACCESS_KEY and config.BITHUMB_SECRET_KEY):
        raise HTTPException(400, "실거래 모드는 빗썸 API 키를 등록한 뒤에 켤 수 있습니다.")
    with app.state.dca_store.edit() as state:
        state.config = cfg
    return _dca_view(state)


@app.get("/api/analysis")
async def analysis():
    """수익 분석: 실행 기록과 현재가로 손익, 수익률, 수수료를 계산한다.

    평가 금액은 지금 전부 팔 때의 매도 수수료까지 뺀 금액이다.
    """
    state = app.state.dca_store.load()
    cfg = state.config
    pos = state.position()
    price = None
    if pos.volume > 0:
        [ticker] = await app.state.exchange.tickers([cfg.market])
        price = ticker.price
    value = pos.volume * price * (1 - cfg.fee_rate) if price is not None else Decimal(0)
    unrealized = value - pos.cost_krw
    total_pnl = pos.realized_pnl_krw + unrealized
    trades = sorted((r for r in state.runs if r.ok and r.volume > 0), key=lambda r: r.at)

    # 거래 시점마다 누적 투자금과 그 시점 가격 기준 평가손익을 찍는다
    curve = []
    for i, r in enumerate(trades, 1):
        p = position_from_runs(trades[:i])
        mark = p.volume * r.price * (1 - cfg.fee_rate) if r.price else Decimal(0)
        curve.append({"at": r.at, "invested": p.invested_krw, "pnl": p.realized_pnl_krw + mark - p.cost_krw})

    return {
        "market": cfg.market,
        "mode": cfg.mode,
        "fee_rate": cfg.fee_rate,
        "price": price,
        "volume": pos.volume,
        "avg_cost": pos.avg_cost,
        "invested_krw": pos.invested_krw,
        "cost_krw": pos.cost_krw,
        "value_krw": value,
        "realized_pnl_krw": pos.realized_pnl_krw,
        "unrealized_pnl_krw": unrealized,
        "total_pnl_krw": total_pnl,
        "return_pct": total_pnl / pos.invested_krw * 100 if pos.invested_krw > 0 else Decimal(0),
        "fees_krw": pos.fees_krw,
        "buy_count": sum(1 for r in trades if r.side == "buy"),
        "sell_count": sum(1 for r in trades if r.side == "sell"),
        "curve": curve,
        "trades": list(reversed(trades)),
    }
