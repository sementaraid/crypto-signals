"""Exchanges the dashboard offers and the coins it suggests.

The coin list is a starting point of large, long-established, liquid coins, not investment advice.
Whether a pair is actually listed is decided by the exchange; unknown pairs return a clear error.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Exchange:
    id: str
    name: str
    quote: str  # default quote currency for symbols on this exchange
    fee: float  # typical taker fee per side


# Indodax first: rupiah pairs, so results need no USD conversion.
EXCHANGES: tuple[Exchange, ...] = (
    Exchange("indodax", "Indodax", "IDR", 0.003),
    Exchange("tokocrypto", "Tokocrypto", "USDT", 0.001),
    Exchange("binance", "Binance", "USDT", 0.001),
    Exchange("okx", "OKX", "USDT", 0.001),
    Exchange("bybit", "Bybit", "USDT", 0.001),
    Exchange("kucoin", "KuCoin", "USDT", 0.001),
    Exchange("kraken", "Kraken", "USDT", 0.004),
    Exchange("coinbase", "Coinbase", "USDT", 0.006),
)

# Large-cap coins with many years of history and deep liquidity, roughly by size.
MAJOR_COINS: tuple[str, ...] = ("BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "TRX", "LINK", "LTC", "BCH", "DOT", "AVAX", "XLM")
# Pegged to the US dollar: they hold value, they do not grow. Useful to park money, not to trade signals on.
STABLECOINS: tuple[str, ...] = ("USDT", "USDC")


def get_exchange(exchange_id: str) -> Exchange | None:
    return next((e for e in EXCHANGES if e.id == exchange_id), None)


def suggested_symbols(quote: str) -> list[str]:
    coins = MAJOR_COINS + (STABLECOINS if quote not in STABLECOINS else ())
    return [f"{c}/{quote}" for c in coins if c != quote]


def catalogue() -> list[dict]:
    """Exchanges with their suggested symbols, for /api/meta."""
    return [asdict(e) | {"symbols": suggested_symbols(e.quote)} for e in EXCHANGES]
