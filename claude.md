# Trading Software — Order-Flow Strategy Bot

A deterministic **order-flow trading bot** with an LLM safety check. It scores a
strict multi-timeframe **confluence checklist** (higher-timeframe trend, location in
value, liquidity sweep, **CVD/delta** order-flow confirmation, break of structure,
ATR risk, funding) and — when enough conditions line up — asks **Gemini to confirm
the same setup** before trading, long **or** short, on the **Binance USD-M Futures
Testnet** (fake funds, no KYC). Equity is tracked as a virtual **$10k paper account**.
Assets: BTC, ETH, SOL, BNB, XRP (perps vs USDT; only those with a backtested edge are
tradable — currently **BTC + BNB**). Every signal and trade is stored forever and
shown on a public dashboard — losers included.

## Transparency principle (INVIOLABLE)
- Every signal and trade is stored forever; nothing is deleted or hidden.
- Losing (red) trades stay as visible as winners. Trust depends on not hiding mistakes.

## Architecture
```
AWS EC2 · Frankfurt (every ~30 min)  ─►  Python bot (app/)         ─►  Binance Futures Testnet
   app.cli run (sync + trade)        klines/flow → confluence → Gemini confirm → order
                                                 │ writes
                                                 ▼
                                           Supabase (Postgres)  ◄─ reads ─ React dashboard (Vercel)
```
- **Bot:** Python, no web server. `app/cli.py` (`run` = blocking scheduler, sync+trade
  every `run_interval_minutes`). Runs on **EC2 in Frankfurt** (systemd `tradingbot`)
  because Binance blocks US IPs (HTTP 451). Deploy = `git pull` + `systemctl restart`.
- **DB:** Supabase Postgres (SQLite locally/tests). SQLAlchemy, `psycopg` driver.
- **Frontend:** React + Vite (`web/`) on Vercel, reads Supabase via `@supabase/supabase-js`
  (anon key, RLS read-only). Auto-deploys from `main`.
- **Broker:** Binance USD-M Futures Testnet (`app/broker/binance_futures.py`, signed
  HMAC, long+short, leverage, reduceOnly closes) behind the `Broker` interface
  (`app/broker/base.py`). Spot (`binance`) and Alpaca stay as alternatives; selected in
  `app/broker/__init__.py` by `settings.broker`.
- **Market data:** `app/sources/market_data.py` — Binance **mainnet public** klines
  (incl. taker-buy volume → CVD), depth, funding, open interest. Read from mainnet for
  real flow; orders execute on testnet.

## Strategy (`app/engine/strategy/`)
- `features.py` — pure functions: EMA, ATR, fractal swings, market structure, **CVD +
  divergence**, liquidity sweep, break of structure, volume profile/POC/value area, VWAP.
- `confluence.py` — `evaluate(snapshot, params)` → direction + strict pass/fail + the
  per-condition checklist + structure-based stop/target. **Single source of truth, shared
  live + backtest** (no logic drift). Live-only inputs (order-book imbalance, funding)
  don't count when absent.
- `engine.py` — `generate_signals()`: fetch multi-TF data, evaluate, log each directional
  signal as a `Prediction` (model `orderflow-v1`; confluence breakdown stored as JSON in
  `news_snapshot`). Mirrors the old predictor contract so the leaderboard keeps working.

## Trading logic (`app/engine/trader.py`)
1. `generate_signals()` → confluence per asset (deterministic; no LLM/news).
2. **Gate 1** (`decide()`): proceed only when the confluence **passes**; open long/short by
   direction, flip/close on the opposite setup. `max_open_positions` cap, idempotent
   (skip if a position/pending order exists).
3. **Gate 2** (`confirm_setup()`): for a new entry, ask the LLM (Gemini `judge_setup`) to
   confirm the *same* setup; trade only if its probability in the setup's direction ≥
   `llm_confirm_min`. **Fail-open** — no usable model / an error → trade on order-flow alone.
4. `size_by_risk()` — notional from the structure stop so each trade risks
   `risk_per_trade_pct` of a **virtual $10k paper account** (`virtual_account`, below),
   capped by per-position notional (× leverage) and margin.
5. Writes `Trade` (confluence + LLM rationale, stop/target) and `EquitySnapshot` (virtual).
6. `run_sync()` — reconcile positions (entry/qty/status), apply structure stop/take-profit,
   record equity, score matured signals (`run_evaluations`).

**Virtual paper account** (`virtual_account`): equity/cash/sizing derive from the bot's own
trades on a fixed `paper_starting_equity` ($10k) base — `equity = 10k + realized + unrealized`
— not the testnet's arbitrary fake balance, so the curve starts cleanly at $10k.

## Backtest (`app/engine/backtest.py`, CLI `backtest`) — the go-live gate
Walks the LTF bar by bar, calls the **same** `confluence.evaluate` on history up to each
bar (no lookahead), enters next-open, manages stop/target with taker fees + slippage, and
reports win rate / profit factor / expectancy (R) / max drawdown / return. Only deploy a
parameter set whose backtest is non-negative after fees. **Must run from an EU IP** (451 in
US). Order-book imbalance/funding aren't backtestable (no historical L2) — live-only.

## Data model (`app/models.py`)
- `Prediction` — signal: asset, model (`orderflow-v1`), direction, bullish/bearish_prob
  (= confluence score %), price, rationale, `news_snapshot` (**JSON confluence context**:
  checks, features, stop, target).
- `Evaluation` — 24h/7d accuracy of the signal (leaderboard).
- `Trade` — position lifecycle: side (buy=long / sell=short), status, qty, notional,
  entry/exit, pnl, pnl_pct, stop/take, close_reason, prediction_id, model, rationale.
- `EquitySnapshot` — virtual equity/cash/buying_power over time ($10k paper base). All times
  **naive UTC** (`utcnow()`).

## CLI (`app/cli.py`)
- `sync` — reconcile + exits + equity + scoring (runs first).
- `trade [--dry-run]` — generate signals and trade (`--dry-run` sends nothing).
- `backtest [--asset --days --htf --mtf --ltf]` — validate the strategy on history.
- `reset [--yes]` — wipe trades/predictions/equity for a clean $10k restart (no `--yes` = dry count).
- `initdb` — create tables. `run` — blocking local scheduler. `predict` — legacy LLM leaderboard.

## Keys (free, no KYC, in `.env`, NEVER in git)
`BINANCE_FUTURES_API_KEY`, `BINANCE_FUTURES_SECRET_KEY` (separate signup at
**testnet.binancefuture.com**), `DATABASE_URL` (Supabase Postgres).
`BINANCE_FUTURES_TESTNET=true` (default). `GEMINI_API_KEY` powers the **trade-confirmation
gate** (without it the bot fails open to order-flow-only) and the optional accuracy
leaderboard; `FINNHUB_API_KEY` is only for the leaderboard. Frontend has only the public
`VITE_SUPABASE_ANON_KEY` (RLS read-only).

## Conventions
- Times always naive UTC via `app.models.utcnow()`.
- External HTTP via `httpx`; data sources isolated in `app/sources/`.
- Broker only via `Broker`; LLM only via `LLMProvider` (lazy SDK imports).
- Strategy math lives in pure functions (`app/engine/strategy/features.py`) so live and
  backtest share it. Everything tunable goes in `app/config.py`.
- Tests run on in-memory SQLite; network mocked with `respx`, broker faked
  (`tests/conftest.py`). `pytest` must stay green.
