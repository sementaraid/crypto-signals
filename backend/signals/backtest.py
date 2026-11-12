"""Long-only spot backtester and performance statistics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADE_COLUMNS = ["entry_time", "exit_time", "entry", "exit", "pnl", "ret", "reason"]


@dataclass(frozen=True)
class Costs:
    """Per-side fee (0.001 = 0.1%) and ATR multiples for stop-loss / take-profit (0 = off)."""

    fee: float = 0.001
    stop_atr: float = 2.0
    tp_atr: float = 4.0

    def __post_init__(self):
        if not 0 <= self.fee < 0.1:
            raise ValueError("fee must be between 0 and 0.1 (10%)")
        if self.stop_atr < 0 or self.tp_atr < 0:
            raise ValueError("stop_atr and tp_atr must be >= 0")


def backtest(
    d: pd.DataFrame, signal: pd.Series, capital: float, fee: float = 0.001, stop_atr: float = 2.0, tp_atr: float = 4.0
) -> tuple[pd.Series, pd.DataFrame]:
    """Simulate going all-in on buy signals and fully out on sell signals.

    Rules (no look-ahead):
    - a signal on candle i's close is executed at candle i+1's open;
    - stop-loss / take-profit are placed from the entry price using ATR of the signal candle,
      and checked against each candle's low/high from the entry candle onwards;
    - if both are touched in one candle, the stop is assumed to hit first (conservative);
    - a gap through a level fills at the open, not at the level;
    - a position still open on the last candle is closed at its close (reason 'end').

    Returns (equity curve in quote currency, trades DataFrame with TRADE_COLUMNS).
    """
    costs = Costs(fee, stop_atr, tp_atr)
    if capital <= 0:
        raise ValueError("capital must be positive")
    if "atr" not in d.columns:
        raise ValueError("frame needs an 'atr' column; run add_indicators first")
    n = len(d)
    if n == 0:
        return pd.Series(dtype=float), pd.DataFrame(columns=TRADE_COLUMNS)

    sig = signal.reindex(d.index).fillna(0).to_numpy()
    o, h, l, c, atr = (d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "atr"))
    idx = d.index

    cash, qty = float(capital), 0.0
    entry_time = entry_px = entry_cash = stop = tp = None
    trades: list[dict] = []
    equity = np.empty(n)

    def exit_at(i: int, price: float, reason: str) -> None:
        nonlocal cash, qty
        cash = qty * price * (1 - costs.fee)
        trades.append(
            {
                "entry_time": entry_time,
                "exit_time": idx[i],
                "entry": entry_px,
                "exit": price,
                "pnl": cash - entry_cash,
                "ret": cash / entry_cash - 1,
                "reason": reason,
            }
        )
        qty = 0.0

    for i in range(n):
        if i > 0:
            s = sig[i - 1]
            if qty == 0 and s > 0:
                entry_time, entry_px, entry_cash = idx[i], o[i], cash
                qty = cash * (1 - costs.fee) / o[i]
                cash = 0.0
                stop = o[i] - costs.stop_atr * atr[i - 1] if costs.stop_atr else None
                tp = o[i] + costs.tp_atr * atr[i - 1] if costs.tp_atr else None
            elif qty > 0 and s < 0:
                exit_at(i, o[i], "signal")
        if qty > 0 and stop is not None and l[i] <= stop:
            exit_at(i, min(stop, o[i]), "stop")
        elif qty > 0 and tp is not None and h[i] >= tp:
            exit_at(i, max(tp, o[i]), "take_profit")
        equity[i] = cash + qty * c[i]

    if qty > 0:
        exit_at(n - 1, c[-1], "end")
        equity[-1] = cash
    return pd.Series(equity, index=idx, name="equity"), pd.DataFrame(trades, columns=TRADE_COLUMNS)


def stats(equity: pd.Series, trades: pd.DataFrame, close: pd.Series, capital: float, to_idr: float) -> dict:
    """Summary numbers. Money values are converted to IDR with `to_idr` (1.0 for */IDR pairs)."""
    if equity.empty:
        raise ValueError("empty equity curve")
    days = max((equity.index[-1] - equity.index[0]).total_seconds() / 86400, 1.0)
    # daily P&L, with the starting capital as the baseline so the first day counts too
    daily = equity.resample("1D").last().ffill()
    day_pnl = daily.diff()
    day_pnl.iloc[0] = daily.iloc[0] - capital
    day_pnl_idr = day_pnl * to_idr
    peak = np.maximum(equity.cummax(), capital)  # a loss on day one is a drawdown too
    profit = equity.iloc[-1] - capital
    return {
        "return_%": 100 * (equity.iloc[-1] / capital - 1),
        "buy_hold_%": 100 * (close.iloc[-1] / close.iloc[0] - 1),
        "max_drawdown_%": 100 * float((equity / peak - 1).min()),
        "trades": int(len(trades)),
        "win_rate_%": 100 * float((trades["pnl"] > 0).mean()) if len(trades) else 0.0,
        "avg_idr_per_day": profit * to_idr / days,
        "worst_day_idr": float(day_pnl_idr.min()),
        "days_with_profit_%": 100 * float((day_pnl_idr > 0).mean()),
    }
