"""Trading strategies.

Each takes a frame with indicators and returns an int Series judged on candle close:
+1 = buy signal, -1 = sell signal, 0 = nothing. If buy and sell fire together they cancel out (0).
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

Strategy = Callable[[pd.DataFrame], pd.Series]


def _cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift() <= b.shift())


def _signal(buy: pd.Series, sell: pd.Series) -> pd.Series:
    return buy.fillna(False).astype(int) - sell.fillna(False).astype(int)


def ema_cross(d: pd.DataFrame) -> pd.Series:
    """Trend following: buy when EMA9 crosses above EMA21, sell on cross below."""
    return _signal(_cross_up(d.ema9, d.ema21), _cross_up(d.ema21, d.ema9))


def macd_trend(d: pd.DataFrame) -> pd.Series:
    """Buy on MACD crossing its signal line while price is above EMA200. Sell on cross back down."""
    return _signal(_cross_up(d.macd, d.macd_sig) & (d.close > d.ema200), _cross_up(d.macd_sig, d.macd))


def rsi_reversion(d: pd.DataFrame) -> pd.Series:
    """Mean reversion: buy when RSI climbs back above 30, sell when it rises above 70."""
    return _signal((d.rsi > 30) & (d.rsi.shift() <= 30), (d.rsi > 70) & (d.rsi.shift() <= 70))


def bb_reversion(d: pd.DataFrame) -> pd.Series:
    """Buy a close back inside the lower Bollinger band, sell at the upper band."""
    return _signal((d.close > d.bb_lo) & (d.close.shift() <= d.bb_lo.shift()), d.close >= d.bb_up)


def combo(d: pd.DataFrame) -> pd.Series:
    """Bullish candle pattern + uptrend (EMA50>EMA200) + RSI not overbought.
    Exit on bearish pattern or close under EMA50."""
    buy = (d.bull_engulf | d.hammer) & (d.ema50 > d.ema200) & (d.rsi < 65)
    sell = d.bear_engulf | d.shooting_star | _cross_up(d.ema50, d.close)
    return _signal(buy, sell)


STRATEGIES: dict[str, Strategy] = {f.__name__: f for f in (ema_cross, macd_trend, rsi_reversion, bb_reversion, combo)}


def get_strategy(name: str) -> Strategy:
    try:
        return STRATEGIES[name]
    except KeyError:
        raise ValueError(f"unknown strategy '{name}' (choose from {', '.join(STRATEGIES)})") from None


def describe(name: str) -> str:
    return " ".join((STRATEGIES[name].__doc__ or "").split())
