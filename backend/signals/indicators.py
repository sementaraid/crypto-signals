"""Technical indicators and candlestick patterns. All are causal: row t only uses rows <= t."""

from __future__ import annotations

import numpy as np
import pandas as pd

EMA_SPANS = (9, 21, 50, 200)
RSI_PERIOD = 14
ATR_PERIOD = 14
BB_PERIOD, BB_STD = 20, 2.0


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Wilder's RSI. Flat price -> 50, only gains -> 100, only losses -> 0."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + gain / loss)
    out = out.where(loss != 0, 100.0)
    out = out.where((gain != 0) | (loss != 0), 50.0)
    out.iloc[0] = np.nan  # no change on the first candle
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    return line, ema(line, signal)


def bollinger(close: pd.Series, period: int = BB_PERIOD, n_std: float = BB_STD):
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return mid + n_std * sd, mid, mid - n_std * sd


def atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def patterns(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    po, pc = o.shift(), c.shift()
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)
    solid = (body / rng) > 0.1  # ignore doji-like candles
    return pd.DataFrame(
        {
            "bull_engulf": (pc < po) & (c > o) & (c >= po) & (o <= pc),
            "bear_engulf": (pc > po) & (c < o) & (c <= po) & (o >= pc),
            "hammer": (lower_wick >= 2 * body) & (upper_wick <= body) & solid,
            "shooting_star": (upper_wick >= 2 * body) & (lower_wick <= body) & solid,
        },
        index=df.index,
    )


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]
    for n in EMA_SPANS:
        d[f"ema{n}"] = ema(c, n)
    d["rsi"] = rsi(c)
    d["macd"], d["macd_sig"] = macd(c)
    d["bb_up"], d["bb_mid"], d["bb_lo"] = bollinger(c)
    d["atr"] = atr(d)
    return d.join(patterns(d))
