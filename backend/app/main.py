"""API 서버. 화면(웹, 앱)이 이 서버를 통해 시세와 전략 설정을 다룬다.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import config, notify
from .confirm import ConfirmGate
from .backtest import BacktestCosts, optimize, run_backtest
from .exchanges.base import ExchangeError
from .exchanges.bithumb import CANDLE_PATHS, BithumbExchange
from .store import DcaStore, TraderStore
from .strategies.dca import KST, WeeklyDcaConfig, next_run, position_from_runs, take_profit_price
from .strategies.short_term import ShortTermParams
from .strategies.trader import TraderConfig, daily_loss_limit_krw, position_value, today_pnl

DEFAULT_MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.exchange = BithumbExchange(config.BITHUMB_ACCESS_KEY, config.BITHUMB_SECRET_KEY)
    app.state.dca_store = DcaStore(config.DATA_DIR / "dca.json")
    app.state.trader_store = TraderStore(config.DATA_DIR / "trader.json")
    app.state.confirm = ConfirmGate()
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


def _needs_code(new, old) -> bool:
    """실거래로 켜져 있는 상태에서 설정이 바뀌면 인증이 필요하다. 끄는 것은 언제나 바로 된다."""
    return new.mode == "live" and new.enabled and new != old


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
async def put_dca(cfg: WeeklyDcaConfig, code: str | None = None):
    if cfg.mode == "live" and not (config.BITHUMB_ACCESS_KEY and config.BITHUMB_SECRET_KEY):
        raise HTTPException(400, "실거래 모드는 빗썸 API 키를 등록한 뒤에 켤 수 있습니다.")
    if _needs_code(cfg, app.state.dca_store.load().config):
        await app.state.confirm.require("dca", f"정기 매수 실거래 설정 저장 ({cfg.describe()})",
                                        cfg.model_dump_json(), code)
    with app.state.dca_store.edit() as state:
        state.config = cfg
    await notify.send(f"정기 매수 설정이 저장됐습니다: {'켜짐' if cfg.enabled else '꺼짐'}, "
                      f"{'실거래' if cfg.mode == 'live' else '모의투자'}, {cfg.describe()}")
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


class BacktestRequest(BaseModel):
    market: str = "KRW-BTC"
    interval: str = "1h"
    candles: int = Field(1000, ge=50, le=3000, description="거슬러 올라갈 캔들 수")
    params: ShortTermParams = ShortTermParams()
    costs: BacktestCosts = BacktestCosts()


@app.post("/api/backtest")
async def backtest(req: BacktestRequest):
    if req.interval not in CANDLE_PATHS:
        raise HTTPException(400, f"interval은 {', '.join(CANDLE_PATHS)} 중 하나여야 합니다.")
    candles = await app.state.exchange.candle_history(req.market, req.interval, req.candles)
    try:
        result = run_backtest(candles, req.params, req.costs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "market": req.market,
        "interval": req.interval,
        "from": candles[0].time_kst,
        "to": candles[-1].time_kst,
        "candle_count": len(candles),
        **result.__dict__,
        "trades": [t.__dict__ for t in reversed(result.trades)],
    }


class OptimizeRequest(BaseModel):
    market: str = "KRW-BTC"
    interval: str = "4h"
    candles: int = Field(3000, ge=300, le=3000)
    strategy: Literal["ma_cross", "breakout"] = "ma_cross"
    costs: BacktestCosts = BacktestCosts()


@app.post("/api/backtest/optimize")
async def backtest_optimize(req: OptimizeRequest):
    if req.interval not in CANDLE_PATHS:
        raise HTTPException(400, f"interval은 {', '.join(CANDLE_PATHS)} 중 하나여야 합니다.")
    candles = await app.state.exchange.candle_history(req.market, req.interval, req.candles)
    try:
        # 수백 번 계산하므로 다른 요청을 막지 않게 별도 스레드에서 돌린다
        return await asyncio.to_thread(optimize, candles, req.costs, req.strategy)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


async def _trader_view(state) -> dict:
    cfg = state.config
    price = None
    try:
        [ticker] = await app.state.exchange.tickers([cfg.market])
        price = ticker.price
    except ExchangeError:
        pass  # 시세를 못 받아도 설정과 기록은 보여 준다
    now = datetime.now(KST)
    value = position_value(state, price) if price is not None else None
    equity = state.cash_krw + (value or Decimal(0))
    # 기록 순서대로 누적 확정 손익
    curve, total = [], Decimal(0)
    for t in state.trades:
        if t.ok and t.pnl_krw is not None:
            total += t.pnl_krw
            curve.append({"at": t.at, "pnl": total})
    sells = [t for t in state.trades if t.ok and t.pnl_krw is not None]
    return {
        "config": cfg,
        "keys_ready": bool(config.BITHUMB_ACCESS_KEY and config.BITHUMB_SECRET_KEY),
        "telegram_ready": notify.enabled(),
        "price": price,
        "position": state.position,
        "position_value_krw": value,
        "cash_krw": state.cash_krw,
        "equity_krw": equity,
        "realized_pnl_krw": state.realized_pnl,
        "total_pnl_krw": equity - cfg.budget_krw,
        "return_pct": (equity / cfg.budget_krw - 1) * 100,
        "today_pnl_krw": today_pnl(state, price, now),
        "daily_loss_limit_krw": daily_loss_limit_krw(cfg),
        "fees_krw": state.fees_krw,
        "trade_count": len(sells),
        "win_rate_pct": sum(1 for t in sells if t.pnl_krw > 0) / len(sells) * 100 if sells else 0,
        "halted_until": state.halted_until,
        "halt_reason": state.halt_reason,
        "stop_requested": state.stop_requested,
        "curve": curve,
        "trades": list(reversed(state.trades[-100:])),
    }


@app.get("/api/strategies/trader")
async def get_trader():
    return await _trader_view(app.state.trader_store.load())


@app.put("/api/strategies/trader")
async def put_trader(cfg: TraderConfig, code: str | None = None):
    if cfg.mode == "live" and not (config.BITHUMB_ACCESS_KEY and config.BITHUMB_SECRET_KEY):
        raise HTTPException(400, "실거래 모드는 빗썸 API 키를 등록한 뒤에 켤 수 있습니다.")
    if _needs_code(cfg, app.state.trader_store.load().config):
        await app.state.confirm.require(
            "trader", f"단기 매매 실거래 설정 저장 ({cfg.market}, 운용 금액 {cfg.budget_krw:,.0f}원)",
            cfg.model_dump_json(), code,
        )
    with app.state.trader_store.edit() as state:
        if state.position is not None and (cfg.market != state.config.market or cfg.mode != state.config.mode):
            raise HTTPException(400, "보유 중에는 코인이나 모드를 바꿀 수 없습니다. 긴급 정지로 먼저 정리하세요.")
        if cfg.enabled and not state.config.enabled:
            state.halted_until = state.halt_reason = None
        state.config = cfg
    await notify.send(f"단기 매매 설정이 저장됐습니다: {'켜짐' if cfg.enabled else '꺼짐'}, "
                      f"{'실거래' if cfg.mode == 'live' else '모의투자'}, {cfg.market}, 운용 금액 {cfg.budget_krw:,.0f}원")
    return await _trader_view(state)


@app.post("/api/strategies/trader/stop")
async def stop_trader():
    """긴급 정지: 엔진이 다음 확인 때(최대 수십 초) 보유분을 시장가로 팔고 전략을 끈다."""
    with app.state.trader_store.edit() as state:
        if state.position is None:
            state.config = state.config.model_copy(update={"enabled": False})
        else:
            state.stop_requested = True
    return await _trader_view(state)
