"""PNG chart for the CLI: candles, EMAs, trade markers and the equity curve."""

from __future__ import annotations

import numpy as np
import pandas as pd

UP, DOWN = "#26a69a", "#ef5350"


def plot(
    d: pd.DataFrame, trades: pd.DataFrame, equity: pd.Series, title: str, path: str, to_idr: float = 1.0, last_n: int = 300
) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    v = d.iloc[-last_n:]
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]})
    try:
        x = np.arange(len(v))
        colors = np.where(v.close >= v.open, UP, DOWN)
        ax.vlines(x, v.low, v.high, color=colors, linewidth=0.8)
        ax.bar(
            x, (v.close - v.open).abs().clip(lower=v.close * 1e-4), bottom=np.minimum(v.open, v.close), color=colors, width=0.7
        )
        for col, colr in (("ema21", "#ff9800"), ("ema50", "#2962ff"), ("ema200", "#9c27b0")):
            ax.plot(x, v[col], color=colr, linewidth=1, label=col.upper())
        pos = {t: k for k, t in enumerate(v.index)}
        for t in trades.itertuples():
            if t.entry_time in pos:
                ax.scatter(pos[t.entry_time], t.entry, marker="^", s=110, color="lime", edgecolor="black", zorder=5)
            if t.exit_time in pos:
                ax.scatter(pos[t.exit_time], t.exit, marker="v", s=110, color="red", edgecolor="black", zorder=5)
        step = max(len(v) // 8, 1)
        ax.set_xticks(x[::step], [ts.strftime("%Y-%m-%d") for ts in v.index[::step]])
        ax.set_title(f"{title}   (▲ buy  ▼ sell, last {len(v)} candles)")
        ax.legend(loc="upper left")
        ax.grid(alpha=0.2)
        ax2.plot(equity.index, equity.to_numpy() * to_idr, color="#2962ff")
        ax2.yaxis.set_major_formatter(FuncFormatter(lambda val, _: f"{val:,.0f}"))
        ax2.set_title("Account value in IDR (full backtest)")
        ax2.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
    finally:
        plt.close(fig)
    return path
