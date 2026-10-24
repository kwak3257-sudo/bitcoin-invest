from fastapi.testclient import TestClient

from app import config


def test_dca_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/strategies/dca")
        assert r.status_code == 200 and r.json()["config"]["enabled"] is False

        body = {"enabled": True, "weekday": 4, "run_time": "21:30", "krw_amount": "50000", "market": "KRW-ETH"}
        r = client.put("/api/strategies/dca", json=body)
        assert r.status_code == 200
        assert r.json()["summary"] == "매주 금요일 21:30에 KRW-ETH 50,000원 매수"
        assert r.json()["next_run"] is not None
        assert client.get("/api/strategies/dca").json()["config"]["market"] == "KRW-ETH"

        r = client.put("/api/strategies/dca", json={**body, "mode": "live"})
        assert r.status_code == 400  # 키 없이 실거래 불가

        r = client.put("/api/strategies/dca", json={**body, "krw_amount": "100"})
        assert r.status_code == 422


def test_analysis_includes_fees(tmp_path, monkeypatch):
    from datetime import datetime
    from decimal import Decimal

    from app.exchanges.base import Ticker
    from app.store import DcaStore
    from app.strategies.dca import KST, DcaRun

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from app.main import app

    class Fake:
        async def tickers(self, markets):
            return [Ticker(markets[0], Decimal(120), Decimal(0), Decimal(0), Decimal(0), Decimal(0),
                           Decimal(0), Decimal(0), datetime.now(KST))]

        async def close(self):
            pass

    with DcaStore(tmp_path / "dca.json").edit() as state:
        state.runs.append(DcaRun(at=datetime(2026, 10, 5, 9, tzinfo=KST), market="KRW-BTC", krw_amount=Decimal(10000),
                                 mode="paper", price=Decimal(100), volume=Decimal(100), fee_krw=Decimal(25)))

    with TestClient(app) as client:
        app.state.exchange = Fake()
        r = client.get("/api/analysis").json()
    # 평가 = 100개 × 120원 × (1 - 0.0025) = 11970, 원가 10025
    assert Decimal(r["value_krw"]) == Decimal("11970")
    assert Decimal(r["total_pnl_krw"]) == Decimal("1945")
    assert Decimal(r["fees_krw"]) == Decimal(25)
    assert r["buy_count"] == 1 and len(r["curve"]) == 1


def test_trader_settings_and_emergency_stop(tmp_path, monkeypatch):
    from datetime import datetime
    from decimal import Decimal

    from app.exchanges.base import Ticker
    from app.store import TraderStore
    from app.strategies.dca import KST
    from app.strategies.trader import OpenPosition

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from app.main import app

    class Fake:
        async def tickers(self, markets):
            return [Ticker(markets[0], Decimal(110), *(Decimal(0),) * 6, datetime.now(KST))]

        async def close(self):
            pass

    with TestClient(app) as client:
        app.state.exchange = Fake()
        r = client.get("/api/strategies/trader")
        assert r.status_code == 200
        v = r.json()
        assert v["config"]["enabled"] is False and v["config"]["mode"] == "paper"
        assert Decimal(v["daily_loss_limit_krw"]) == 3000

        cfg = {**v["config"], "enabled": True}
        assert client.put("/api/strategies/trader", json=cfg).json()["config"]["enabled"] is True
        assert client.put("/api/strategies/trader", json={**cfg, "mode": "live"}).status_code == 400

        store = TraderStore(tmp_path / "trader.json")
        with store.edit() as s:
            s.position = OpenPosition(entry_at=datetime.now(KST), entry_price=Decimal(100), volume=Decimal(100),
                                      cost_krw=Decimal(10025))
        v = client.get("/api/strategies/trader").json()
        # 평가 금액은 매도 수수료를 뺀다: 100 * 110 * 0.9975
        assert Decimal(v["position_value_krw"]) == Decimal("10972.5")
        assert client.put("/api/strategies/trader", json={**cfg, "market": "KRW-ETH"}).status_code == 400

        v = client.post("/api/strategies/trader/stop").json()
        assert v["stop_requested"] is True  # 보유 중이면 엔진이 팔고 끈다
