"""Command line interface.

Examples
  python trader.py compare                                   # rank all strategies on BTC/USDT
  python trader.py backtest --strategy ema_cross --timeframe 4h --chart
  python trader.py signal --strategy combo --timeframe 1d      # what does the latest candle say?
  python trader.py compare --exchange indodax --symbol BTC/IDR --fee 0.003
  python trader.py compare --demo                            # offline test with fake candles

Not financial advice. Past performance does not guarantee future results.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from .analysis import compare_strategies, latest_signal, prepare, run_backtest
from .data import DataError, demo_candles, fetch_candles, load_csv
from .params import DEFAULTS, Params, ValidationError, parse_params
from .strategies import STRATEGIES

DEMO_WARNING = "!! DEMO MODE: fake random candles. Numbers below are meaningless; only checks the code runs.\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trader.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["compare", "backtest", "signal"])
    p.add_argument("--exchange", default=DEFAULTS["exchange"], help="ccxt exchange id: binance, indodax, tokocrypto ...")
    p.add_argument("--symbol", default=DEFAULTS["symbol"])
    p.add_argument("--timeframe", default=DEFAULTS["timeframe"], help="15m, 1h, 4h, 1d ...")
    p.add_argument("--timeframes", default=DEFAULTS["timeframes"], help="comma separated, for compare")
    p.add_argument("--strategy", default=DEFAULTS["strategy"], choices=list(STRATEGIES))
    p.add_argument("--days", default=DEFAULTS["days"], help="how much history to test")
    p.add_argument("--capital-idr", dest="capital_idr", default=DEFAULTS["capital_idr"], help="trading capital in rupiah")
    p.add_argument("--usd-idr", dest="usd_idr", default=DEFAULTS["usd_idr"], help="USD->IDR rate (ignored for */IDR)")
    p.add_argument("--fee", default=DEFAULTS["fee"], help="fee per trade side (0.001 = 0.1%%)")
    p.add_argument("--stop-atr", dest="stop_atr", default=DEFAULTS["stop_atr"], help="stop-loss in ATRs (0 = off)")
    p.add_argument("--tp-atr", dest="tp_atr", default=DEFAULTS["tp_atr"], help="take-profit in ATRs (0 = off)")
    p.add_argument("--target-idr", dest="target_idr", type=float, default=100_000, help="daily profit goal")
    p.add_argument("--csv", help="use your own OHLCV CSV instead of downloading")
    p.add_argument("--demo", action="store_true", help="fake candles, offline test only")
    p.add_argument("--chart", action="store_true", help="save a PNG chart (backtest)")
    p.add_argument("--out", default="compare_results.csv", help="where compare writes its CSV ('' = don't)")
    return p


def make_loader(p: Params, csv: str | None):
    def load(timeframe: str) -> pd.DataFrame:
        if csv:
            return load_csv(csv)
        if p.demo:
            return demo_candles(timeframe, p.days)
        return fetch_candles(p.exchange, p.symbol, timeframe, p.days)

    return load


def _fmt(k, v):
    if "idr" in k:
        return f"{v:,.0f}"
    return f"{v:,.1f}" if isinstance(v, float) else v


def cmd_signal(p: Params, load) -> None:
    r = latest_signal(prepare(load(p.timeframe)), p.strategy, p.stop_atr, p.tp_atr)
    print(f"{p.symbol} {p.timeframe} | strategy {p.strategy} | last closed candle {r['time']}")
    print(f"  close {r['close']:,.2f}  RSI {r['rsi']:.1f}  EMA50 {r['ema50']:,.2f}  EMA200 {r['ema200']:,.2f}")
    print(f"  >>> {r['action']}")
    if r["previous"]:
        print(f"  previous signal: {r['previous']['action']} at {r['previous']['time']}")
    if r["stop_loss"] is not None:
        print(f"  suggested stop-loss {r['stop_loss']:,.2f}", end="")
    if r["take_profit"] is not None:
        print(f" | take-profit {r['take_profit']:,.2f}", end="")
    if r["stop_loss"] is not None or r["take_profit"] is not None:
        print()


def cmd_backtest(p: Params, load, target_idr: float, chart: bool) -> None:
    d = prepare(load(p.timeframe))
    eq, tr, st = run_backtest(d, p.strategy, p.capital, p.to_idr, p.fee, p.stop_atr, p.tp_atr)
    print(f"{p.symbol} {p.timeframe} {p.strategy}  {d.index[0].date()} -> {d.index[-1].date()}  capital {p.capital_idr:,.0f} IDR")
    for k, v in st.items():
        print(f"  {k:22s} {_fmt(k, v)}")
    print(f"  target {target_idr:,.0f} IDR/day reached on average: {'YES' if st['avg_idr_per_day'] >= target_idr else 'NO'}")
    if len(tr):
        print("\nLast 10 trades:")
        print(tr.tail(10).to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    if chart:
        from .chart import plot

        path = plot(d, tr, eq, f"{p.symbol} {p.timeframe} — {p.strategy}", f"chart_{p.strategy}_{p.timeframe}.png", p.to_idr)
        print(f"Chart saved: {path}")


def cmd_compare(p: Params, load, target_idr: float, out: str) -> None:
    res = compare_strategies(load, p.timeframes, p.capital, p.to_idr, p.fee, p.stop_atr, p.tp_atr)
    with pd.option_context("display.width", 220, "display.max_columns", None):
        print(
            f"{p.symbol} | {p.days} days | capital {p.capital_idr:,.0f} IDR | fee {p.fee:.2%}/side | "
            f"goal {target_idr:,.0f} IDR/day\n"
        )
        print(res.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
    print("\n'test_*' = only the most recent 30% of history. Good overall but bad there is probably luck.")
    if out:
        res.to_csv(out, index=False)


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        p = parse_params({k: getattr(a, k) for k in DEFAULTS})
        load = make_loader(p, a.csv)
        if p.demo and not a.csv:
            print(DEMO_WARNING)
        if a.command == "signal":
            cmd_signal(p, load)
        elif a.command == "backtest":
            cmd_backtest(p, load, a.target_idr, a.chart)
        else:
            cmd_compare(p, load, a.target_idr, a.out)
    except (ValidationError, DataError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0
