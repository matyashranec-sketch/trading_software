# Trading Software — News-Driven Stock Prediction Tracker

AI čte čerstvé news a předpovídá, jestli sledovaná aktiva půjdou nahoru (bullish)
nebo dolů (bearish). Každá predikce se uloží, po vypršení horizontu se ověří proti
reálné ceně, a vše je trvale a transparentně vidět na veřejném leaderboardu.

## Princip transparentnosti (NEPORUŠITELNÉ)
- Každá predikce se ukládá natrvalo.
- Žádná predikce se nikdy nemaže ani neskrývá — ani ty špatné.
- Špatné predikce (červené) jsou stejně viditelné jako správné (zelené).
- Důvěryhodnost projektu stojí na tom, že se chyby nezametají pod koberec.

## Sledovaná aktiva (monitor only)
| Symbol | Název | Typ |
|--------|-------|-----|
| TSLA | Tesla | akcie |
| AAPL | Apple | akcie |
| NVDA | NVIDIA | akcie |
| MSFT | Microsoft | akcie |
| BTC | Bitcoin | krypto |

## Jak vzniká predikce  (`app/engine/predictor.py`)
1. Stáhnou se čerstvé news k aktivu (Finnhub company-news pro akcie, Finnhub crypto news pro BTC).
2. Zjistí se aktuální cena (`price_at_prediction`).
3. Každý nakonfigurovaný AI model dostane news a vrátí `bullish_prob`, `bearish_prob` a `rationale`.
4. Uloží se `Prediction` + dvě `Evaluation` (horizonty 24h a 7d) ve stavu `pending`.

## Jak se predikce ověří  (`app/engine/evaluator.py`)
- Každou hodinu běží evaluator: najde `Evaluation`, které dozrály (`target_eval_time <= teď`).
- Stáhne aktuální cenu → `price_at_eval`.
- `actual_direction` = bullish když cena stoupla, bearish když klesla, push když stejná.
- `is_correct` = (`direction == actual_direction`). Push se nepočítá do accuracy, ale zůstává vidět.

## Architektura
- **Stack:** Python + FastAPI + SQLite + APScheduler. Frontend = Jinja2 + trochu JS.
- **AI:** Google Gemini (free tier, klíč z AI Studio, bez karty). Provider je pluggable
  (`app/llm/base.py`) → jde přepnout na Ollama/Groq beze změny zbytku appky.
- **Více modelů:** porovnává se víc Gemini variant → "accuracy by model" + best/worst model.
- **Data:** Finnhub (news + ceny akcií), CoinGecko (cena BTC).
- **Horizonty:** 24h i 7d současně (každá predikce má obě vyhodnocení).

## Datový model  (`app/models.py`)
- `Prediction`: id, created_at, asset, model, direction, bullish_prob, bearish_prob,
  price_at_prediction, rationale, news_snapshot (JSON headlines).
- `Evaluation`: id, prediction_id, horizon, target_eval_time, status, evaluated_at,
  price_at_eval, actual_direction, is_correct.
- Všechny časy jsou **naivní UTC** (kvůli SQLite). Pomocná funkce `models.utcnow()`.

## Leaderboard / scoreboard  (`app/engine/scoreboard.py`)
- Overall accuracy + per-asset (TSLA/BTC/AAPL/NVDA/MSFT) + per-model.
- Last 30 days, last 90 days. Best/worst performing model.
- Počítá se zvlášť pro horizont 24h a 7d.
- Zelená = trefa, červená = miss, šedá = ještě nevyhodnoceno (pending).

## Klíče (free, do `.env`, nikdy ne do gitu)
- `FINNHUB_API_KEY` — https://finnhub.io
- `GEMINI_API_KEY` — https://aistudio.google.com/app/apikey
- Bez klíčů appka naběhne taky — leaderboard je prázdný + hláška.

## Spuštění
```
pip install -r requirements.txt
copy .env.example .env   # a doplň klíče
uvicorn app.main:app --reload
```
Leaderboard: http://localhost:8000/ · Log predikcí: http://localhost:8000/predictions

## Ruční spuštění predikce
`POST /api/run-predictions` (tlačítko "Run now" na webu) — nečeká se na denní scheduler.

## Konvence pro vývoj
- Časy vždy naivní UTC přes `app.models.utcnow()`.
- Externí HTTP přes `httpx`. Zdroje dat v `app/sources/`, izolované za funkcemi.
- LLM volat jen přes `LLMProvider` interface (`app/llm/base.py`) — nevolat SDK přímo z enginu.
- Vše konfigurovatelné patří do `app/config.py`.
