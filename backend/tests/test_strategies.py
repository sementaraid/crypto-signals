import numpy as np
import pandas as pd
import pytest

from signals.indicators import add_indicators
from signals.strategies import STRATEGIES, _signal, describe, get_strategy


@pytest.fixture
def indicators(demo):
    return add_indicators(demo("4h", 400))


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_output_shape_and_values(name, indicators):
    s = STRATEGIES[name](indicators)
    assert s.index.equals(indicators.index)
    assert set(s.unique()) <= {-1, 0, 1}
    assert pd.api.types.is_integer_dtype(s)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_strategies_have_no_lookahead(name, demo):
    df = demo("4h", 400)
    full = STRATEGIES[name](add_indicators(df))
    for k in (500, 1500, 2399):
        part = STRATEGIES[name](add_indicators(df.iloc[:k]))
        pd.testing.assert_series_equal(part, full.iloc[:k], check_names=False)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_strategies_fire_on_demo_data(name, demo):
    s = STRATEGIES[name](add_indicators(demo("1h", 730)))
    assert (s == 1).any() and (s == -1).any()


def _frame(**cols):
    n = len(next(iter(cols.values())))
    return pd.DataFrame(cols, index=pd.date_range("2026-01-01", periods=n, freq="h"))


def test_ema_cross_exact_bars():
    d = _frame(ema9=[1.0, 2, 4, 3, 1], ema21=[2.0, 3, 3, 3, 2])
    assert get_strategy("ema_cross")(d).tolist() == [0, 0, 1, 0, -1]


def test_rsi_reversion_exact_bars():
    d = _frame(rsi=[40.0, 25, 31, 50, 71, 80, 60])
    assert get_strategy("rsi_reversion")(d).tolist() == [0, 0, 1, 0, -1, 0, 0]


def test_macd_trend_requires_uptrend():
    d = _frame(macd=[-1.0, 1, -1, 1], macd_sig=[0.0, 0, 0, 0], close=[10.0, 10, 10, 10], ema200=[5.0, 5, 5, 20])
    assert get_strategy("macd_trend")(d).tolist() == [0, 1, -1, 0]


def test_bb_reversion_exact_bars():
    d = _frame(close=[10.0, 8, 9.5, 12, 15], bb_lo=[9.0, 9, 9, 9, 9], bb_up=[14.0, 14, 14, 14, 14])
    assert get_strategy("bb_reversion")(d).tolist() == [0, 0, 1, 0, -1]


def test_combo_needs_pattern_trend_and_rsi():
    base = dict(
        bull_engulf=[False, True, True, True],
        hammer=[False] * 4,
        bear_engulf=[False] * 4,
        shooting_star=[False] * 4,
        ema50=[10.0, 10, 10, 8],
        ema200=[9.0, 9, 9, 9],
        rsi=[50.0, 50, 70, 50],
        close=[11.0, 11, 11, 11],
    )
    assert get_strategy("combo")(_frame(**base)).tolist() == [0, 1, 0, 0]


def test_simultaneous_buy_and_sell_cancel():
    idx = pd.RangeIndex(3)
    assert _signal(pd.Series([True, True, False], idx), pd.Series([True, False, True], idx)).tolist() == [0, 1, -1]


def test_get_strategy_unknown():
    with pytest.raises(ValueError, match="unknown strategy"):
        get_strategy("nope")


def test_describe_is_single_line():
    for name in STRATEGIES:
        assert describe(name) and "\n" not in describe(name)


def test_nan_inputs_do_not_signal():
    d = _frame(ema9=[np.nan, np.nan, 2.0], ema21=[np.nan, 1.0, 1.0])
    assert get_strategy("ema_cross")(d).tolist() == [0, 0, 0]
