# 📈 News-Driven Trading Bot

An AI reads fresh market news every ~2 hours and places **real (paper) trades**
on [Alpaca](https://alpaca.markets) — but only when there's fresh news *and* it's
confident. Every trade, winner or loser, stays public on a dashboard together
with the reasoning and the headlines that drove it.

> **Transparency is the point.** Nothing is ever deleted or hidden — losing
> trades are as visible as winners. The credibility of the project depends on not
> sweeping mistakes under the rug.

## How it works

```
GitHub Actions (every 2h)  ──►  Python bot (app/)              ──►  Alpaca (paper): orders, positions, equity
  python -m app.cli sync          news (Finnhub) + price (Alpaca)
  python -m app.cli trade         Gemini signal + risk/sizing
                                          │ writes
                                          ▼
                                   Supabase (Postgres)   ◄── reads ──  React dashboard (Vercel)
                                   trades / signals / equity            @supabase/supabase-js (anon, read-only)
```

Each run: fetch news → ask Gemini for a bullish/bearish call with confidence →
**trade only if** the news is fresh (≤ `news_fresh_hours`) **and** confidence ≥
`min_confidence`. Otherwise it holds. Stocks respect market hours; crypto (BTC)
trades 24/7. Positions are sized as a fraction of equity, capped, and kept within
a cash buffer.

## Tracked assets
TSLA · AAPL · NVDA · MSFT (stocks) · BTC (crypto). Edit `ASSETS` in `app/config.py`.

## Quick start (local)
```bash
pip install -r requirements.txt
cp .env.example .env          # fill in the keys below (all free)
python -m app.cli initdb      # create tables (SQLite by default)
python -m app.cli trade --dry-run   # see what it WOULD do, places nothing
python -m app.cli trade       # place paper trades
pytest                        # run the test suite
```

Keys (all free, no credit card):
- `GEMINI_API_KEY` — https://aistudio.google.com/app/apikey
- `FINNHUB_API_KEY` — https://finnhub.io
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — https://alpaca.markets (Paper Trading → API Keys)

## Deploy (free stack)
1. **Alpaca** — create a free account, grab **paper** API keys.
2. **Supabase** — create a project, open the SQL editor and run
   [`supabase/schema.sql`](supabase/schema.sql) (creates tables + read-only RLS).
   Copy the Postgres connection string and the public anon key.
3. **GitHub Actions** — add repo secrets `GEMINI_API_KEY`, `FINNHUB_API_KEY`,
   `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `DATABASE_URL` (the Supabase connection
   string). The workflow in [`.github/workflows/bot.yml`](.github/workflows/bot.yml)
   runs `sync` + `trade` every 2 hours (and on demand via *Run workflow*).
4. **Vercel** — import the repo, set **Root Directory** to `web`, add env vars
   `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`, deploy. See [`web/README.md`](web/README.md).

## Strategy & risk (all in `app/config.py`)
| Setting | Default | Meaning |
|---|---|---|
| `min_confidence` | 75 | trade only when the model is at least this sure |
| `require_fresh_news` / `news_fresh_hours` | true / 24 | only act on recent news |
| `max_position_pct` | 0.10 | target size per position (of equity) |
| `max_open_positions` | 5 | concurrent position cap |
| `cash_buffer_pct` | 0.10 | never deploy this fraction of cash |
| `allow_short` | false | bearish closes longs; shorting off by default |
| `stop_loss_pct` / `take_profit_pct` | 0 / 0 | optional hard exits (0 = off) |

Override any of them via environment variables (e.g. `MIN_CONFIDENCE=70`).

## Safety: paper → live
The bot trades **paper money by default** (`LIVE_TRADING=false`). Going live is a
deliberate switch: set `LIVE_TRADING=true` **and** use live Alpaca keys. Until
then there is no real money at risk.

## Project layout
```
app/
  config.py      # assets, models, trading risk, settings
  models.py      # DB models: Prediction/Evaluation (signals) + Trade/EquitySnapshot
  sources/       # Alpaca prices (+ Finnhub/CoinGecko fallback), Finnhub news
  llm/           # pluggable AI provider (Gemini)
  broker/        # Alpaca trading wrapper behind a Broker interface
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
