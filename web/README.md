# Dashboard (React + Vite)

Public, read-only dashboard for the trading bot. It reads straight from Supabase
with the anon key (Row Level Security keeps it read-only) — there is no backend.

## Local dev
```bash
cd web
npm install
cp .env.example .env     # fill in VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
npm run dev
```

## Deploy to Vercel
1. New Project → import this repo.
2. Set **Root Directory** to `web`.
3. Framework preset: **Vite** (build `npm run build`, output `dist`).
4. Add env vars `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`
   (Supabase → Project Settings → API).
5. Deploy.

## Views
- **Dashboard** — equity curve, cash, realized P&L / win rate, open positions.
- **Trades** — every trade (open + closed) with P&L, the AI's rationale, and the
  news headlines that drove it. Nothing is hidden.
- **Signals** — model accuracy (24h / 7d) and the recent signal feed.
