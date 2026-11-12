"""Validated analysis parameters, shared by the API and the CLI."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from .data import DataError, timeframe_to_timedelta
from .strategies import STRATEGIES

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}/[A-Z0-9]{1,20}$")
_EXCHANGE_RE = re.compile(r"^[a-z0-9_]{2,30}$")
MAX_TIMEFRAMES = 4


def load_defaults(env: Mapping[str, str] = os.environ) -> dict:
    """Default parameters. DEFAULT_EXCHANGE / DEFAULT_SYMBOL / DEFAULT_FEE override them per deployment."""
    return {
        "exchange": env.get("DEFAULT_EXCHANGE", "indodax").strip().lower(),
        "symbol": env.get("DEFAULT_SYMBOL", "BTC/IDR").strip().upper(),
        "timeframe": "4h",
        "timeframes": "1h,4h,1d",
        "strategy": "combo",
        "days": 730,
        "capital_idr": 10_000_000,
        "usd_idr": 16_500,
        "fee": float(env.get("DEFAULT_FEE", "0.003")),
        "stop_atr": 2.0,
        "tp_atr": 4.0,
        "demo": False,
    }


DEFAULTS = load_defaults()


class ValidationError(ValueError):
    """Bad user input. `errors` maps field name -> message."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


@dataclass(frozen=True)
class Params:
    exchange: str = DEFAULTS["exchange"]
    symbol: str = DEFAULTS["symbol"]
    timeframe: str = DEFAULTS["timeframe"]
    timeframes: tuple[str, ...] = ("1h", "4h", "1d")
    strategy: str = DEFAULTS["strategy"]
    days: int = DEFAULTS["days"]
    capital_idr: float = DEFAULTS["capital_idr"]
    usd_idr: float = DEFAULTS["usd_idr"]
    fee: float = DEFAULTS["fee"]
    stop_atr: float = DEFAULTS["stop_atr"]
    tp_atr: float = DEFAULTS["tp_atr"]
    demo: bool = DEFAULTS["demo"]

    @property
    def quote(self) -> str:
        return self.symbol.split("/")[1]

    @property
    def to_idr(self) -> float:
        """Multiply quote-currency amounts by this to get rupiah."""
        return 1.0 if self.quote == "IDR" else self.usd_idr

    @property
    def capital(self) -> float:
        """Capital in the pair's quote currency."""
        return self.capital_idr / self.to_idr

    def public(self) -> dict:
        return {k: getattr(self, k) for k in DEFAULTS} | {"timeframes": list(self.timeframes), "to_idr": self.to_idr}


def _num(raw, name, errors, cast=float, lo=None, hi=None, lo_open=False):
    try:
        v = cast(float(raw)) if cast is int else cast(raw)
    except (TypeError, ValueError):
        errors[name] = "must be a number"
        return None
    if v != v or v in (float("inf"), float("-inf")):
        errors[name] = "must be a finite number"
        return None
    if lo is not None and (v <= lo if lo_open else v < lo):
        errors[name] = f"must be {'>' if lo_open else '>='} {lo}"
    elif hi is not None and v > hi:
        errors[name] = f"must be <= {hi}"
    return v


def _timeframe(raw, name, errors):
    tf = str(raw).strip()
    try:
        timeframe_to_timedelta(tf)
    except DataError as e:
        errors[name] = str(e)
    return tf


def parse_params(q: Mapping) -> Params:
    """Build Params from a query-string-like mapping; raises ValidationError listing every problem."""
    get = lambda k: q.get(k, DEFAULTS[k])  # noqa: E731
    errors: dict[str, str] = {}

    exchange = str(get("exchange")).strip().lower()
    if not _EXCHANGE_RE.match(exchange):
        errors["exchange"] = "invalid exchange id"
    symbol = str(get("symbol")).strip().upper()
    if not _SYMBOL_RE.match(symbol):
        errors["symbol"] = "must look like BTC/USDT"
    strategy = str(get("strategy")).strip()
    if strategy not in STRATEGIES:
        errors["strategy"] = f"unknown strategy (choose from {', '.join(STRATEGIES)})"
    timeframe = _timeframe(get("timeframe"), "timeframe", errors)
    tfs = tuple(dict.fromkeys(t.strip() for t in str(get("timeframes")).split(",") if t.strip()))
    if not tfs:
        errors["timeframes"] = "give at least one timeframe"
    elif len(tfs) > MAX_TIMEFRAMES:
        errors["timeframes"] = f"at most {MAX_TIMEFRAMES} timeframes"
    else:
        for t in tfs:
            _timeframe(t, "timeframes", errors)

    demo_raw = get("demo")
    demo = demo_raw if isinstance(demo_raw, bool) else str(demo_raw).strip().lower() in ("1", "true", "yes", "on")

    p = Params(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        timeframes=tfs,
        strategy=strategy,
        days=_num(get("days"), "days", errors, int, 10, 3650),
        capital_idr=_num(get("capital_idr"), "capital_idr", errors, float, 0, 1e15, lo_open=True),
        usd_idr=_num(get("usd_idr"), "usd_idr", errors, float, 0, 1e7, lo_open=True),
        fee=_num(get("fee"), "fee", errors, float, 0, 0.05),
        stop_atr=_num(get("stop_atr"), "stop_atr", errors, float, 0, 50),
        tp_atr=_num(get("tp_atr"), "tp_atr", errors, float, 0, 50),
        demo=demo,
    )
    if errors:
        raise ValidationError(errors)
    return p
