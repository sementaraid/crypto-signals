"""Turn numpy/pandas values into plain JSON-safe Python."""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd


def to_jsonable(x):
    """NaN/inf/NaT -> None, timestamps -> unix seconds (int), numpy scalars -> Python scalars."""
    if isinstance(x, dict):
        return {str(k): to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_jsonable(v) for v in x]
    if x is None or x is pd.NaT:
        return None
    if isinstance(x, (pd.Timestamp, datetime)):
        return int(pd.Timestamp(x).timestamp())
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if math.isfinite(x) else None
    return x


def unix_seconds(index: pd.DatetimeIndex) -> np.ndarray:
    """Unix seconds regardless of the index's storage unit (pandas 3 may use s/ms/us/ns)."""
    return index.as_unit("s").asi8


def series_points(s: pd.Series, scale: float = 1.0) -> list[dict]:
    """Series -> [{"time": unix_s, "value": float}], the format lightweight-charts expects."""
    t = unix_seconds(s.index)
    return [{"time": int(a), "value": float(v) * scale} for a, v in zip(t, s.to_numpy(), strict=True) if math.isfinite(v)]


def candle_points(d: pd.DataFrame) -> list[dict]:
    t = unix_seconds(d.index)
    return [
        {"time": int(a), "open": float(o), "high": float(h), "low": float(l), "close": float(c)}
        for a, o, h, l, c in zip(t, d.open.to_numpy(), d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy(), strict=True)
    ]
