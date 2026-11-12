import json

import pytest

from signals.api import create_app
from signals.data import DataError
from signals.strategies import STRATEGIES


def get(client, path, **params):
    r = client.get(path, query_string=params)
    return r, r.get_json(silent=True)


def assert_strict_json(response):
    """Browsers reject NaN/Infinity in JSON; make sure we never send them."""
    json.loads(response.data, parse_constant=lambda c: pytest.fail(f"non-standard JSON constant {c}"))


def test_health_and_meta(client):
    r, j = get(client, "/api/health")
    assert r.status_code == 200 and j["ok"] is True and j["version"]
    r, j = get(client, "/api/meta")
    assert [s["id"] for s in j["strategies"]] == list(STRATEGIES)
    assert all(s["description"] for s in j["strategies"])
    assert "4h" in j["timeframes"] and "binance" in j["exchanges"]


def test_backtest_response(client):
    r, j = get(client, "/api/backtest", strategy="ema_cross", timeframe="4h", days=365)
    assert r.status_code == 200, j
    assert_strict_json(r)
    assert set(j) == {"params", "stats", "candles", "lines", "equity_idr", "trades", "signal"}
    times = [c["time"] for c in j["candles"]]
    assert times == sorted(set(times))  # strictly increasing, unique
    assert [p["time"] for p in j["equity_idr"]] == times
    assert all(len(j["lines"][k]) == len(times) for k in ("ema21", "ema50", "ema200"))
    tset = set(times)
    for t in j["trades"]:
        assert t["entry_time"] in tset and t["exit_time"] in tset  # markers land on candles
        assert t["pnl_idr"] == pytest.approx(t["pnl"] * 16_500)
    assert j["stats"]["trades"] == len(j["trades"])
    assert j["signal"]["action"] in {"BUY", "SELL", "HOLD"} and j["signal"]["time"] == times[-1]
    assert j["params"]["strategy"] == "ema_cross" and j["params"]["to_idr"] == 16_500


def test_backtest_idr_pair_values_in_rupiah(client):
    _, j = get(client, "/api/backtest", symbol="BTC/IDR", capital_idr=20_000_000, days=365)
    assert j["params"]["to_idr"] == 1.0
    assert j["equity_idr"][0]["value"] == pytest.approx(20_000_000, rel=0.2)


def test_compare(client):
    r, j = get(client, "/api/compare", timeframes="4h,1d", days=365)
    assert r.status_code == 200
    assert_strict_json(r)
    assert len(j["rows"]) == 2 * len(STRATEGIES)
    assert j["params"]["timeframes"] == ["4h", "1d"]


def test_signal(client):
    r, j = get(client, "/api/signal", strategy="combo", days=365)
    assert r.status_code == 200 and j["action"] in {"BUY", "SELL", "HOLD"}
    assert isinstance(j["time"], int)


def test_loader_receives_params(client, loader_calls):
    get(client, "/api/backtest", exchange="indodax", symbol="eth/idr", timeframe="1d", days=400)
    p, tf = loader_calls[-1]
    assert (p.exchange, p.symbol, p.days, tf) == ("indodax", "ETH/IDR", 400, "1d")


def test_validation_error(client):
    r, j = get(client, "/api/backtest", fee="-1", strategy="nope")
    assert r.status_code == 400
    assert set(j["fields"]) == {"fee", "strategy"} and "fee" in j["error"]


def test_data_error_is_422(static_dir):
    def loader(p, tf):
        raise DataError("could not download candles from binance: NetworkError")

    c = create_app({"TESTING": True, "STATIC_DIR": str(static_dir), "CANDLE_LOADER": loader}).test_client()
    for path in ("/api/backtest", "/api/compare", "/api/signal"):
        r, j = get(c, path)
        assert r.status_code == 422 and "NetworkError" in j["error"]


def test_too_little_history_is_422(client):
    r, j = get(client, "/api/backtest", timeframe="1d", days=100)
    assert r.status_code == 422 and "warm-up" in j["error"]


def test_unexpected_error_is_json_500(static_dir):
    def loader(p, tf):
        raise RuntimeError("secret internals")

    c = create_app({"STATIC_DIR": str(static_dir), "CANDLE_LOADER": loader}).test_client()
    r, j = get(c, "/api/backtest")
    assert r.status_code == 500 and j == {"error": "internal server error"}  # no internals leaked


def test_api_404_and_405_are_json(client):
    r, j = get(client, "/api/nope")
    assert r.status_code == 404 and "error" in j
    r = client.post("/api/health")
    assert r.status_code == 405 and "error" in r.get_json()


def test_dashboard_static_and_spa_fallback(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Crypto Signals" in r.data
    assert client.get("/app.js").data == b"console.log('hi')"
    assert b"Crypto Signals" in client.get("/some/client/route").data


def test_dashboard_does_not_escape_static_dir(client):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt"):
        r = client.get(path)
        assert b"do not serve" not in r.data


def test_dashboard_not_built(tmp_path):
    c = create_app({"STATIC_DIR": str(tmp_path / "nothing")}).test_client()
    r = c.get("/")
    assert r.status_code == 404 and b"not built" in r.data


def test_demo_flag_uses_default_loader_offline(static_dir):
    c = create_app({"STATIC_DIR": str(static_dir)}).test_client()  # real default loader
    r, j = get(c, "/api/signal", demo="true", timeframe="1d", days=400)
    assert r.status_code == 200 and j["action"] in {"BUY", "SELL", "HOLD"}
