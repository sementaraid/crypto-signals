"""High-level operations shared by the CLI and the API."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pandas as pd

from .backtest import backtest, stats
from .data import DataError
from .indicators import EMA_SPANS, add_indicators
from .strategies import STRATEGIES, get_strategy

WARMUP_BARS = max(EMA_SPANS)  # skip candles where the slowest EMA is still settling
MIN_BARS = 50  # fewer than this after warm-up is not worth backtesting
TEST_FRACTION = 0.3  # most recent share of history used as the "unseen" test slice

Loader = Callable[[str], pd.DataFrame]


def prepare(candles: pd.DataFrame, min_bars: int = MIN_BARS) -> pd.DataFrame:
    """Indicators computed on all candles, then the warm-up period dropped."""
    d = add_indicators(candles).iloc[WARMUP_BARS:].dropna()
    if len(d) < min_bars:
        raise DataError(
            f"only {len(d)} usable candles after a {WARMUP_BARS}-candle warm-up; "
            f"need at least {min_bars}. Increase the history (days)."
        )
    return d


def run_backtest(
    d: pd.DataFrame, strategy: str, capital: float, to_idr: float, fee: float = 0.001, stop_atr: float = 2.0, tp_atr: float = 4.0
):
    """Returns (equity, trades, stats) for one strategy on a prepared frame."""
    eq, tr = backtest(d, get_strategy(strategy)(d), capital, fee, stop_atr, tp_atr)
    return eq, tr, stats(eq, tr, d.close, capital, to_idr)


def compare_strategies(
    load: Loader,
    timeframes: Iterable[str],
    capital: float,
    to_idr: float,
    fee: float = 0.001,
    stop_atr: float = 2.0,
    tp_atr: float = 4.0,
) -> pd.DataFrame:
    """Every strategy x timeframe over the full period and over the newest TEST_FRACTION only.

    The test slice starts flat (no open position) so it is a fair stand-alone run.
    """
    rows = []
    for tf in timeframes:
        d = prepare(load(tf))
        test = d.iloc[int(len(d) * (1 - TEST_FRACTION)) :]
        for name, fn in STRATEGIES.items():
            sig = fn(d)
            eq, tr = backtest(d, sig, capital, fee, stop_atr, tp_atr)
            full = stats(eq, tr, d.close, capital, to_idr)
            eq2, tr2 = backtest(test, sig.loc[test.index], capital, fee, stop_atr, tp_atr)
            recent = stats(eq2, tr2, test.close, capital, to_idr)
            rows.append(
                {
                    "timeframe": tf,
                    "strategy": name,
                    **full,
                    "test_return_%": recent["return_%"],
                    "test_idr_per_day": recent["avg_idr_per_day"],
                }
            )
    return pd.DataFrame(rows).sort_values("avg_idr_per_day", ascending=False, kind="stable").reset_index(drop=True)


def latest_signal(d: pd.DataFrame, strategy: str, stop_atr: float = 2.0, tp_atr: float = 4.0) -> dict:
    """What the strategy says on the last closed candle of a prepared frame."""
    s = get_strategy(strategy)(d)
    last = d.iloc[-1]
    action = {1: "BUY", -1: "SELL", 0: "HOLD"}[int(s.iloc[-1])]
    fired = s[s != 0]
    earlier = fired.iloc[:-1] if action != "HOLD" else fired
    out = {
        "action": action,
        "time": d.index[-1],
        "close": float(last.close),
        "rsi": float(last.rsi),
        "ema50": float(last.ema50),
        "ema200": float(last.ema200),
        "previous": None,
        "stop_loss": None,
        "take_profit": None,
    }
    if len(earlier):
        out["previous"] = {"action": "BUY" if earlier.iloc[-1] > 0 else "SELL", "time": earlier.index[-1]}
    if action == "BUY":
        out["stop_loss"] = float(last.close - stop_atr * last.atr) if stop_atr else None
        out["take_profit"] = float(last.close + tp_atr * last.atr) if tp_atr else None
    return out
