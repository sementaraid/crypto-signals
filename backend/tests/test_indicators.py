import numpy as np
import pandas as pd
import pytest

from signals.indicators import add_indicators, atr, bollinger, ema, macd, patterns, rsi

from .conftest import make_candles


def test_ema_matches_recurrence():
    s = pd.Series([10.0, 11, 12, 11, 13, 15, 14])
    alpha = 2 / (3 + 1)
    expected = [s[0]]
    for x in s[1:]:
        expected.append(alpha * x + (1 - alpha) * expected[-1])
    np.testing.assert_allclose(ema(s, 3), expected)


def test_rsi_flat_up_down():
    assert rsi(pd.Series([5.0] * 30)).iloc[1:].eq(50).all()
    assert rsi(pd.Series(np.arange(1.0, 31))).iloc[1:].eq(100).all()
    assert rsi(pd.Series(np.arange(31.0, 1, -1))).iloc[1:].eq(0).all()
    assert np.isnan(rsi(pd.Series([1.0, 2.0])).iloc[0])


def test_rsi_matches_wilder_by_hand():
    close = pd.Series([44.0, 44.5, 43.8, 44.2, 45.0, 44.7])
    period = 3
    a = 1 / period
    gain = loss = None
    for prev, cur in zip(close[:-1], close[1:], strict=True):
        g, lo = max(cur - prev, 0), max(prev - cur, 0)
        gain = g if gain is None else a * g + (1 - a) * gain
        loss = lo if loss is None else a * lo + (1 - a) * loss
    expected = 100 - 100 / (1 + gain / loss)
    assert rsi(close, period).iloc[-1] == pytest.approx(expected)


def test_rsi_bounded(demo):
    r = rsi(demo()["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_macd_is_fast_minus_slow():
    s = pd.Series(np.linspace(100, 200, 80) + np.sin(np.arange(80)))
    line, sig = macd(s)
    np.testing.assert_allclose(line, ema(s, 12) - ema(s, 26))
    np.testing.assert_allclose(sig, ema(line, 9))


def test_bollinger():
    s = pd.Series(np.arange(1.0, 41))
    up, mid, lo = bollinger(s, 20, 2)
    assert mid.iloc[19] == pytest.approx(s.iloc[:20].mean())
    assert up.iloc[19] - mid.iloc[19] == pytest.approx(2 * s.iloc[:20].std())
    assert mid.iloc[:19].isna().all()
    flat_up, flat_mid, flat_lo = bollinger(pd.Series([7.0] * 25))
    assert flat_up.iloc[-1] == flat_mid.iloc[-1] == flat_lo.iloc[-1] == 7


def test_atr_constant_range_and_gaps():
    df = make_candles([10.0] * 30, open_=[10.0] * 30, high=[11.0] * 30, low=[9.0] * 30)
    assert atr(df).iloc[-1] == pytest.approx(2.0)
    # true range uses the previous close when the candle gaps
    gap = make_candles([10.0, 20.0], open_=[10.0, 19.0], high=[10.0, 21.0], low=[10.0, 19.0])
    tr2 = max(21 - 19, abs(21 - 10), abs(19 - 10))
    assert atr(gap, period=1).iloc[-1] == pytest.approx(tr2)


def test_patterns():
    #                 bear        bull engulf   hammer        shooting star  doji
    o = [10.0, 10.0, 9.0, 8.5, 20.0, 19.9, 20.0, 20.0]
    c = [10.0, 9.0, 10.5, 8.8, 20.3, 19.6, 20.0, 20.01]
    h = [10.0, 10.0, 10.5, 8.9, 20.35, 21.0, 20.5, 20.5]
    l = [10.0, 9.0, 9.0, 7.0, 19.9, 19.55, 19.5, 19.5]
    p = patterns(make_candles(c, open_=o, high=h, low=l))
    assert p["bull_engulf"].tolist() == [False, False, True, False, False, False, False, False]
    assert p["hammer"].iloc[3]
    assert p["shooting_star"].iloc[5]
    assert not p["hammer"].iloc[6] and not p["shooting_star"].iloc[6]  # flat doji is neither
    bear = patterns(make_candles([11.0, 9.5], open_=[10.0, 11.5], high=[11.0, 11.5], low=[10.0, 9.5]))
    assert bear["bear_engulf"].iloc[1]


def test_add_indicators_columns_and_no_mutation(demo):
    df = demo()
    before = df.copy()
    d = add_indicators(df)
    pd.testing.assert_frame_equal(df, before)
    for col in [
        "ema9",
        "ema21",
        "ema50",
        "ema200",
        "rsi",
        "macd",
        "macd_sig",
        "bb_up",
        "bb_mid",
        "bb_lo",
        "atr",
        "bull_engulf",
        "bear_engulf",
        "hammer",
        "shooting_star",
    ]:
        assert col in d.columns


def test_indicators_have_no_lookahead(demo):
    """Values at row t must not change when future candles are added."""
    df = demo("1d", 400)
    full = add_indicators(df)
    for k in (60, 250, 399):
        part = add_indicators(df.iloc[:k])
        pd.testing.assert_frame_equal(part, full.iloc[:k], check_exact=False, rtol=1e-9)
