from signals.markets import EXCHANGES, MAJOR_COINS, STABLECOINS, catalogue, get_exchange, suggested_symbols


def test_indodax_first_and_rupiah():
    assert EXCHANGES[0].id == "indodax" and EXCHANGES[0].quote == "IDR"
    assert get_exchange("indodax").fee == 0.003
    assert get_exchange("nope") is None


def test_exchange_ids_are_real_ccxt_exchanges():
    import ccxt

    for e in EXCHANGES:
        assert e.id in ccxt.exchanges
        assert 0 <= e.fee < 0.01


def test_indodax_supports_dashboard_timeframes():
    import ccxt

    from signals.api import TIMEFRAMES

    ex = ccxt.indodax()
    assert ex.has["fetchOHLCV"]
    assert set(TIMEFRAMES) <= set(ex.timeframes)


def test_suggested_symbols():
    idr = suggested_symbols("IDR")
    assert idr[0] == "BTC/IDR" and "USDT/IDR" in idr and len(idr) == len(MAJOR_COINS) + len(STABLECOINS)
    usdt = suggested_symbols("USDT")
    assert "USDT/USDT" not in usdt and "USDC/USDT" not in usdt  # no stablecoin vs stablecoin
    assert len(set(idr)) == len(idr)


def test_catalogue_shape():
    cat = catalogue()
    assert [c["id"] for c in cat] == [e.id for e in EXCHANGES]
    assert all({"id", "name", "quote", "fee", "symbols"} <= set(c) for c in cat)
