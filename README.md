# 📈 Order-Flow Strategy Bot

A deterministic trading bot that scores a strict **order-flow confluence checklist**
every ~30 minutes, then asks **Gemini to confirm the same setup**, and places **real
trades on the [Binance USD-M Futures Testnet](https://testnet.binancefuture.com)** (fake
funds, no KYC) — long **or** short — *only when both agree*. Equity is tracked as a
virtual **$10k paper account**. Every trade, winner or loser, stays public on a dashboard
together with the exact checklist — and the model's verdict — that drove it.

> **Transparency is the point.** Nothing is ever deleted or hidden — losing trades are
> as visible as winners. The credibility of the project depends on not sweeping mistakes
> under the rug.

## How it works

```
AWS EC2 · Frankfurt (every ~30m)  ──►  Python bot (app/)            ──►  Binance Futures Testnet
  app.cli run  (sync + trade)         klines + order flow (CVD/delta)        orders, positions, equity
                                       confluence → Gemini confirm → order
                                              │ writes
                                              ▼
                                       Supabase (Postgres)  ◄── reads ──  React dashboard (Vercel)

The bot runs in the EU because Binance blocks US IPs (HTTP 451).
```

Each run, for every asset, it builds a multi-timeframe picture and checks a strict
checklist — and **only trades when enough of it passes**:

1. **Trend** — higher-timeframe direction (4h/1d); trade only with it.
2. **Location** — price at value (POC / VWAP / value area), not mid-range chop.
3. **Liquidity sweep** — a stop-run beyond a prior swing that gets reclaimed.
4. **Order flow** — CVD/delta confirmation (cumulative volume delta divergence or a
   strong aggressive-buy/sell push). *This is the heart of the strategy.*
5. **Break of structure** — the reversal is confirmed on the lower timeframe.
6. **Risk** — sane ATR volatility, price not over-extended from the trend.
7. **Funding** — not crowding the side we're taking (futures).

Stops are placed at structure (beyond the swept level / ATR), targets at an R-multiple,
and each trade risks a fixed fraction of a **virtual $10k paper account**. It shorts as
readily as it goes long.

**Second gate — LLM confirmation.** When the checklist passes, the bot sends the *same*
quantitative setup (direction, which checks passed, order-flow features, stop/target) to
**Gemini** and opens the trade only if the model independently agrees with enough conviction
(`llm_confirm_min`). If Gemini is unavailable it **fails open** — trading on the order-flow
signal alone. The model's verdict is stored on the trade alongside the checklist.

## Validate before trusting it — backtest
The live decision and the backtest call the **same** confluence code, so you can test it
on history first:
```bash
python -m app.cli backtest --asset BTC --days 365      # win rate, profit factor, R, drawdown
```
Reports land in `data/backtests/`. Only deploy a parameter set whose backtest is positive
after fees. (Run it from an EU IP — Binance returns 451 in the US.)

## Tracked assets
BTC · ETH · SOL · BNB · XRP (perps vs USDT). Edit `ASSETS` in `app/config.py`. Only coins
with a backtested edge are **tradable** (currently **BTC + BNB**); the rest stay tracked for
the leaderboard (`tradable=False`).

## Quick start (local, EU IP)
```bash
pip install -r requirements.txt
cp .env.example .env          # fill in the futures testnet keys (free, no KYC)
python -m app.cli initdb      # create tables (SQLite by default)
python -m app.cli backtest --asset BTC --days 180   # sanity-check the edge
python -m app.cli trade --dry-run   # see what it WOULD do, places nothing
python -m app.cli trade       # place testnet futures trades
pytest                        # run the test suite
```

Keys (free, no credit card, no identity verification):
- `BINANCE_FUTURES_API_KEY` / `BINANCE_FUTURES_SECRET_KEY` —
  https://testnet.binancefuture.com (log in → API key; pre-funded fake balance).
- `DATABASE_URL` — Supabase Postgres (Session pooler URI) for production; omit for local SQLite.
- *(recommended)* `GEMINI_API_KEY` — powers the **trade-confirmation gate** (without it the
  bot fails open to order-flow-only) and the optional accuracy leaderboard.
- *(optional)* `FINNHUB_API_KEY` — only for the news accuracy leaderboard (`app.cli predict`).

## Deploy (free stack)
1. **Binance Futures Testnet** — log in at testnet.binancefuture.com, create API keys.
2. **Supabase** — create a project, run [`supabase/schema.sql`](supabase/schema.sql) in the
   SQL editor (tables + read-only RLS). Copy the **Session pooler** connection string and anon key.
3. **Bot host (EU)** — run the bot where Binance is reachable (e.g. an EC2 box in Frankfurt)
   as a systemd service running `python -m app.cli run`. Deploy updates with
   `git pull && sudo systemctl restart tradingbot`.
4. **Vercel** — import the repo, set **Root Directory** to `web`, add `VITE_SUPABASE_URL`
   and `VITE_SUPABASE_ANON_KEY`, deploy. Auto-deploys from `main`. See [`web/README.md`](web/README.md).

## Strategy & risk (all in `app/config.py`, overridable via env)
| Setting | Default | Meaning |
|---|---|---|
| `strategy_htf` / `mtf` / `ltf` | 4h / 1h / 15m | trend / structure / decision timeframes |
| `min_confluence` | 5 | how many checklist items must pass (raise it = stricter) |
| `strategy_reward_risk` | 2.0 | take-profit at this R multiple of the stop |
| `paper_starting_equity` | 10_000 | virtual paper-account base; equity & sizing start here |
| `risk_per_trade_pct` | 0.005 | risk ~0.5% of the $10k paper account per trade |
| `max_position_pct` | 0.10 | per-position notional cap (× leverage) of equity |
| `max_open_positions` | 5 | concurrent position cap |
| `cash_buffer_pct` | 0.10 | never deploy this fraction of margin |
| `futures_leverage` | 3 | low leverage; structure stops sit inside liquidation |
| `allow_short` | true | take shorts as well as longs |
| `require_llm_confirmation` | true | Gemini must confirm a setup before trading (else fail open) |
| `llm_confirm_min` | 60 | min Gemini probability (in the setup's direction) to confirm |

> **Honest note:** microstructure edges are thin and don't always beat fees. The backtest
> is the gate, and the testnet validates the *process*, not a guaranteed profit. Order-book
> imbalance and live funding can't be backtested (no historical L2) — they're live-only filters.

## Safety: testnet → real money
The bot trades on the **Futures Testnet by default** (`BINANCE_FUTURES_TESTNET=true`) —
fake funds, zero real risk. Trading real money is a deliberate switch: set it to `false`
and use mainnet keys. Spot (`BROKER=binance`) and Alpaca (`BROKER=alpaca`) brokers remain
as alternatives.

## Project layout
```
app/
  config.py      # assets, strategy params, risk, settings
  models.py      # DB models: Prediction/Evaluation (signals) + Trade/EquitySnapshot
  sources/       # market_data (klines/depth/funding + CVD), prices, news
  engine/
    strategy/    # features, confluence (single source of truth), engine (live signals)
    backtest.py  # historical validation (same confluence code, no lookahead)
    trader.py    # confluence -> risk-sized long/short orders
    evaluator.py # scores matured signals
  broker/        # binance_futures + binance (spot) + alpaca, behind a Broker interface
  llm/           # pluggable AI provider (trade-confirmation gate + leaderboard)
  cli.py         # `trade`, `sync`, `backtest`, `reset`, `initdb`, `run`, `predict`
web/             # React + Vite dashboard (deployed to Vercel)
supabase/        # schema.sql (tables + RLS)
```
Architecture & conventions: [claude.md](claude.md).
```bash
python seed_demo.py   # optional: fake trades/signals/equity to preview the dashboard
```
