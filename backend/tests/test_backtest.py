import numpy as np
import pandas as pd
import pytest

from signals.backtest import TRADE_COLUMNS, Costs, backtest, stats
from signals.indicators import add_indicators
from signals.strategies import STRATEGIES

from .conftest import make_candles, signal_at, with_atr

CAP = 1000.0


def run(df, buys=(), sells=(), fee=0.0, stop_atr=0.0, tp_atr=0.0, atr=1.0):
    d = with_atr(df, atr)
    return backtest(d, signal_at(d, buys, sells), CAP, fee, stop_atr, tp_atr)


def test_no_signals_keeps_capital():
    eq, tr = run(make_candles([10, 11, 12, 9]))
    assert (eq == CAP).all()
    assert tr.empty and list(tr.columns) == TRADE_COLUMNS


def test_executes_at_next_open():
    df = make_candles([10, 10, 12, 15, 15], open_=[10, 10, 11, 14, 16])
    eq, tr = run(df, buys=[1], sells=[3])
    t = tr.iloc[0]
    assert t.entry_time == df.index[2] and t.entry == 11
    assert t.exit_time == df.index[4] and t.exit == 16
    assert t.reason == "signal"
    assert t.pnl == pytest.approx(CAP * 16 / 11 - CAP)
    assert eq.iloc[1] == CAP  # still flat on the signal candle
    assert eq.iloc[3] == pytest.approx(CAP / 11 * 15)  # marked to close while holding
    assert eq.iloc[-1] == pytest.approx(CAP * 16 / 11)


def test_round_trip_fees():
    df = make_candles([10] * 5, open_=[10] * 5)
    eq, tr = run(df, buys=[0], sells=[2], fee=0.001)
    assert tr.iloc[0].ret == pytest.approx((1 - 0.001) ** 2 - 1)
    assert eq.iloc[-1] == pytest.approx(CAP * 0.999**2)


def test_stop_loss_hits_at_level():
    df = make_candles([10, 10, 10, 9], open_=[10, 10, 10, 10], high=[10, 10, 10, 10], low=[10, 10, 10, 7.5])
    _, tr = run(df, buys=[0], stop_atr=2, atr=1)  # entry 10, stop 8
    assert tr.iloc[0].reason == "stop" and tr.iloc[0].exit == 8


def test_stop_loss_gap_fills_at_open():
    df = make_candles([10, 10, 6], open_=[10, 10, 6.5], high=[10, 10, 6.5], low=[10, 10, 5])
    _, tr = run(df, buys=[0], stop_atr=2)
    assert tr.iloc[0].exit == 6.5  # worse than the 8 stop, as in reality


def test_take_profit_and_gap_up():
    df = make_candles([10, 10, 13], open_=[10, 10, 10], high=[10, 10, 15], low=[10, 10, 10])
    _, tr = run(df, buys=[0], tp_atr=4)  # tp 14
    assert tr.iloc[0].reason == "take_profit" and tr.iloc[0].exit == 14
    gap = make_candles([10, 10, 20], open_=[10, 10, 18], high=[10, 10, 20], low=[10, 10, 18])
    _, tr = run(gap, buys=[0], tp_atr=4)
    assert tr.iloc[0].exit == 18


def test_stop_wins_when_both_touched():
    df = make_candles([10, 10, 10], open_=[10, 10, 10], high=[10, 10, 20], low=[10, 10, 1])
    _, tr = run(df, buys=[0], stop_atr=2, tp_atr=4)
    assert tr.iloc[0].reason == "stop"


def test_stop_checked_on_entry_candle():
    df = make_candles([10, 9], open_=[10, 10], high=[10, 10], low=[10, 7])
    _, tr = run(df, buys=[0], stop_atr=2)
    assert tr.iloc[0].entry_time == df.index[1] and tr.iloc[0].reason == "stop"


def test_levels_use_signal_candle_atr():
    df = make_candles([10, 10, 10], open_=[10, 10, 10], high=[10, 10, 10], low=[10, 10, 8.5])
    d = with_atr(df)
    d["atr"] = [1.0, 0.5, 100.0]  # stop = 10 - 2*0.5 = 9 (atr of candle 1, not candle 2)
    _, tr = backtest(d, signal_at(d, buys=[1]), CAP, 0, 2, 0)
    assert tr.iloc[0].exit == 9


def test_open_position_closed_at_end():
    df = make_candles([10, 10, 12], open_=[10, 10, 11])
    eq, tr = run(df, buys=[0], fee=0.001)
    assert tr.iloc[0].reason == "end" and tr.iloc[0].exit == 12
    assert eq.iloc[-1] == pytest.approx(CAP * 0.999 * 12 / 10 * 0.999)


def test_duplicate_signals_ignored():
    df = make_candles([10] * 6, open_=[10] * 6)
    _, tr = run(df, buys=[0, 1, 2], sells=[3, 4])
    assert len(tr) == 1
    _, tr = run(df, sells=[0, 1])
    assert tr.empty


def test_sell_then_rebuy():
    df = make_candles([10, 10, 10, 10, 10, 10], open_=[10, 11, 12, 13, 14, 15])
    _, tr = run(df, buys=[0, 2], sells=[1])
    assert tr.entry.tolist() == [11, 13]
    assert tr.exit.tolist() == [12, 10]  # second trade still open -> closed at the last close
    assert tr.reason.tolist() == ["signal", "end"]


def test_misaligned_signal_is_reindexed():
    df = with_atr(make_candles([10, 10, 12], open_=[10, 10, 11]))
    sig = pd.Series([1], index=[df.index[0]])
    _, tr = backtest(df, sig, CAP, 0, 0, 0)
    assert len(tr) == 1


@pytest.mark.parametrize(
    "kwargs, msg",
    [
        (dict(capital=0), "capital"),
        (dict(fee=-0.1), "fee"),
        (dict(fee=0.5), "fee"),
        (dict(stop_atr=-1), "stop_atr"),
    ],
)
def test_invalid_inputs(kwargs, msg):
    d = with_atr(make_candles([10, 11]))
    args = dict(capital=CAP, fee=0.001, stop_atr=2.0, tp_atr=4.0) | kwargs
    with pytest.raises(ValueError, match=msg):
        backtest(d, signal_at(d), **args)


def test_requires_atr_and_handles_empty():
    with pytest.raises(ValueError, match="atr"):
        backtest(make_candles([1, 2]), pd.Series(dtype=int), CAP)
    eq, tr = backtest(with_atr(make_candles([1.0])).iloc[:0], pd.Series(dtype=int), CAP)
    assert eq.empty and tr.empty


def test_costs_defaults():
    assert Costs() == Costs(0.001, 2.0, 4.0)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_accounting_invariants_on_demo(name, demo):
    d = add_indicators(demo("1h", 365)).iloc[200:].dropna()
    eq, tr = backtest(d, STRATEGIES[name](d), CAP, 0.001, 2.0, 4.0)
    assert (eq > 0).all()
    assert eq.iloc[-1] == pytest.approx(CAP + tr.pnl.sum())
    # money compounds trade by trade
    assert eq.iloc[-1] == pytest.approx(CAP * np.prod(1 + tr.ret.to_numpy()))
    assert (tr.exit_time >= tr.entry_time).all()
    assert (tr.entry_time.iloc[1:].to_numpy() >= tr.exit_time.iloc[:-1].to_numpy()).all()  # never overlap
    assert set(tr.reason) <= {"signal", "stop", "take_profit", "end"}


# ----------------------------------------------------------------------------- stats


def _eq(values, freq="12h"):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values), freq=freq), dtype=float)


def test_stats_numbers():
    eq = _eq([1000, 1100, 990, 1210])  # 2 days, 12h apart
    tr = pd.DataFrame({"pnl": [100.0, -110, 220]})
    close = _eq([50, 55, 60, 75])
    s = stats(eq, tr, close, 1000, to_idr=10)
    assert s["return_%"] == pytest.approx(21)
    assert s["buy_hold_%"] == pytest.approx(50)
    assert s["max_drawdown_%"] == pytest.approx(-10)
    assert s["trades"] == 3 and s["win_rate_%"] == pytest.approx(200 / 3)
    assert s["avg_idr_per_day"] == pytest.approx(210 * 10 / 1.5)
    # day 1 closes at 1100 (+100 vs capital), day 2 at 1210 (+110)
    assert s["worst_day_idr"] == pytest.approx(1000)
    assert s["days_with_profit_%"] == pytest.approx(100)


def test_stats_counts_first_day_loss():
    s = stats(_eq([900, 900, 950, 950]), pd.DataFrame({"pnl": []}), _eq([1, 1, 1, 1]), 1000, 1)
    assert s["worst_day_idr"] == pytest.approx(-100)
    assert s["max_drawdown_%"] == pytest.approx(-10)  # drop below starting capital counts
    assert s["win_rate_%"] == 0 and s["trades"] == 0


def test_stats_minimum_one_day_and_empty():
    s = stats(_eq([1000, 1010], freq="1h"), pd.DataFrame({"pnl": [10.0]}), _eq([1, 1], "1h"), 1000, 1)
    assert s["avg_idr_per_day"] == pytest.approx(10)  # 1 hour of data counts as 1 day
    with pytest.raises(ValueError):
        stats(pd.Series(dtype=float), pd.DataFrame(), pd.Series(dtype=float), 1000, 1)
