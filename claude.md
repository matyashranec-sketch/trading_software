# Trading Software — News-Driven Trading Bot

AI čte čerstvé news, vydá bullish/bearish signál s mírou jistoty, a **když jsou
news čerstvé a model je dost přesvědčený, udělá reálný (zatím paper) obchod** na
Alpaca. Každý obchod i signál se ukládá natrvalo a je transparentně vidět na
veřejném dashboardu — i ztrátové.

## Princip transparentnosti (NEPORUŠITELNÉ)
- Každý signál i obchod se ukládá natrvalo.
- Nic se nikdy nemaže ani neskrývá — ani ztrátové obchody.
- Špatné (červené) jsou stejně viditelné jako dobré (zelené).
- Důvěryhodnost projektu stojí na tom, že se chyby nezametají pod koberec.

## Architektura
```
GitHub Actions (cron, každé 2h)  ─►  Python bot (app/)        ─►  Alpaca (paper)
   app.cli sync  + app.cli trade        news + cena + Gemini + risk
                                              │ zapisuje
                                              ▼
                                        Supabase (Postgres)  ◄─ čte ─ React dashboard (Vercel)
```
- **Bot:** Python, bez webového serveru. Spouští se přes `app/cli.py`.
- **Heartbeat:** GitHub Actions cron (`.github/workflows/bot.yml`), každé 2 h.
- **DB:** Supabase Postgres (lokálně SQLite). SQLAlchemy, driver `psycopg`.
- **Frontend:** React + Vite (`web/`) na Vercelu, čte Supabase přímo přes
  `@supabase/supabase-js` (anon klíč, RLS jen pro čtení).
- **AI:** Google Gemini (free), provider je pluggable (`app/llm/base.py`).
- **Broker:** Alpaca přes `alpaca-py`, schované za rozhraním `Broker`
  (`app/broker/base.py`) → engine ani testy nezávisí na SDK.

## Obchodní logika (`app/engine/trader.py`)
1. `generate_signals()` — pro každé aktivum: cena + news → **obchodní model**
   (první dostupný Gemini, nebo `trading_model`) → uloží `Prediction`.
2. **Gate** (`decide()`): obchoduj jen když jsou **čerstvé news**
   (≤ `news_fresh_hours`) **a** `confidence ≥ min_confidence`. Jinak hold.
3. Bullish → otevři/drž long; bearish → zavři long (short jen když `allow_short`).
   Sizing z equity (`max_position_pct`, volitelně škálováno confidencí), limity
   `max_open_positions` a `cash_buffer_pct`. Akcie respektují obchodní hodiny,
   krypto jede 24/7. **Idempotence:** neotevírej, když už je pozice / čekající order.
4. Zapíše `Trade` (s rationale + order id) a `EquitySnapshot`.
5. `run_sync()` — sesouhlasí otevřené obchody s Alpaca (entry/qty/status),
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

## Klíče (free, do `.env`, NIKDY do gitu)
`GEMINI_API_KEY`, `FINNHUB_API_KEY`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`,
`DATABASE_URL` (Supabase Postgres). `LIVE_TRADING=false` = paper (default).
Frontend má jen veřejný `VITE_SUPABASE_ANON_KEY` (RLS = read-only).

## Bezpečnost
- Default **paper** (virtuální peníze). Ostré obchodování až vědomě:
  `LIVE_TRADING=true` + live klíče.
- Secrets bota = GitHub Actions secrets. Plný `DATABASE_URL` a Alpaca klíče
  nikdy ve frontendu.

## Konvence pro vývoj
- Časy vždy naivní UTC přes `app.models.utcnow()`.
- Externí HTTP přes `httpx`. Zdroje dat v `app/sources/`, izolované za funkcemi.
- LLM volat jen přes `LLMProvider` (`app/llm/base.py`); broker jen přes `Broker`
  (`app/broker/base.py`) — SDK importovat líně uvnitř metod.
- Vše konfigurovatelné patří do `app/config.py`.
- Testy běží na SQLite in-memory; broker/LLM se mockují (viz `tests/conftest.py`
  `FakeBroker`). `pytest` musí být zelený.
