# 📈 News-Driven Stock Prediction Tracker

AI čte čerstvé news a předpovídá, jestli **TSLA, BTC, AAPL, NVDA, MSFT** půjdou
nahoru (bullish 🟢) nebo dolů (bearish 🔴). Každá predikce se uloží, po vypršení
horizontu (24h a 7d) se ověří proti reálné ceně a **vše je trvale a transparentně**
vidět na veřejném leaderboardu. Žádná predikce se nikdy nemaže ani neskrývá.

## Co to umí
- 🗞️ Tahá news z Finnhubu, cenu BTC z CoinGecka
- 🤖 Nechá **víc Gemini modelů** promyslet bullish/bearish % + zdůvodnění
- 💾 Uloží každou predikci + 2 vyhodnocení (24h, 7d)
- ⏱️ Automaticky vyhodnotí po vypršení horizontu (trefa/miss)
- 📊 Leaderboard: overall + per-asset + per-model, last 30/90 dní, best/worst model

## Rychlý start
```bash
pip install -r requirements.txt
copy .env.example .env      # Windows  (na macOS/Linux: cp)
# do .env doplň klíče (oba jsou ZDARMA, bez platební karty):
#   FINNHUB_API_KEY  ->  https://finnhub.io
#   GEMINI_API_KEY   ->  https://aistudio.google.com/app/apikey
uvicorn app.main:app --reload
```
- Leaderboard: <http://localhost:8000/>
- Log všech predikcí: <http://localhost:8000/predictions>

> Bez klíčů appka naběhne taky — leaderboard bude prázdný a ukáže návod, co doplnit.

## Jak vytvořit predikci hned
Na webu klikni **„Run now"**, nebo:
```bash
curl -X POST http://localhost:8000/api/run-predictions
```
Jinak se predikce generují automaticky 1× denně a vyhodnocují každou hodinu.

## Testy
```bash
pytest
```

## Struktura
```
app/
  config.py      # sledovaná aktiva, horizonty, modely, nastavení
  models.py      # DB modely (Prediction, Evaluation)
  sources/       # Finnhub (news+ceny), CoinGecko (BTC)
  llm/           # pluggable AI provider (Gemini)
  engine/        # predictor, evaluator, scoreboard
  web/           # šablony + statika (leaderboard, log)
  scheduler.py   # denní predikce + hodinové vyhodnocení
  main.py        # FastAPI app
```
Detailní popis fungování viz [claude.md](claude.md).
