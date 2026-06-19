"""Insert DEMO data so you can preview the dashboard before adding API keys.

Creates fake signals (for the accuracy leaderboard), trades (open + closed, with
P&L) and an equity curve. Everything uses the ``demo-`` model prefix so it is
obviously fake.

Run from the project root:
    python seed_demo.py

Wipe demo data: delete data/app.db (SQLite), or truncate the tables in Supabase.
"""
from __future__ import annotations

import json
import random
from datetime import timedelta

from app.config import ASSETS, HORIZONS
from app.db import init_db, session_scope
from app.models import (
    BEARISH,
    BULLISH,
    PUSH,
    SIDE_BUY,
    TRADE_CLOSED,
    TRADE_OPEN,
    EquitySnapshot,
    Evaluation,
    Prediction,
    Trade,
    utcnow,
)

DEMO_MODELS = ["demo-gemini-2.5-flash", "demo-gemini-2.0-flash", "demo-gemini-1.5-flash"]
# Some models are deliberately better than others so best/worst is visible.
MODEL_SKILL = {DEMO_MODELS[0]: 0.66, DEMO_MODELS[1]: 0.54, DEMO_MODELS[2]: 0.47}
TRADING_MODEL = DEMO_MODELS[0]
START_EQUITY = 10_000.0


def _news(asset, direction: str) -> str:
    lean = "positive" if direction == BULLISH else "negative"
    return json.dumps([
        {"headline": f"Demo: {asset.name} {lean} headline", "summary": "",
         "source": "demo", "url": "#", "datetime": 0}
    ])


def seed(days: int = 45) -> None:
    init_db()
    rng = random.Random(42)
    now = utcnow()
    preds = 0

    with session_scope() as s:
        preds = _seed_signals(s, rng, now, days)
        trades = _seed_trades(s, rng, now, days)
        _seed_equity(s, rng, now, days)

    print(f"Seeded {preds} demo signals and {trades} demo trades across {len(ASSETS)} assets.")
    print("Frontend: cd web && npm run dev   (point it at this database via Supabase)")
    print("Wipe demo data: delete data/app.db")


def _seed_signals(s, rng, now, days) -> int:
    """Predictions + evaluations for the accuracy leaderboard."""
    count = 0
    for d in range(days, 0, -1):
        created = now - timedelta(days=d, hours=rng.randint(0, 6))
        for asset in ASSETS:
            base = round(rng.uniform(60, 420), 2)
            for model in DEMO_MODELS:
                bull = rng.choice([35, 42, 48, 55, 63, 71, 78])
                bear = 100 - bull
                direction = BULLISH if bull >= bear else BEARISH
                pred = Prediction(
                    created_at=created, asset=asset.symbol, model=model, direction=direction,
                    bullish_prob=bull, bearish_prob=bear, price_at_prediction=base,
                    rationale=f"Demo rationale for {asset.symbol}.", news_snapshot=_news(asset, direction),
                )
                s.add(pred)
                s.flush()
                count += 1
                _seed_evaluations(s, pred, base, direction, model, now, rng)
    return count


def _seed_evaluations(s, pred, base, direction, model, now, rng) -> None:
    skill = MODEL_SKILL[model]
    for hname, delta in HORIZONS.items():
        target = pred.created_at + delta
        ev = Evaluation(prediction_id=pred.id, horizon=hname,
                        target_eval_time=target, status="pending")
        if target <= now:
            hit = rng.random() < skill
            up = (direction == BULLISH) if hit else (direction != BULLISH)
            move = rng.uniform(0.005, 0.07) * (1 if up else -1)
            price_eval = round(base * (1 + move), 2)
            actual = BULLISH if price_eval > base else (BEARISH if price_eval < base else PUSH)
            ev.status = "evaluated"
            ev.evaluated_at = target
            ev.price_at_eval = price_eval
            ev.actual_direction = actual
            ev.is_correct = None if actual == PUSH else (direction == actual)
        s.add(ev)


def _seed_trades(s, rng, now, days) -> int:
    """A mix of closed (win/loss) and a couple of open trades."""
    count = 0
    for d in range(days, 2, -3):
        asset = rng.choice(ASSETS)
        entry = round(rng.uniform(60, 420), 2)
        qty = round(rng.uniform(1, 20), 4)
        opened = now - timedelta(days=d, hours=rng.randint(0, 6))
        win = rng.random() < 0.58
        move = rng.uniform(0.01, 0.09) * (1 if win else -1)
        exit_price = round(entry * (1 + move), 2)
        pnl = round((exit_price - entry) * qty, 2)
        s.add(Trade(
            created_at=opened, asset=asset.symbol, side=SIDE_BUY, status=TRADE_CLOSED,
            qty=qty, notional=round(entry * qty, 2), entry_price=entry, model=TRADING_MODEL,
            rationale=f"Demo: fresh {asset.name} news + high confidence.",
            closed_at=opened + timedelta(days=1), exit_price=exit_price,
            pnl=pnl, pnl_pct=round(move * 100, 2), close_reason="signal",
        ))
        count += 1

    # a couple of currently-open positions
    for asset in rng.sample(ASSETS, 2):
        entry = round(rng.uniform(60, 420), 2)
        qty = round(rng.uniform(1, 20), 4)
        s.add(Trade(
            created_at=now - timedelta(hours=rng.randint(2, 20)), asset=asset.symbol,
            side=SIDE_BUY, status=TRADE_OPEN, qty=qty, notional=round(entry * qty, 2),
            entry_price=entry, model=TRADING_MODEL,
            rationale=f"Demo: holding {asset.name} on a bullish signal.",
        ))
        count += 1
    return count


def _seed_equity(s, rng, now, days) -> None:
    equity = START_EQUITY
    for d in range(days, -1, -1):
        equity *= 1 + rng.uniform(-0.012, 0.016)
        ts = now - timedelta(days=d)
        cash = equity * rng.uniform(0.3, 0.7)
        s.add(EquitySnapshot(ts=ts, equity=round(equity, 2), cash=round(cash, 2),
                             buying_power=round(cash * 2, 2)))


if __name__ == "__main__":
    seed()
