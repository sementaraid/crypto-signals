import pandas as pd
import pytest

from signals.cli import main
from signals.strategies import STRATEGIES

from .conftest import FIXED_END


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_compare_writes_csv(in_tmp, capsys):
    assert main(["compare", "--demo", "--timeframes", "4h,1d", "--days", "365"]) == 0
    out = capsys.readouterr().out
    assert "DEMO MODE" in out and "rsi_reversion" in out
    res = pd.read_csv(in_tmp / "compare_results.csv")
    assert len(res) == 2 * len(STRATEGIES)


def test_compare_no_csv(in_tmp):
    assert main(["compare", "--demo", "--timeframes", "1d", "--days", "400", "--out", ""]) == 0
    assert not list(in_tmp.glob("*.csv"))


def test_backtest_with_chart(in_tmp, capsys):
    assert main(["backtest", "--demo", "--strategy", "ema_cross", "--timeframe", "4h", "--days", "365", "--chart"]) == 0
    out = capsys.readouterr().out
    assert "return_%" in out and "Chart saved" in out
    assert (in_tmp / "chart_ema_cross_4h.png").stat().st_size > 10_000


def test_signal(capsys):
    assert main(["signal", "--demo", "--timeframe", "1d", "--days", "400"]) == 0
    assert ">>>" in capsys.readouterr().out


def test_csv_input(in_tmp, demo, capsys):
    df = demo("1d", 400)
    df.index.name = "date"
    df.to_csv(in_tmp / "my.csv")
    assert main(["backtest", "--csv", "my.csv", "--timeframe", "1d"]) == 0
    assert str(FIXED_END.date()) in capsys.readouterr().out


@pytest.mark.parametrize(
    "args, msg",
    [
        (["backtest", "--demo", "--fee", "-1"], "fee"),
        (["signal", "--demo", "--symbol", "BTCUSDT"], "symbol"),
        (["backtest", "--demo", "--timeframe", "1d", "--days", "100"], "warm-up"),
        (["backtest", "--csv", "missing.csv"], "cannot read"),
    ],
)
def test_errors_exit_2(args, msg, capsys):
    assert main(args) == 2
    assert msg in capsys.readouterr().err


def test_unknown_strategy_rejected_by_argparse():
    with pytest.raises(SystemExit):
        main(["backtest", "--strategy", "nope"])
