"""Flask API around trader.py. Also serves the built Vite dashboard from ./static."""
import math
import os

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory

import trader

STATIC = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "static"))
app = Flask(__name__, static_folder=None)


# ----------------------------------------------------------------------------- helpers

class BadRequest(Exception):
    pass


def clean(x):
    """Make numpy/pandas values JSON-safe (NaN/inf -> None, timestamps -> unix seconds)."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, pd.Timestamp):
        return int(x.timestamp())
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(x) else float(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def params():
    q = request.args

    def num(name, default):
        try:
            return float(q.get(name, default))
        except ValueError:
            raise BadRequest(f"'{name}' must be a number")

    p = {
        "exchange": q.get("exchange", "binance").strip().lower(),
        "symbol": q.get("symbol", "BTC/USDT").strip().upper(),
        "timeframe": q.get("timeframe", "4h"),
        "timeframes": [t for t in q.get("timeframes", "1h,4h,1d").split(",") if t],
        "strategy": q.get("strategy", "combo"),
        "days": int(num("days", 730)),
        "capital_idr": num("capital_idr", 10_000_000),
        "usd_idr": num("usd_idr", 16_500),
        "fee": num("fee", 0.001),
        "stop_atr": num("stop_atr", 2.0),
        "tp_atr": num("tp_atr", 4.0),
        "demo": q.get("demo", "false").lower() in ("1", "true", "yes"),
    }
    if p["strategy"] not in trader.STRATEGIES:
        raise BadRequest(f"unknown strategy '{p['strategy']}'")
    if "/" not in p["symbol"]:
        raise BadRequest("symbol must look like BTC/USDT")
    if not 10 <= p["days"] <= 3650:
        raise BadRequest("days must be between 10 and 3650")
    if p["capital_idr"] <= 0:
        raise BadRequest("capital must be positive")
    p["to_idr"] = 1.0 if p["symbol"].split("/")[1] == "IDR" else p["usd_idr"]
    p["capital"] = p["capital_idr"] / p["to_idr"]
    return p


def load(p, timeframe):
    if p["demo"]:
        return trader.demo_candles(timeframe, p["days"])
    try:
        return trader.fetch_candles(p["exchange"], p["symbol"], timeframe, p["days"])
    except SystemExit as e:  # trader raises SystemExit when nothing comes back
        raise BadRequest(str(e))
    except AttributeError:
        raise BadRequest(f"unknown exchange '{p['exchange']}'")
    except Exception as e:  # ccxt network / symbol errors
        raise BadRequest(f"could not download candles from {p['exchange']}: {type(e).__name__}: {str(e)[:200]}")


@app.errorhandler(BadRequest)
def bad_request(e):
    return jsonify(error=str(e)), 400


# ----------------------------------------------------------------------------- API

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    return {
        "strategies": [{"id": k, "description": (f.__doc__ or "").strip()} for k, f in trader.STRATEGIES.items()],
        "timeframes": ["15m", "1h", "4h", "1d"],
        "exchanges": ["binance", "indodax", "tokocrypto", "bybit", "okx", "kucoin"],
    }


@app.get("/api/backtest")
def api_backtest():
    p = params()
    d = trader.add_indicators(load(p, p["timeframe"])).dropna()
    if len(d) < 50:
        raise BadRequest("not enough candles after indicator warm-up; increase days")
    sig = trader.STRATEGIES[p["strategy"]](d)
    eq, tr = trader.backtest(d, sig, p["capital"], p["fee"], p["stop_atr"], p["tp_atr"])
    st = trader.stats(eq, tr, d.close, p["capital"], p["to_idr"])
    t = [int(ts.timestamp()) for ts in d.index]
    line = lambda col: [{"time": a, "value": float(v)} for a, v in zip(t, d[col].values)]
    trades = tr.to_dict("records") if len(tr) else []
    return jsonify(clean({
        "params": {k: v for k, v in p.items() if k not in ("capital",)},
        "stats": st,
        "candles": [{"time": a, "open": o, "high": h, "low": l, "close": c}
                    for a, o, h, l, c in zip(t, d.open.values, d.high.values, d.low.values, d.close.values)],
        "lines": {"ema21": line("ema21"), "ema50": line("ema50"), "ema200": line("ema200")},
        "equity_idr": [{"time": a, "value": float(v) * p["to_idr"]} for a, v in zip(t, eq.values)],
        "trades": [{**r, "pnl_idr": r["pnl"] * p["to_idr"]} for r in trades],
        "signal": trader.latest_signal(d, p["strategy"], p["stop_atr"], p["tp_atr"]),
    }))


@app.get("/api/compare")
def api_compare():
    p = params()
    res = trader.compare_strategies(lambda tf: load(p, tf), p["timeframes"], p["capital"], p["to_idr"],
                                    p["fee"], p["stop_atr"], p["tp_atr"])
    return jsonify(clean({"rows": res.to_dict("records")}))


@app.get("/api/signal")
def api_signal():
    p = params()
    d = trader.add_indicators(load(p, p["timeframe"]))
    return jsonify(clean(trader.latest_signal(d, p["strategy"], p["stop_atr"], p["tp_atr"])))


# ----------------------------------------------------------------------------- dashboard

@app.get("/")
@app.get("/<path:path>")
def dashboard(path="index.html"):
    if path.startswith("api/"):
        return jsonify(error="not found"), 404
    if not os.path.isfile(os.path.join(STATIC, path)):
        path = "index.html"
    if not os.path.isfile(os.path.join(STATIC, path)):
        return "Dashboard not built. Run `npm run build` in frontend/ or use Docker.", 404
    return send_from_directory(STATIC, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
