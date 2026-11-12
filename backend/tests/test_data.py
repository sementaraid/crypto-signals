import os
import time

import ccxt
import numpy as np
import pandas as pd
import pytest

from signals.data import (
    DataError,
    cache_path,
    demo_candles,
    download_candles,
    fetch_candles,
    load_csv,
    make_exchange,
    normalize,
    timeframe_to_timedelta,
)

from .conftest import FIXED_END, make_candles

H = 3_600_000  # one hour in ms


class FakeExchange:
    """Mimics the bits of a ccxt exchange that download_candles uses."""

    id = "fake"

    def __init__(self, n_candles=2500, now=1_000 * H + H // 2, page=1000, ignore_since=False, error=None):
        self.now, self.page, self.ignore_since, self.error = now, page, ignore_since, error
        start = now - n_candles * H - H // 2
        self.rows = [[start + i * H, 10.0 + i, 11.0 + i, 9.0 + i, 10.5 + i, 1.0] for i in range(n_candles + 1)]
        self.calls = 0

    def milliseconds(self):
        return self.now

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls += 1
        if self.error:
            raise self.error
        if self.ignore_since:
            return self.rows[:limit]
        out = [r for r in self.rows if r[0] >= since]
        return out[: min(limit, self.page)]


# ----------------------------------------------------------------------------- timeframes / normalize


@pytest.mark.parametrize("tf, td", [("15m", "15min"), ("1h", "1h"), ("4h", "4h"), ("1d", "1D"), ("1w", "7D"), ("30m", "30min")])
def test_timeframe_to_timedelta(tf, td):
    assert timeframe_to_timedelta(tf) == pd.Timedelta(td)


@pytest.mark.parametrize("tf", ["", "0h", "1y", "h", "4H", "1.5h", None, "1h; rm -rf"])
def test_timeframe_invalid(tf):
    with pytest.raises(DataError):
        timeframe_to_timedelta(tf)


def test_normalize_cleans():
    df = make_candles([10, 11, 12, 13])
    messy = pd.concat([df.iloc[[2, 0, 1]], df.iloc[[1]]])  # unsorted + duplicate
    messy.loc[df.index[3]] = [0.0, 1.0, 1.0, 1.0, 1.0]  # non-positive price
    out = normalize(messy)
    assert out.index.is_monotonic_increasing and out.index.is_unique
    assert len(out) == 3


def test_normalize_drops_inverted_and_nan_rows():
    df = make_candles([10, 11, 12])
    df.iloc[1, df.columns.get_loc("low")] = 99  # low > high
    df.iloc[2, df.columns.get_loc("close")] = np.nan
    assert len(normalize(df)) == 1


def test_normalize_errors():
    with pytest.raises(DataError, match="missing columns"):
        normalize(make_candles([1, 2]).drop(columns="volume"))
    with pytest.raises(DataError, match="no usable"):
        normalize(make_candles([1, 2]).iloc[:0])
    with pytest.raises(DataError, match="datetime index"):
        normalize(make_candles([1, 2]).reset_index(drop=True))


# ----------------------------------------------------------------------------- demo / csv


def test_demo_deterministic_and_valid():
    a = demo_candles("4h", 30, end=FIXED_END)
    b = demo_candles("4h", 30, end=FIXED_END)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 30 * 6 and a.index[-1] == FIXED_END
    assert (a.index.to_series().diff().dropna() == pd.Timedelta("4h")).all()
    assert (a.high >= a[["open", "close"]].max(axis=1)).all()
    assert (a.low <= a[["open", "close"]].min(axis=1)).all()
    assert not demo_candles("4h", 30, seed=8, end=FIXED_END).equals(a)


def test_demo_rejects_bad_timeframes():
    with pytest.raises(DataError):
        demo_candles("7x", 30)
    with pytest.raises(DataError, match="too short"):
        demo_candles("1w", 10)


@pytest.mark.parametrize(
    "ts, col",
    [
        ([1767225600000, 1767229200000], "timestamp"),  # ms
        ([1767225600, 1767229200], "time"),  # seconds
        (["2026-01-01 00:00", "2026-01-01 01:00"], "Date"),  # strings, capitalised header
    ],
)
def test_load_csv_time_formats(tmp_path, ts, col):
    f = tmp_path / "c.csv"
    cols = {col: ts, "Open": [1, 2], "High": [2, 3], "Low": [0.5, 1], "Close": [1.5, 2.5], "Volume": [1, 1]}
    pd.DataFrame(cols).to_csv(f, index=False)
    df = load_csv(f)
    assert list(df.index) == [pd.Timestamp("2026-01-01 00:00"), pd.Timestamp("2026-01-01 01:00")]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_load_csv_errors(tmp_path):
    with pytest.raises(DataError, match="cannot read"):
        load_csv(tmp_path / "missing.csv")
    f = tmp_path / "notime.csv"
    f.write_text("open,high,low,close,volume\n1,2,0.5,1.5,1\n")
    with pytest.raises(DataError, match="time column"):
        load_csv(f)


# ----------------------------------------------------------------------------- download


def test_download_paginates_and_drops_forming_candle():
    ex = FakeExchange(n_candles=2500, page=1000)
    df = download_candles(ex, "BTC/USDT", "1h", days=100)
    assert ex.calls >= 3
    assert df.index.is_unique and df.index.is_monotonic_increasing
    last_open_ms = df.index[-1].value // 10**6
    assert last_open_ms + H <= ex.now  # every candle is closed
    assert last_open_ms + 2 * H > ex.now  # ...and the newest closed one is kept
    # 100 days = 2400 hours; the candle that opened before `since` is not requested
    assert 100 * 24 - 1 <= len(df) <= 100 * 24


def test_download_stops_when_exchange_ignores_since():
    ex = FakeExchange(n_candles=50, ignore_since=True)
    df = download_candles(ex, "BTC/USDT", "1h", days=1000)
    assert ex.calls <= 3 and len(df) > 0


@pytest.mark.parametrize(
    "err, msg",
    [
        (ccxt.BadSymbol("x"), "not available"),
        (ccxt.NetworkError("down"), "could not download"),
        (ccxt.ExchangeNotAvailable("451"), "could not download"),
    ],
)
def test_download_errors(err, msg):
    with pytest.raises(DataError, match=msg):
        download_candles(FakeExchange(error=err), "BTC/USDT", "1h", 10)


def test_download_empty():
    ex = FakeExchange(n_candles=0)
    ex.rows = []
    with pytest.raises(DataError, match="no candles"):
        download_candles(ex, "BTC/USDT", "1h", 10)


def test_make_exchange():
    assert make_exchange("binance").id == "binance"
    with pytest.raises(DataError, match="unknown exchange"):
        make_exchange("../../etc")


# ----------------------------------------------------------------------------- cache


def test_cache_hit_stale_and_corrupt(tmp_path):
    ex = FakeExchange(n_candles=100)
    a = fetch_candles("fake", "BTC/USDT", "1h", 2, cache_dir=tmp_path, client=ex)
    calls = ex.calls
    b = fetch_candles("fake", "BTC/USDT", "1h", 2, cache_dir=tmp_path, client=ex)
    assert ex.calls == calls  # served from cache
    pd.testing.assert_frame_equal(a, b, check_freq=False)

    path = cache_path(tmp_path, "fake", "BTC/USDT", "1h", 2)
    old = time.time() - 7200
    os.utime(path, (old, old))
    fetch_candles("fake", "BTC/USDT", "1h", 2, cache_dir=tmp_path, client=ex)
    assert ex.calls > calls  # stale -> downloaded again

    path.write_text("garbage,,,\n")
    calls = ex.calls
    fetch_candles("fake", "BTC/USDT", "1h", 2, cache_dir=tmp_path, client=ex)
    assert ex.calls > calls  # corrupt -> downloaded again
    assert not list(tmp_path.glob("*.tmp"))  # atomic write leaves no temp files


def test_cache_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "env-cache"))
    fetch_candles("fake", "BTC/USDT", "1h", 2, client=FakeExchange(n_candles=100))
    assert list((tmp_path / "env-cache").glob("*.csv"))


def test_cache_path_is_sanitised(tmp_path):
    p = cache_path(tmp_path, "binance", "../../x/Y", "1h", 5)
    assert p.parent == tmp_path and "/" not in p.name


def test_read_only_cache_does_not_break(tmp_path, monkeypatch):
    import signals.data as data

    def boom(*a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(data, "_write_atomic", boom)
    df = fetch_candles("fake", "BTC/USDT", "1h", 2, cache_dir=tmp_path, client=FakeExchange(n_candles=100))
    assert len(df) > 0
