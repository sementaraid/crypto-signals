#!/usr/bin/env python3
"""
Crypto candle analyzer: buy/sell signals + backtest + chart.

Examples
  python trader.py compare                                  # rank all strategies on BTC/USDT
  python trader.py backtest --strategy ema_cross --timeframe 4h --chart
  python trader.py signal --strategy combo --timeframe 1d     # what does the latest candle say?
  python trader.py compare --exchange indodax --symbol BTC/IDR # trade in rupiah directly
  python trader.py compare --demo                           # offline test with fake candles

Not financial advice. Past performance does not guarantee future results.
"""
import argparse
import os
import time

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------- data

def fetch_candles(exchange_id, symbol, timeframe, days, cache_dir=os.environ.get("DATA_DIR", "data")):
    """Download OHLCV history with ccxt (paginated) and cache to CSV."""
    import ccxt

    os.makedirs(cache_dir, exist_ok=True)
    fname = os.path.join(cache_dir, f"{exchange_id}_{symbol.replace('/', '-')}_{timeframe}_{days}d.csv")
    if os.path.exists(fname) and time.time() - os.path.getmtime(fname) < 3600:
        return pd.read_csv(fname, index_col=0, parse_dates=True)

    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    tf_ms = ex.parse_timeframe(timeframe) * 1000
    since = ex.milliseconds() - days * 86_400_000
    rows = []
    while since < ex.milliseconds():
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        nxt = batch[-1][0] + tf_ms
        if nxt <= since:
            break
        since = nxt
    if not rows:
        raise SystemExit(f"No candles returned for {symbol} {timeframe} on {exchange_id}")
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts")
    df.index = pd.to_datetime(df.pop("ts"), unit="ms")
    df = df.iloc[:-1]  # drop the still-forming candle
    df.to_csv(fname)
    return df


def demo_candles(timeframe, days, seed=7):
    """Fake random-walk candles for offline testing. Results on these mean nothing."""
    freq = {"15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}.get(timeframe, "1h")
    idx = pd.date_range(end=pd.Timestamp.now().floor("D"), periods=int(pd.Timedelta(days=days) / pd.Timedelta(freq)), freq=freq)
    rng = np.random.default_rng(seed)
    vol = 0.03 * np.sqrt(pd.Timedelta(freq) / pd.Timedelta("1D"))
    close = 60_000 * np.exp(np.cumsum(rng.normal(0, vol, len(idx))))
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0, vol / 2, len(idx))) * close
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + wick,
                         "low": np.minimum(open_, close) - wick, "close": close,
                         "volume": rng.uniform(100, 1000, len(idx))}, index=idx)


def load_csv(path):
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    tcol = next(c for c in df.columns if c in ("ts", "time", "timestamp", "date", "datetime"))
    t = df.pop(tcol)
    df.index = pd.to_datetime(t, unit="ms") if np.issubdtype(t.dtype, np.number) else pd.to_datetime(t)
    return df[["open", "high", "low", "close", "volume"]]

# ----------------------------------------------------------------------------- indicators

def add_indicators(df):
    d = df.copy()
    c = d["close"]
    for n in (9, 21, 50, 200):
        d[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + gain / loss)
    d["macd"] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    d["macd_sig"] = d["macd"].ewm(span=9, adjust=False).mean()
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    d["bb_up"], d["bb_mid"], d["bb_lo"] = mid + 2 * sd, mid, mid - 2 * sd
    tr = pd.concat([d["high"] - d["low"], (d["high"] - c.shift()).abs(), (d["low"] - c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    # candlestick patterns
    o, h, l = d["open"], d["high"], d["low"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    po, pc = o.shift(), c.shift()
    d["bull_engulf"] = (pc < po) & (c > o) & (c >= po) & (o <= pc)
    d["bear_engulf"] = (pc > po) & (c < o) & (c <= po) & (o >= pc)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)
    d["hammer"] = (lower_wick >= 2 * body) & (upper_wick <= body) & (body / rng > 0.1)
    d["shooting_star"] = (upper_wick >= 2 * body) & (lower_wick <= body) & (body / rng > 0.1)
    return d

# ----------------------------------------------------------------------------- strategies
# Each returns a Series: +1 = buy signal, -1 = sell signal, 0 = nothing (judged on candle close).

def _cross_up(a, b):
    return (a > b) & (a.shift() <= b.shift())


def ema_cross(d):
    """Trend following: buy when EMA9 crosses above EMA21, sell on cross below."""
    return _cross_up(d.ema9, d.ema21).astype(int) - _cross_up(d.ema21, d.ema9).astype(int)


def macd_trend(d):
    """Buy on MACD crossing its signal line while price is above EMA200."""
    buy = _cross_up(d.macd, d.macd_sig) & (d.close > d.ema200)
    sell = _cross_up(d.macd_sig, d.macd)
    return buy.astype(int) - sell.astype(int)


def rsi_reversion(d):
    """Mean reversion: buy when RSI climbs back above 30, sell when it rises above 70."""
    buy = (d.rsi > 30) & (d.rsi.shift() <= 30)
    sell = (d.rsi > 70) & (d.rsi.shift() <= 70)
    return buy.astype(int) - sell.astype(int)


def bb_reversion(d):
    """Buy a close back inside the lower Bollinger band, sell at the middle/upper band."""
    buy = (d.close > d.bb_lo) & (d.close.shift() <= d.bb_lo.shift())
    sell = d.close >= d.bb_up
    return buy.astype(int) - sell.astype(int)


def combo(d):
    """Bullish candle pattern + uptrend (EMA50>EMA200) + RSI not overbought.
    Exit on bearish pattern or close under EMA50."""
    buy = (d.bull_engulf | d.hammer) & (d.ema50 > d.ema200) & (d.rsi < 65)
    sell = d.bear_engulf | d.shooting_star | _cross_up(d.ema50, d.close)
    return buy.astype(int) - sell.astype(int)


STRATEGIES = {f.__name__: f for f in (ema_cross, macd_trend, rsi_reversion, bb_reversion, combo)}

# ----------------------------------------------------------------------------- backtest

def backtest(d, signal, capital, fee=0.001, stop_atr=2.0, tp_atr=4.0):
    """Long-only spot backtest.
    Signals are read on candle close and executed at the NEXT candle's open (no look-ahead).
    Optional ATR stop-loss / take-profit checked against each candle's high/low."""
    cash, qty = capital, 0.0
    entry = stop = tp = None
    trades, equity = [], np.empty(len(d))
    sig = signal.values
    o, h, l, c, atr = d.open.values, d.high.values, d.low.values, d.close.values, d.atr.values
    idx = d.index

    def close_pos(i, price, why):
        nonlocal cash, qty, entry
        cash = qty * price * (1 - fee)
        trades.append({"entry_time": entry[0], "exit_time": idx[i], "entry": entry[1], "exit": price,
                       "pnl": cash - entry[2], "ret": cash / entry[2] - 1, "reason": why})
        qty, entry = 0.0, None

    for i in range(len(d)):
        if i > 0:
            s = sig[i - 1]
            if qty == 0 and s == 1:
                qty = cash * (1 - fee) / o[i]
                entry = (idx[i], o[i], cash)
                stop = o[i] - stop_atr * atr[i - 1] if stop_atr else None
                tp = o[i] + tp_atr * atr[i - 1] if tp_atr else None
                cash = 0.0
            elif qty > 0 and s == -1:
                close_pos(i, o[i], "signal")
        if qty > 0 and stop is not None and l[i] <= stop:      # stop first = conservative
            close_pos(i, min(stop, o[i]), "stop")
        elif qty > 0 and tp is not None and h[i] >= tp:
            close_pos(i, max(tp, o[i]), "take_profit")
        equity[i] = cash + qty * c[i]
    if qty > 0:
        close_pos(len(d) - 1, c[-1], "end")
        equity[-1] = cash
    return pd.Series(equity, index=idx), pd.DataFrame(trades)


def stats(equity, trades, close, capital, to_idr):
    days = max((equity.index[-1] - equity.index[0]).total_seconds() / 86400, 1)
    daily = equity.resample("1D").last().ffill()
    day_pnl_idr = daily.diff().dropna() * to_idr
    dd = (equity / equity.cummax() - 1).min()
    profit = equity.iloc[-1] - capital
    return {
        "return_%": 100 * (equity.iloc[-1] / capital - 1),
        "buy_hold_%": 100 * (close.iloc[-1] / close.iloc[0] - 1),
        "max_drawdown_%": 100 * dd,
        "trades": len(trades),
        "win_rate_%": 100 * (trades.pnl > 0).mean() if len(trades) else 0.0,
        "avg_idr_per_day": profit * to_idr / days,
        "worst_day_idr": day_pnl_idr.min() if len(day_pnl_idr) else 0.0,
        "days_with_profit_%": 100 * (day_pnl_idr > 0).mean() if len(day_pnl_idr) else 0.0,
    }

def compare_strategies(load, timeframes, capital, to_idr, fee=0.001, stop_atr=2.0, tp_atr=4.0):
    """Every strategy x timeframe, over the full period and over the last 30% only (unseen "test" slice).
    load(timeframe) -> OHLCV DataFrame."""
    rows = []
    for tf in timeframes:
        d = add_indicators(load(tf)).dropna()
        cut = d.index[int(len(d) * 0.7)]
        for name, fn in STRATEGIES.items():
            sig = fn(d)
            eq, tr = backtest(d, sig, capital, fee, stop_atr, tp_atr)
            full = stats(eq, tr, d.close, capital, to_idr)
            dt = d[d.index >= cut]
            eq2, tr2 = backtest(dt, sig[dt.index], capital, fee, stop_atr, tp_atr)
            test = stats(eq2, tr2, dt.close, capital, to_idr)
            rows.append({"timeframe": tf, "strategy": name, **full, "test_return_%": test["return_%"],
                         "test_idr_per_day": test["avg_idr_per_day"]})
    return pd.DataFrame(rows).sort_values("avg_idr_per_day", ascending=False)


def latest_signal(d, strategy, stop_atr=2.0, tp_atr=4.0):
    """What the strategy says on the last closed candle. d must already have indicators."""
    s = STRATEGIES[strategy](d)
    last = d.iloc[-1]
    action = {1: "BUY", -1: "SELL", 0: "HOLD"}[int(s.iloc[-1])]
    recent = s[s != 0]
    prev = recent.iloc[:-1] if action != "HOLD" else recent
    out = {"action": action, "time": d.index[-1], "close": last.close, "rsi": last.rsi,
           "ema50": last.ema50, "ema200": last.ema200, "previous": None, "stop_loss": None, "take_profit": None}
    if len(prev):
        out["previous"] = {"action": "BUY" if prev.iloc[-1] == 1 else "SELL", "time": prev.index[-1]}
    if action == "BUY":
        out["stop_loss"] = last.close - stop_atr * last.atr
        out["take_profit"] = last.close + tp_atr * last.atr
    return out

# ----------------------------------------------------------------------------- chart

def plot(d, trades, equity, title, path, to_idr=1.0):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker

    v = d.iloc[-300:]  # last 300 candles keep the chart readable
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=False, gridspec_kw={"height_ratios": [3, 1]})
    x = np.arange(len(v))
    up = v.close >= v.open
    ax.vlines(x, v.low, v.high, color=np.where(up, "#26a69a", "#ef5350"), linewidth=0.8)
    ax.bar(x, (v.close - v.open).abs().clip(lower=v.close * 1e-4), bottom=np.minimum(v.open, v.close),
           color=np.where(up, "#26a69a", "#ef5350"), width=0.7)
    for col, colr in (("ema21", "#ff9800"), ("ema50", "#2962ff"), ("ema200", "#9c27b0")):
        ax.plot(x, v[col], color=colr, linewidth=1, label=col.upper())
    pos = {t: k for k, t in enumerate(v.index)}
    if len(trades):
        for _, t in trades.iterrows():
            if t.entry_time in pos:
                ax.scatter(pos[t.entry_time], t.entry, marker="^", s=110, color="lime", edgecolor="black", zorder=5)
            if t.exit_time in pos:
                ax.scatter(pos[t.exit_time], t.exit, marker="v", s=110, color="red", edgecolor="black", zorder=5)
    step = max(len(v) // 8, 1)
    ax.set_xticks(x[::step], [ts.strftime("%Y-%m-%d") for ts in v.index[::step]])
    ax.set_title(f"{title}   (▲ buy  ▼ sell, last {len(v)} candles)")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.2)
    ax2.plot(equity.index, equity.values * to_idr, color="#2962ff")
    ax2.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax2.set_title("Account value in IDR (full backtest)")
    ax2.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    print(f"Chart saved: {path}")

# ----------------------------------------------------------------------------- CLI

def get_data(a, timeframe):
    if a.csv:
        return load_csv(a.csv)
    if a.demo:
        return demo_candles(timeframe, a.days)
    return fetch_candles(a.exchange, a.symbol, timeframe, a.days)


def idr_rate(a):
    quote = a.symbol.split("/")[1].upper()
    return 1.0 if quote == "IDR" else a.usd_idr


def fmt(r):
    return {k: (f"{v:,.0f}" if "idr" in k else f"{v:,.1f}" if isinstance(v, float) else v) for k, v in r.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["compare", "backtest", "signal"])
    p.add_argument("--exchange", default="binance", help="any ccxt exchange id, e.g. binance, indodax, tokocrypto")
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--timeframe", default="4h", help="15m, 1h, 4h, 1d ...")
    p.add_argument("--timeframes", default="1h,4h,1d", help="for compare")
    p.add_argument("--strategy", default="combo", choices=list(STRATEGIES))
    p.add_argument("--days", type=int, default=730, help="how much history to test")
    p.add_argument("--capital-idr", type=float, default=10_000_000, help="trading capital in rupiah")
    p.add_argument("--usd-idr", type=float, default=16_500, help="USD->IDR rate (ignored for */IDR pairs)")
    p.add_argument("--fee", type=float, default=0.001, help="fee per trade side (0.001 = 0.1%%)")
    p.add_argument("--stop-atr", type=float, default=2.0, help="stop-loss distance in ATRs (0 = off)")
    p.add_argument("--tp-atr", type=float, default=4.0, help="take-profit distance in ATRs (0 = off)")
    p.add_argument("--target-idr", type=float, default=100_000, help="daily profit goal to compare against")
    p.add_argument("--csv", help="use your own OHLCV CSV instead of downloading")
    p.add_argument("--demo", action="store_true", help="fake candles, offline test only")
    p.add_argument("--chart", action="store_true")
    a = p.parse_args()

    to_idr = idr_rate(a)
    capital = a.capital_idr / to_idr  # capital in quote currency
    if a.demo:
        print("!! DEMO MODE: fake random candles. Numbers below are meaningless; only checks the code runs.\n")

    if a.command == "signal":
        d = add_indicators(get_data(a, a.timeframe))
        r = latest_signal(d, a.strategy, a.stop_atr, a.tp_atr)
        print(f"{a.symbol} {a.timeframe} | strategy {a.strategy} | last closed candle {r['time']}")
        print(f"  close {r['close']:,.2f}  RSI {r['rsi']:.1f}  EMA50 {r['ema50']:,.2f}  EMA200 {r['ema200']:,.2f}")
        print(f"  >>> {r['action']}")
        if r["previous"]:
            print(f"  previous signal: {r['previous']['action']} at {r['previous']['time']}")
        if r["action"] == "BUY":
            print(f"  suggested stop-loss {r['stop_loss']:,.2f} | take-profit {r['take_profit']:,.2f}")
        return

    if a.command == "backtest":
        d = add_indicators(get_data(a, a.timeframe)).dropna()
        eq, tr = backtest(d, STRATEGIES[a.strategy](d), capital, a.fee, a.stop_atr, a.tp_atr)
        r = stats(eq, tr, d.close, capital, to_idr)
        print(f"{a.symbol} {a.timeframe} {a.strategy}  {d.index[0].date()} -> {d.index[-1].date()}  capital {a.capital_idr:,.0f} IDR")
        for k, v in fmt(r).items():
            print(f"  {k:22s} {v}")
        print(f"  target {a.target_idr:,.0f} IDR/day reached on average: {'YES' if r['avg_idr_per_day'] >= a.target_idr else 'NO'}")
        if len(tr):
            print("\nLast 10 trades:")
            print(tr.tail(10).to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
        if a.chart:
            plot(d, tr, eq, f"{a.symbol} {a.timeframe} — {a.strategy}", f"chart_{a.strategy}_{a.timeframe}.png", to_idr)
        return

    res = compare_strategies(lambda tf: get_data(a, tf), a.timeframes.split(","), capital, to_idr,
                             a.fee, a.stop_atr, a.tp_atr)
    pd.set_option("display.width", 200)
    print(f"{a.symbol} | {a.days} days | capital {a.capital_idr:,.0f} IDR | fee {a.fee:.2%}/side | goal {a.target_idr:,.0f} IDR/day\n")
    print(res.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
    print("\n'test_*' = only the most recent 30% of history. A strategy that is good overall but bad there is probably luck.")
    res.to_csv("compare_results.csv", index=False)


if __name__ == "__main__":
    main()
