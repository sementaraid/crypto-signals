"""Loading OHLCV candles: exchange download (ccxt) with an on-disk cache, demo data, CSV files."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]
CACHE_MAX_AGE_S = 3600
FETCH_LIMIT = 1000
MAX_PAGES = 2000  # hard stop for a misbehaving exchange (2M candles)

_TIMEFRAME_RE = re.compile(r"^([1-9]\d*)([mhdw])$")
_UNIT = {"m": "min", "h": "h", "d": "D", "w": "W"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class DataError(Exception):
    """Candles could not be obtained or are unusable. The message is safe to show to users."""


# ----------------------------------------------------------------------------- helpers


def timeframe_to_timedelta(timeframe: str) -> pd.Timedelta:
    """'15m' -> 15 minutes, '4h' -> 4 hours, '1d' -> 1 day, '1w' -> 7 days."""
    m = _TIMEFRAME_RE.match(timeframe or "")
    if not m:
        raise DataError(f"invalid timeframe '{timeframe}' (use e.g. 15m, 1h, 4h, 1d, 1w)")
    return pd.Timedelta(int(m.group(1)), unit=_UNIT[m.group(2)])


def default_cache_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data"))


def cache_path(cache_dir: Path, exchange_id: str, symbol: str, timeframe: str, days: int) -> Path:
    name = f"{exchange_id}_{symbol.replace('/', '-')}_{timeframe}_{days}d"
    return Path(cache_dir) / (_SAFE_NAME.sub("_", name) + ".csv")


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and clean an OHLCV frame: numeric columns, sorted unique DatetimeIndex, no bad rows."""
    missing = [c for c in OHLCV if c not in df.columns]
    if missing:
        raise DataError(f"candles are missing columns: {', '.join(missing)}")
    out = df[OHLCV].apply(pd.to_numeric, errors="coerce")
    if not isinstance(out.index, pd.DatetimeIndex):
        raise DataError("candles need a datetime index")
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    out.index = out.index.as_unit("ms")  # one resolution everywhere (downloads, cache, CSV, demo)
    out.index.name = "time"
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1) & (out.high >= out.low)]
    out["volume"] = out["volume"].fillna(0.0)
    if out.empty:
        raise DataError("no usable candles")
    return out.astype(float)


def _write_atomic(df: pd.DataFrame, path: Path) -> None:
    """Write via temp file + rename so concurrent readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            df.to_csv(f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_cache(path: Path, max_age: float) -> pd.DataFrame | None:
    try:
        if time.time() - path.stat().st_mtime >= max_age:
            return None
        return normalize(pd.read_csv(path, index_col=0, parse_dates=True))
    except (OSError, ValueError, DataError):
        return None  # missing, stale or corrupt cache -> download again


# ----------------------------------------------------------------------------- sources


def make_exchange(exchange_id: str):
    import ccxt

    if exchange_id not in ccxt.exchanges:
        raise DataError(f"unknown exchange '{exchange_id}'")
    return getattr(ccxt, exchange_id)({"enableRateLimit": True})


def download_candles(client, symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Page through fetch_ohlcv from `days` ago until now. Keeps only fully closed candles."""
    import ccxt

    tf_ms = int(timeframe_to_timedelta(timeframe).total_seconds() * 1000)
    now = client.milliseconds()
    since = now - days * 86_400_000
    rows: list[list] = []
    try:
        for _ in range(MAX_PAGES):
            if since >= now:
                break
            batch = client.fetch_ohlcv(symbol, timeframe, since=since, limit=FETCH_LIMIT)
            if not batch:
                break
            rows += batch
            nxt = batch[-1][0] + tf_ms
            if nxt <= since:  # exchange ignored `since`; avoid an endless loop
                break
            since = nxt
    except ccxt.BadSymbol as e:
        raise DataError(f"symbol '{symbol}' is not available on {client.id}") from e
    except ccxt.BaseError as e:
        raise DataError(f"could not download candles from {client.id}: {type(e).__name__}: {str(e)[:200]}") from e

    if not rows:
        raise DataError(f"no candles returned for {symbol} {timeframe} on {client.id}")
    df = pd.DataFrame(rows, columns=["ts", *OHLCV])
    df = df[df.ts + tf_ms <= now]  # drop the candle that is still forming
    df.index = pd.to_datetime(df.pop("ts"), unit="ms")
    df.index.name = "time"
    return normalize(df)


def fetch_candles(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    days: int,
    *,
    cache_dir: Path | str | None = None,
    max_age: float = CACHE_MAX_AGE_S,
    client=None,
) -> pd.DataFrame:
    """Candles from an exchange, cached on disk for `max_age` seconds."""
    timeframe_to_timedelta(timeframe)  # validate early
    path = cache_path(Path(cache_dir) if cache_dir else default_cache_dir(), exchange_id, symbol, timeframe, days)
    cached = _read_cache(path, max_age)
    if cached is not None:
        return cached
    df = download_candles(client or make_exchange(exchange_id), symbol, timeframe, days)
    with contextlib.suppress(OSError):  # a read-only disk should not break analysis
        _write_atomic(df, path)
    return df


def demo_candles(timeframe: str, days: int, seed: int = 7, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Fake random-walk candles for offline testing. Results on these mean nothing."""
    step = timeframe_to_timedelta(timeframe)
    periods = int(pd.Timedelta(days=days) / step)
    if periods < 2:
        raise DataError("demo period too short for this timeframe")
    end = end if end is not None else pd.Timestamp.now().floor("D")
    idx = pd.date_range(end=end, periods=periods, freq=step, name="time")
    rng = np.random.default_rng(seed)
    vol = 0.03 * np.sqrt(step / pd.Timedelta("1D"))
    close = 60_000 * np.exp(np.cumsum(rng.normal(0, vol, periods)))
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0, vol / 2, periods)) * close
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + wick,
            "low": np.minimum(open_, close) - wick,
            "close": close,
            "volume": rng.uniform(100, 1000, periods),
        },
        index=idx,
    )


_TIME_COLUMNS = ("ts", "time", "timestamp", "date", "datetime", "open_time")


def load_csv(path: str | Path) -> pd.DataFrame:
    """Read OHLCV from CSV. Needs a time column (unix seconds/ms or a date string) and OHLCV columns."""
    try:
        df = pd.read_csv(path)
    except (OSError, ValueError) as e:
        raise DataError(f"cannot read CSV '{path}': {e}") from e
    df.columns = [str(c).strip().lower() for c in df.columns]
    tcol = next((c for c in _TIME_COLUMNS if c in df.columns), None)
    if tcol is None:
        raise DataError(f"CSV needs a time column named one of: {', '.join(_TIME_COLUMNS)}")
    t = df.pop(tcol)
    if pd.api.types.is_numeric_dtype(t):
        unit = "ms" if t.abs().max() > 1e11 else "s"  # 1e11 s is year 5138; 1e11 ms is 1973
        df.index = pd.to_datetime(t, unit=unit)
    else:
        df.index = pd.to_datetime(t, errors="coerce")
        df = df[df.index.notna()]
    return normalize(df)
