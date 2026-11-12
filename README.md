# Crypto Signals

Analyzes crypto candle history, generates BUY/SELL signals, backtests them
(with fees, stop-loss and take-profit) and reports profit in **rupiah per day**.

- `backend/` — Python: `trader.py` (indicators, strategies, backtester, CLI) + `app.py` (Flask API)
- `frontend/` — Vite dashboard (candlestick chart with buy/sell markers, stats, trades, strategy comparison)
- `Dockerfile` — builds the dashboard and serves it together with the API on one port

## Run with Docker (easiest)
```
docker compose up --build
```
Open http://localhost:8000. Downloaded candles are cached in a Docker volume for 1 hour.

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
| `/api/health` | `{"ok": true}` |

Example: `curl "http://localhost:8000/api/signal?symbol=ETH/USDT&timeframe=1d&strategy=ema_cross"`

## Command line (still works)
```
cd backend
python trader.py compare --capital-idr 50000000
python trader.py backtest --strategy combo --timeframe 4h --chart
python trader.py signal --strategy combo --timeframe 4h
python trader.py compare --exchange indodax --symbol BTC/IDR --fee 0.003
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
future data). Stop-loss = 2x ATR, take-profit = 4x ATR by default.

## Reading results
- **Avg profit / day** — average profit per day for your capital, compared to your daily goal.
- **Max drawdown** — the worst fall from a peak. Could you stomach that loss?
- **Recent 30%** — results on only the newest part of history. Good overall but bad
  recently usually means it was luck (marked `luck?`).
- **Buy & hold** — if simply holding the coin did better, the strategy adds nothing.

Not financial advice. Paper-trade before using real money.
