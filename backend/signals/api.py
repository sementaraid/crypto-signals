"""Flask API. Also serves the built Vite dashboard (STATIC_DIR)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import __version__
from .analysis import compare_strategies, latest_signal, prepare, run_backtest
from .data import DataError, demo_candles, fetch_candles
from .params import Params, ValidationError, parse_params
from .serialize import candle_points, series_points, to_jsonable
from .strategies import STRATEGIES, describe

log = logging.getLogger(__name__)

TIMEFRAMES = ["15m", "1h", "4h", "1d"]
EXCHANGES = ["binance", "indodax", "tokocrypto", "bybit", "okx", "kucoin"]


def default_loader(p: Params, timeframe: str):
    if p.demo:
        return demo_candles(timeframe, p.days)
    return fetch_candles(p.exchange, p.symbol, timeframe, p.days)


def create_app(config: dict | None = None) -> Flask:
    """App factory. Config keys: STATIC_DIR, CANDLE_LOADER (callable(params, timeframe) -> OHLCV frame)."""
    app = Flask(__name__, static_folder=None)
    app.config.update(
        STATIC_DIR=os.environ.get("STATIC_DIR", str(Path(__file__).resolve().parent.parent / "static")),
        CANDLE_LOADER=default_loader,
        JSON_SORT_KEYS=False,
    )
    app.config.update(config or {})

    def params() -> Params:
        return parse_params(request.args)

    def load(p: Params, timeframe: str):
        return app.config["CANDLE_LOADER"](p, timeframe)

    # ------------------------------------------------------------------ errors
    @app.errorhandler(ValidationError)
    def _validation(e: ValidationError):
        return jsonify(error=str(e), fields=e.errors), 400

    @app.errorhandler(DataError)
    def _data(e: DataError):
        return jsonify(error=str(e)), 422

    @app.errorhandler(HTTPException)
    def _http(e: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=e.description), e.code
        return e

    @app.errorhandler(Exception)
    def _unexpected(e: Exception):
        log.exception("unhandled error on %s", request.full_path)
        return jsonify(error="internal server error"), 500

    # ------------------------------------------------------------------ API
    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/meta")
    def meta():
        return {
            "strategies": [{"id": k, "description": describe(k)} for k in STRATEGIES],
            "timeframes": TIMEFRAMES,
            "exchanges": EXCHANGES,
        }

    @app.get("/api/backtest")
    def api_backtest():
        p = params()
        d = prepare(load(p, p.timeframe))
        eq, tr, st = run_backtest(d, p.strategy, p.capital, p.to_idr, p.fee, p.stop_atr, p.tp_atr)
        trades = [{**r, "pnl_idr": r["pnl"] * p.to_idr} for r in tr.to_dict("records")]
        return jsonify(
            to_jsonable(
                {
                    "params": p.public(),
                    "stats": st,
                    "candles": candle_points(d),
                    "lines": {k: series_points(d[k]) for k in ("ema21", "ema50", "ema200")},
                    "equity_idr": series_points(eq, p.to_idr),
                    "trades": trades,
                    "signal": latest_signal(d, p.strategy, p.stop_atr, p.tp_atr),
                }
            )
        )

    @app.get("/api/compare")
    def api_compare():
        p = params()
        res = compare_strategies(lambda tf: load(p, tf), p.timeframes, p.capital, p.to_idr, p.fee, p.stop_atr, p.tp_atr)
        return jsonify(to_jsonable({"params": p.public(), "rows": res.to_dict("records")}))

    @app.get("/api/signal")
    def api_signal():
        p = params()
        d = prepare(load(p, p.timeframe))
        return jsonify(to_jsonable(latest_signal(d, p.strategy, p.stop_atr, p.tp_atr)))

    # ------------------------------------------------------------------ dashboard
    @app.get("/")
    @app.get("/<path:path>")
    def dashboard(path: str = "index.html"):
        if path.startswith("api/"):
            return jsonify(error="not found"), 404
        static = Path(app.config["STATIC_DIR"])
        if not (static / path).is_file():
            path = "index.html"  # client-side routes fall back to the SPA
        if not (static / path).is_file():
            return "Dashboard not built. Run `npm run build` in frontend/ or use Docker.", 404
        return send_from_directory(static, path)

    return app
