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
