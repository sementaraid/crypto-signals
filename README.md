# Crypto Signals

Analyzes crypto candle history, generates BUY/SELL signals, backtests them
(with fees, stop-loss and take-profit) and reports profit in **rupiah per day**.

- `backend/` — Python package `signals` (indicators, strategies, backtester, Flask API, CLI) + tests
- `frontend/` — Vite dashboard (candlestick chart with buy/sell markers, stats, trades, strategy comparison)
- `Dockerfile` — builds the dashboard and serves it together with the API on one port

## Run with Docker (easiest)
```
docker compose up --build
```
Open http://localhost:8000. Downloaded candles are cached in a Docker volume for 1 hour.

## Deploy to the VPS (behind the shared Caddy)
Production runs behind the Caddy reverse proxy from
[sementaraid/caddy](https://github.com/sementaraid/caddy), which serves it at
`https://signals.sunar.dev` with HTTPS and a password. No ports are published by the app.
```
git clone https://github.com/sementaraid/crypto-signals.git ~/apps/crypto-signals
cd ~/apps/crypto-signals
docker compose -f compose.prod.yaml up -d --build
```
Update later with `git pull && docker compose -f compose.prod.yaml up -d --build`.
The login is configured in the caddy repo's `.env` (see its `.env.example`).

## Run without Docker (development)
Terminal 1 — API:
```
cd backend
pip install -r requirements.txt
python app.py
```
Terminal 2 — dashboard with hot reload (proxies `/api` to port 8000):
```
cd frontend
npm install
npm run dev
```
Open http://localhost:5173.

## Backend layout
```
backend/
  app.py              WSGI entry (gunicorn app:app)
  trader.py           CLI entry
  signals/
    data.py           exchange download (ccxt), atomic on-disk cache, demo data, CSV import
    indicators.py     EMA, RSI, MACD, Bollinger, ATR, candle patterns (all causal)
    strategies.py     the 5 strategies + registry
    backtest.py       long-only backtester and statistics
    analysis.py       warm-up handling, compare, latest signal (shared by API and CLI)
    params.py         input validation (shared by API and CLI)
    serialize.py      JSON-safe output
    api.py            Flask app factory and routes
    cli.py            command line
    chart.py          PNG chart for the CLI
  tests/              pytest suite
```

## Tests
```
cd backend
pip install -r requirements-dev.txt
pytest                      # run everything (~2 s, fully offline)
pytest --cov=signals        # with coverage
ruff check . && ruff format --check .
```
The suite checks indicator maths against hand calculations, makes sure no indicator or strategy
uses future candles, verifies backtest fills (next-candle open, stop-loss/take-profit, gaps, fees)
and accounting, and exercises the API, CLI, data download (with a fake exchange) and cache.
GitHub Actions runs lint, tests, the frontend build and a Docker smoke test on every push.

## API
All endpoints are `GET` and take query parameters:
`exchange` (binance), `symbol` (BTC/USDT), `timeframe` (4h), `strategy` (combo), `days` (730),
`capital_idr` (10000000), `usd_idr` (16500), `fee` (0.001 = 0.1%), `stop_atr` (2), `tp_atr` (4), `demo` (false).

| Endpoint | Returns |
|---|---|
| `/api/meta` | strategies (with descriptions), timeframes, exchanges |
| `/api/backtest` | stats, candles, EMA lines, trades, equity curve in IDR, latest signal |
| `/api/compare?timeframes=1h,4h,1d` | every strategy x timeframe ranked by IDR/day |
| `/api/signal` | what the latest closed candle says: BUY / SELL / HOLD (+ stop-loss / take-profit) |
| `/api/health` | `{"ok": true, "version": ...}` |

Errors are JSON: `400` invalid input (`{"error", "fields"}`), `422` candles unavailable or too few,
`500` unexpected (details are logged, not returned).

Example: `curl "http://localhost:8000/api/signal?symbol=ETH/USDT&timeframe=1d&strategy=ema_cross"`

## Command line (still works)
```
cd backend
python trader.py compare --capital-idr 50000000
python trader.py backtest --strategy combo --timeframe 4h --chart
python trader.py signal --strategy combo --timeframe 4h
python trader.py compare --symbol ETH/IDR
python trader.py compare --exchange tokocrypto --symbol BTC/USDT --fee 0.001
```

## Strategies
| name | idea |
|---|---|
| ema_cross | buy EMA9 crossing above EMA21, sell on cross below (trend) |
| macd_trend | MACD crossing up, only when price above EMA200 |
| rsi_reversion | buy RSI recovering above 30, sell above 70 |
| bb_reversion | buy close back inside lower Bollinger band, sell at upper band |
| combo | bullish engulfing/hammer + uptrend + RSI<65; exit on bearish candle or close below EMA50 |

All are long-only (spot). Signals execute at the **next** candle's open (no peeking at
future data). Stop-loss = 2x ATR, take-profit = 4x ATR by default. The first 200 candles are
used only to warm up the indicators and are not traded or counted in results.

## Reading results
- **Avg profit / day** — average profit per day for your capital, compared to your daily goal.
- **Max drawdown** — the worst fall from a peak. Could you stomach that loss?
- **Recent 30%** — results on only the newest part of history. Good overall but bad
  recently usually means it was luck (marked `luck?`).
- **Buy & hold** — if simply holding the coin did better, the strategy adds nothing.

## Exchanges and defaults
The default is **Indodax, BTC/IDR, 0.3% fee per side**: rupiah pairs need no USD conversion.
Other exchanges (Tokocrypto, Binance, OKX, Bybit, KuCoin, Kraken, Coinbase) are in the dropdown;
switching sets that exchange's currency and typical fee. Binance and some others block certain
countries (HTTP 451), so pick one that works from where the server runs.

Change the defaults per deployment with environment variables (see `compose.prod.yaml`):
`DEFAULT_EXCHANGE`, `DEFAULT_SYMBOL`, `DEFAULT_FEE`.

The symbol box suggests large, long-established coins (`backend/signals/markets.py`). That list
is a starting point, not a recommendation.

Not financial advice. Paper-trade before using real money.
