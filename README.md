# 📈 News-Driven Trading Bot

An AI reads fresh crypto news every ~2 hours and places **real trades on the
[Binance Spot Testnet](https://testnet.binance.vision)** (fake funds, no KYC) —
but only when there's fresh news *and* it's confident. Every trade, winner or
loser, stays public on a dashboard together with the reasoning and the headlines
that drove it.

> **Transparency is the point.** Nothing is ever deleted or hidden — losing
> trades are as visible as winners. The credibility of the project depends on not
> sweeping mistakes under the rug.

## How it works

```
Fly.io · Frankfurt (every ~2h)  ──►  Python bot (app/)            ──►  Binance Testnet: orders, balances
  app.cli run  (sync + trade)         news (Finnhub) + price (Binance)
                                       Gemini signal + risk/sizing
                                              │ writes
                                              ▼
                                       Supabase (Postgres)  ◄── reads ──  React dashboard (Vercel)
                                       trades / signals / equity          @supabase/supabase-js (anon, read-only)

GitHub Actions only builds & deploys the bot to Fly (Binance blocks GitHub's US IPs → HTTP 451).
```

Each run: fetch news → ask Gemini for a bullish/bearish call with confidence →
**trade only if** the news is fresh (≤ `news_fresh_hours`) **and** confidence ≥
`min_confidence`. Otherwise it holds. Crypto trades 24/7. Positions are sized as a
fraction of equity, capped, and kept within a cash buffer.

## Tracked assets
BTC · ETH · SOL · BNB · XRP (traded vs USDT). Edit `ASSETS` in `app/config.py`.

## Quick start (local)
```bash
pip install -r requirements.txt
cp .env.example .env          # fill in the keys below (all free, no KYC)
python -m app.cli initdb      # create tables (SQLite by default)
python -m app.cli trade --dry-run   # see what it WOULD do, places nothing
python -m app.cli trade       # place testnet trades
pytest                        # run the test suite
```

Keys (all free, no credit card, no identity verification):
- `GEMINI_API_KEY` — https://aistudio.google.com/app/apikey
- `FINNHUB_API_KEY` — https://finnhub.io
- `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` — https://testnet.binance.vision
  (log in with GitHub → *Generate HMAC_SHA256 Key*)

## Deploy (free stack)
1. **Binance Testnet** — log in at testnet.binance.vision, generate API keys
   (fake balances are pre-funded; no KYC).
2. **Supabase** — create a project, open the SQL editor and run
   [`supabase/schema.sql`](supabase/schema.sql) (creates tables + read-only RLS).
   Copy the **Session pooler** Postgres connection string and the public anon key.
3. **GitHub secrets** — add `GEMINI_API_KEY`, `FINNHUB_API_KEY`,
   `BINANCE_API_KEY`, `BINANCE_SECRET_KEY`, `DATABASE_URL` (Supabase pooler string),
   plus `FLY_API_TOKEN` (next step). The deploy workflow pushes these to Fly.
4. **Fly.io** (runs the bot in the EU, where Binance is reachable) — create a free
   account, then a deploy token (*Tokens → Create deploy token*) and add it as the
   GitHub secret `FLY_API_TOKEN`. The workflow
   [`.github/workflows/fly-deploy.yml`](.github/workflows/fly-deploy.yml) creates the
   app (`fra` / Frankfurt), pushes the secrets, and deploys on every push to `main`
   (and via *Run workflow*). The bot then runs `sync + trade` every ~2h on Fly.
   App name lives in [`fly.toml`](fly.toml) — change it if Fly says it's taken.
5. **Vercel** — import the repo, set **Root Directory** to `web`, add env vars
   `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`, deploy. See [`web/README.md`](web/README.md).

## Strategy & risk (all in `app/config.py`)
| Setting | Default | Meaning |
|---|---|---|
| `min_confidence` | 75 | trade only when the model is at least this sure |
| `require_fresh_news` / `news_fresh_hours` | true / 24 | only act on recent news |
| `max_position_pct` | 0.10 | target size per position (of equity) |
| `max_open_positions` | 5 | concurrent position cap |
| `cash_buffer_pct` | 0.10 | never deploy this fraction of cash |
| `stop_loss_pct` / `take_profit_pct` | 0 / 0 | optional hard exits (0 = off) |

Override any of them via environment variables (e.g. `MIN_CONFIDENCE=80`).

On the **free Gemini tier** the bot retries transient `429` (rate limit) and
`503` (overloaded) errors with exponential backoff, spaces calls out, and caches
the model list, so a burst of per-asset requests stays reliable on a single key
(`gemini_max_retries`, `llm_min_interval_seconds`, … in `app/config.py`).

## Safety: testnet → real money
The bot trades on the **Binance Spot Testnet by default** (`BINANCE_TESTNET=true`)
— fake funds, zero real risk. Trading real money is a deliberate switch: set
`BINANCE_TESTNET=false` and use mainnet keys. (An Alpaca stock broker is also
included as an alternative — set `BROKER=alpaca`.)

## Project layout
```
app/
  config.py      # assets, models, trading risk, settings
  models.py      # DB models: Prediction/Evaluation (signals) + Trade/EquitySnapshot
  sources/       # Binance/CoinGecko prices, Finnhub news (coin-filtered)
  llm/           # pluggable AI provider (Gemini)
  broker/        # Binance (testnet) + Alpaca, behind a common Broker interface
  engine/        # predictor (signals), trader (orders), evaluator, scoreboard
  cli.py         # `trade`, `sync`, `predict`, `initdb`, `run`
  scheduler.py   # optional local loop (production uses GitHub Actions)
web/             # React + Vite dashboard (deployed to Vercel)
supabase/        # schema.sql (tables + RLS)
.github/workflows/bot.yml   # the 2-hourly heartbeat
```
Architecture & conventions: [claude.md](claude.md).
```bash
python seed_demo.py   # optional: fake trades/signals/equity to preview the dashboard
```
