# Trading Software — News-Driven Trading Bot

AI čte čerstvé crypto news, vydá bullish/bearish signál s mírou jistoty, a **když
jsou news čerstvé a model je dost přesvědčený, udělá reálný obchod** na **Binance
Spot Testnetu** (fake peníze, bez KYC). Aktiva: BTC, ETH, SOL, BNB, XRP (vs USDT).
Každý obchod i signál se ukládá natrvalo a je transparentně vidět na veřejném
dashboardu — i ztrátové.

## Princip transparentnosti (NEPORUŠITELNÉ)
- Každý signál i obchod se ukládá natrvalo.
- Nic se nikdy nemaže ani neskrývá — ani ztrátové obchody.
- Špatné (červené) jsou stejně viditelné jako dobré (zelené).
- Důvěryhodnost projektu stojí na tom, že se chyby nezametají pod koberec.

## Architektura
```
Fly.io · Frankfurt (každé ~2h)  ─►  Python bot (app/)        ─►  Binance Spot Testnet
   app.cli run (sync + trade)        news + cena + Gemini + risk
                                              │ zapisuje
                                              ▼
                                        Supabase (Postgres)  ◄─ čte ─ React dashboard (Vercel)
```
- **Bot:** Python, bez webového serveru. Spouští se přes `app/cli.py` (`run` = blokující
  scheduler, cyklus sync+trade každé `run_interval_hours`).
- **Heartbeat:** běží na **Fly.io ve Frankfurtu** (`Dockerfile` + `fly.toml`), protože
  Binance blokuje US IP GitHub Actions (HTTP 451). GitHub Actions
  (`.github/workflows/fly-deploy.yml`) jen **builduje a deployuje** na Fly; secrets se
  pushnou na Fly z GitHub secrets (`FLY_API_TOKEN`). `bot.yml` zůstává jen pro ruční běh.
- **DB:** Supabase Postgres (lokálně SQLite). SQLAlchemy, driver `psycopg`.
- **Frontend:** React + Vite (`web/`) na Vercelu, čte Supabase přímo přes
  `@supabase/supabase-js` (anon klíč, RLS jen pro čtení).
- **AI:** Google Gemini (free), provider je pluggable (`app/llm/base.py`).
- **Broker:** Binance Spot Testnet (REST, podepsané HMAC) v `app/broker/binance.py`,
  schované za rozhraním `Broker` (`app/broker/base.py`) → engine ani testy nezávisí
  na konkrétní burze. Alpaca zůstává jako alternativa (`BROKER=alpaca`). Výběr v
  `app/broker/__init__.py` podle `settings.broker`.
- **Ceny:** Binance mainnet veřejné ticker API (CoinGecko fallback); news z Finnhubu
  filtrované podle coinu (`asset.news_terms`).

## Obchodní logika (`app/engine/trader.py`)
1. `generate_signals()` — pro každé aktivum: cena + news → **obchodní model**
   (první dostupný Gemini, nebo `trading_model`) → uloží `Prediction`.
2. **Gate** (`decide()`): obchoduj jen když jsou **čerstvé news**
   (≤ `news_fresh_hours`) **a** `confidence ≥ min_confidence`. Jinak hold.
3. Bullish → otevři/drž long; bearish → zavři long (short jen když `allow_short`).
   Sizing z equity (`max_position_pct`, volitelně škálováno confidencí), limity
   `max_open_positions` a `cash_buffer_pct`. Krypto jede 24/7 (`is_market_open()`
   vždy True). **Idempotence:** neotevírej, když už je pozice / čekající order.
4. Zapíše `Trade` (s rationale + order id) a `EquitySnapshot`.
5. `run_sync()` — sesouhlasí otevřené obchody s brokerem (entry/qty/status),
   aplikuje volitelný stop-loss/take-profit, zapíše equity a doskóruje dozrálé
   signály (`run_evaluations`).

## Datový model (`app/models.py`)
- `Prediction` — signál: asset, model, direction, bullish/bearish_prob,
  price_at_prediction, rationale, news_snapshot (JSON headlines). `confidence`.
- `Evaluation` — skóre signálu na horizontu 24h/7d (accuracy leaderboard).
- `Trade` — životní cyklus pozice: side, status (submitted/open/closed/canceled),
  qty, notional, entry/exit_price, pnl, pnl_pct, stop/take, close_reason,
  alpaca_order_id, prediction_id (FK), model, rationale.
- `EquitySnapshot` — equity/cash/buying_power v čase (equity křivka).
- Všechny časy **naivní UTC** přes `models.utcnow()`.

## CLI (`app/cli.py`)
- `sync` — reconcile + exity + equity + skórování (běží jako první v cronu).
- `trade [--dry-run]` — generuj signály a obchoduj (`--dry-run` nic neodešle).
- `predict` — přegeneruje multi-model accuracy leaderboard (mimo obchodní cestu).
- `initdb` — vytvoří tabulky. `run` — blokující lokální scheduler.

## Klíče (free, bez KYC, do `.env`, NIKDY do gitu)
`GEMINI_API_KEY`, `FINNHUB_API_KEY`, `BINANCE_API_KEY`, `BINANCE_SECRET_KEY`
(testnet.binance.vision), `DATABASE_URL` (Supabase Postgres). `BINANCE_TESTNET=true`
= testnet (default). Frontend má jen veřejný `VITE_SUPABASE_ANON_KEY` (RLS = read-only).

## Bezpečnost
- Default **Binance testnet** (fake peníze, bez KYC). Ostré peníze až vědomě:
  `BINANCE_TESTNET=false` + mainnet klíče.
- Secrets bota = GitHub Actions secrets. Plný `DATABASE_URL` a Binance klíče
  nikdy ve frontendu.

## Konvence pro vývoj
- Časy vždy naivní UTC přes `app.models.utcnow()`.
- Externí HTTP přes `httpx`. Zdroje dat v `app/sources/`, izolované za funkcemi.
- LLM volat jen přes `LLMProvider` (`app/llm/base.py`); broker jen přes `Broker`
  (`app/broker/base.py`) — SDK importovat líně uvnitř metod.
- Vše konfigurovatelné patří do `app/config.py`.
- Testy běží na SQLite in-memory; broker/LLM se mockují (viz `tests/conftest.py`
  `FakeBroker`). `pytest` musí být zelený.
