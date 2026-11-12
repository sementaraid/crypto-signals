import numpy as np
import pandas as pd
import pytest

from signals.api import create_app
from signals.data import demo_candles

FIXED_END = pd.Timestamp("2026-01-01")


def make_candles(close, open_=None, high=None, low=None, freq="1h", start="2026-01-01"):
    """Build an OHLCV frame from lists. Missing open/high/low default to sensible values around close."""
    close = np.asarray(close, dtype=float)
    open_ = np.asarray(open_ if open_ is not None else np.r_[close[0], close[:-1]], dtype=float)
    high = np.asarray(high if high is not None else np.maximum(open_, close), dtype=float)
    low = np.asarray(low if low is not None else np.minimum(open_, close), dtype=float)
    idx = pd.date_range(start, periods=len(close), freq=freq, name="time")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)


def with_atr(df, atr=1.0):
    d = df.copy()
    d["atr"] = atr
    return d


def signal_at(df, buys=(), sells=()):
    s = pd.Series(0, index=df.index)
    for i in buys:
        s.iloc[i] = 1
    for i in sells:
        s.iloc[i] = -1
    return s


@pytest.fixture
def demo():
    """Deterministic demo candles (fixed end date)."""
    return lambda timeframe="4h", days=730, seed=7: demo_candles(timeframe, days, seed=seed, end=FIXED_END)


@pytest.fixture
def static_dir(tmp_path):
    d = tmp_path / "static"
    d.mkdir()
    (d / "index.html").write_text("<!doctype html><title>Crypto Signals</title>")
    (d / "app.js").write_text("console.log('hi')")
    (tmp_path / "secret.txt").write_text("do not serve")
    return d


@pytest.fixture
def loader_calls():
    return []


@pytest.fixture
def app(static_dir, loader_calls):
    def loader(p, timeframe):
        loader_calls.append((p, timeframe))
        return demo_candles(timeframe, p.days, end=FIXED_END)

    return create_app({"TESTING": True, "STATIC_DIR": str(static_dir), "CANDLE_LOADER": loader})


@pytest.fixture
def client(app):
    return app.test_client()
