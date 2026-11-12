import pandas as pd
import pytest

from signals.analysis import MIN_BARS, TEST_FRACTION, WARMUP_BARS, compare_strategies, latest_signal, prepare, run_backtest
from signals.data import DataError
from signals.strategies import STRATEGIES


def test_prepare_drops_warmup(demo):
    df = demo("1d", 600)
    d = prepare(df)
    assert d.index[0] == df.index[WARMUP_BARS]
    assert not d.isna().any().any()


def test_prepare_too_short(demo):
    with pytest.raises(DataError, match="warm-up"):
        prepare(demo("1d", WARMUP_BARS + MIN_BARS - 5))


def test_run_backtest(demo):
    d = prepare(demo("4h", 365))
    eq, tr, st = run_backtest(d, "ema_cross", 1000, 16_500)
    assert len(eq) == len(d) and st["trades"] == len(tr)
    with pytest.raises(ValueError):
        run_backtest(d, "nope", 1000, 1)


def test_compare(demo):
    res = compare_strategies(lambda tf: demo(tf, 365), ["4h", "1d"], 1000, 16_500)
    assert len(res) == 2 * len(STRATEGIES)
    assert set(res.timeframe) == {"4h", "1d"} and set(res.strategy) == set(STRATEGIES)
    assert res.avg_idr_per_day.is_monotonic_decreasing
    assert {"test_return_%", "test_idr_per_day", "max_drawdown_%"} <= set(res.columns)


def test_compare_test_slice_is_independent(demo):
    """The 'recent' numbers must equal a fresh backtest started flat on the newest slice."""
    from signals.backtest import backtest, stats

    df = demo("4h", 365)
    res = compare_strategies(lambda tf: df, ["4h"], 1000, 1.0)
    d = prepare(df)
    test = d.iloc[int(len(d) * (1 - TEST_FRACTION)) :]
    sig = STRATEGIES["ema_cross"](d).loc[test.index]
    eq, tr = backtest(test, sig, 1000)
    row = res[res.strategy == "ema_cross"].iloc[0]
    assert row["test_return_%"] == pytest.approx(stats(eq, tr, test.close, 1000, 1.0)["return_%"])


def _with_last_signal(demo, value):
    """Prepared frame + a strategy patched to return `value` on the last candle."""
    d = prepare(demo("4h", 365))
    sig = pd.Series(0, index=d.index)
    sig.iloc[10] = -1
    sig.iloc[-1] = value
    return d, sig


@pytest.mark.parametrize("value, action", [(1, "BUY"), (-1, "SELL"), (0, "HOLD")])
def test_latest_signal(monkeypatch, demo, value, action):
    d, sig = _with_last_signal(demo, value)
    monkeypatch.setitem(STRATEGIES, "ema_cross", lambda _d: sig)
    r = latest_signal(d, "ema_cross", stop_atr=2, tp_atr=4)
    assert r["action"] == action and r["time"] == d.index[-1]
    assert r["previous"] == {"action": "SELL", "time": d.index[10]}
    if action == "BUY":
        assert r["stop_loss"] == pytest.approx(d.close.iloc[-1] - 2 * d.atr.iloc[-1])
        assert r["take_profit"] == pytest.approx(d.close.iloc[-1] + 4 * d.atr.iloc[-1])
    else:
        assert r["stop_loss"] is None and r["take_profit"] is None


def test_latest_signal_disabled_levels(monkeypatch, demo):
    d, sig = _with_last_signal(demo, 1)
    monkeypatch.setitem(STRATEGIES, "ema_cross", lambda _d: sig)
    r = latest_signal(d, "ema_cross", stop_atr=0, tp_atr=0)
    assert r["stop_loss"] is None and r["take_profit"] is None


def test_latest_signal_no_history(monkeypatch, demo):
    d = prepare(demo("4h", 365))
    monkeypatch.setitem(STRATEGIES, "ema_cross", lambda _d: pd.Series(0, index=_d.index))
    assert latest_signal(d, "ema_cross")["previous"] is None


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_latest_signal_matches_strategy(name, demo):
    d = prepare(demo("4h", 365))
    expected = {1: "BUY", -1: "SELL", 0: "HOLD"}[int(STRATEGIES[name](d).iloc[-1])]
    assert latest_signal(d, name)["action"] == expected
