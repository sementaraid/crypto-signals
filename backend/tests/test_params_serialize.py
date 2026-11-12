import math

import numpy as np
import pandas as pd
import pytest

from signals.params import DEFAULTS, MAX_TIMEFRAMES, Params, ValidationError, parse_params
from signals.serialize import candle_points, series_points, to_jsonable, unix_seconds


def test_defaults():
    p = parse_params({})
    assert p == Params()
    assert p.timeframes == ("1h", "4h", "1d")
    assert p.to_idr == DEFAULTS["usd_idr"]
    assert p.capital == pytest.approx(10_000_000 / 16_500)


def test_parses_strings_and_normalises():
    p = parse_params(
        {
            "exchange": " Indodax ",
            "symbol": "btc/idr",
            "days": "365",
            "fee": "0.003",
            "capital_idr": "5e7",
            "demo": "true",
            "timeframes": "1h, 4h,1h",
        }
    )
    assert p.exchange == "indodax" and p.symbol == "BTC/IDR"
    assert p.days == 365 and p.fee == 0.003 and p.capital_idr == 5e7 and p.demo
    assert p.timeframes == ("1h", "4h")  # trimmed and de-duplicated
    assert p.to_idr == 1.0 and p.capital == 5e7  # IDR pair: no conversion


@pytest.mark.parametrize(
    "raw, expected",
    [("1", True), ("yes", True), ("on", True), ("false", False), ("0", False), ("", False), (True, True), (False, False)],
)
def test_demo_flag(raw, expected):
    assert parse_params({"demo": raw}).demo is expected


@pytest.mark.parametrize(
    "field, value",
    [
        ("symbol", "BTCUSDT"),
        ("symbol", "BTC/US DT"),
        ("exchange", "../etc"),
        ("strategy", "nope"),
        ("timeframe", "7x"),
        ("timeframes", ""),
        ("timeframes", ",".join(["1h"] * 1 + ["2h", "3h", "4h", "6h"])),
        ("days", "5"),
        ("days", "99999"),
        ("days", "abc"),
        ("fee", "-0.01"),
        ("fee", "0.2"),
        ("fee", "nan"),
        ("capital_idr", "0"),
        ("capital_idr", "inf"),
        ("usd_idr", "-1"),
        ("stop_atr", "-1"),
        ("tp_atr", "x"),
    ],
)
def test_rejects_bad_values(field, value):
    with pytest.raises(ValidationError) as e:
        parse_params({field: value})
    assert field in e.value.errors


def test_reports_all_errors_at_once():
    with pytest.raises(ValidationError) as e:
        parse_params({"fee": "-1", "days": "1", "symbol": "x"})
    assert set(e.value.errors) == {"fee", "days", "symbol"}
    assert "fee" in str(e.value)


def test_max_timeframes_constant():
    assert parse_params({"timeframes": ",".join(["15m", "1h", "4h", "1d"][:MAX_TIMEFRAMES])})


def test_public_is_plain_data():
    pub = parse_params({}).public()
    assert pub["timeframes"] == ["1h", "4h", "1d"] and pub["to_idr"] == 16_500
    assert set(DEFAULTS) <= set(pub)


# ----------------------------------------------------------------------------- serialize


def test_to_jsonable():
    ts = pd.Timestamp("2026-01-01")
    out = to_jsonable(
        {
            "a": np.float64(1.5),
            "b": np.int64(2),
            "c": np.nan,
            "d": np.inf,
            "e": ts,
            "f": pd.NaT,
            "g": np.bool_(True),
            "h": [np.float32(2.0), None, (1, "x")],
            3: "k",
        }
    )
    assert out == {
        "a": 1.5,
        "b": 2,
        "c": None,
        "d": None,
        "e": 1767225600,
        "f": None,
        "g": True,
        "h": [2.0, None, [1, "x"]],
        "3": "k",
    }
    assert type(out["b"]) is int and type(out["g"]) is bool


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_unix_seconds_any_unit(unit):
    idx = pd.DatetimeIndex(["2026-01-01", "2026-01-02"]).as_unit(unit)
    assert unix_seconds(idx).tolist() == [1767225600, 1767312000]


def test_points_skip_nan_and_scale():
    s = pd.Series([1.0, np.nan, 3.0], index=pd.date_range("2026-01-01", periods=3, freq="D"))
    assert series_points(s, 2) == [{"time": 1767225600, "value": 2.0}, {"time": 1767398400, "value": 6.0}]
    d = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]}, index=s.index[:1])
    assert candle_points(d) == [{"time": 1767225600, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}]
    assert all(math.isfinite(p["value"]) for p in series_points(s))
