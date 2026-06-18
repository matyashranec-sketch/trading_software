"""Insert DEMO predictions so you can preview the UI before adding API keys.

These rows use the model name prefix ``demo-`` so they are obviously fake.
To wipe everything and start clean, just delete ``data/app.db``.

Run from the project root:
    python seed_demo.py
"""
from __future__ import annotations

import json
import random
from datetime import timedelta

from app.config import ASSETS, HORIZONS
from app.db import init_db, session_scope
from app.models import BEARISH, BULLISH, PUSH, Evaluation, Prediction, utcnow

DEMO_MODELS = ["demo-gemini-2.5-flash", "demo-gemini-2.0-flash", "demo-gemini-1.5-flash"]
# Some models are deliberately better than others so best/worst is visible.
MODEL_SKILL = {DEMO_MODELS[0]: 0.66, DEMO_MODELS[1]: 0.54, DEMO_MODELS[2]: 0.47}


def seed(days: int = 45) -> None:
    init_db()
    rng = random.Random(42)
    now = utcnow()
    created_count = 0

    with session_scope() as s:
        for d in range(days, 0, -1):
            created = now - timedelta(days=d, hours=rng.randint(0, 6))
            for asset in ASSETS:
                base_price = round(rng.uniform(60, 420), 2)
                for model in DEMO_MODELS:
                    bull = rng.choice([35, 42, 48, 55, 63, 71, 78])
                    bear = 100 - bull
                    direction = BULLISH if bull >= bear else BEARISH
                    pred = Prediction(
                        created_at=created,
                        asset=asset.symbol,
                        model=model,
                        direction=direction,
                        bullish_prob=bull,
                        bearish_prob=bear,
                        price_at_prediction=base_price,
                        rationale=(
                            f"Demo: {asset.symbol} news leans "
                            f"{'positive' if direction == BULLISH else 'negative'}."
                        ),
                        news_snapshot=json.dumps([
                            {"headline": f"Demo headline about {asset.name}",
                             "summary": "", "source": "demo", "url": "#", "datetime": 0}
                        ]),
                    )
                    s.add(pred)
                    s.flush()
                    created_count += 1
                    _add_evaluations(s, pred, base_price, direction, model, now, rng)

    print(f"Seeded {created_count} demo predictions across {len(ASSETS)} assets.")
    print("Start the app:  uvicorn app.main:app --reload   ->  http://localhost:8000/")
    print("Wipe demo data: delete data/app.db")


def _add_evaluations(s, pred, base_price, direction, model, now, rng) -> None:
    skill = MODEL_SKILL[model]
    for hname, delta in HORIZONS.items():
        target = pred.created_at + delta
        ev = Evaluation(prediction_id=pred.id, horizon=hname,
                        target_eval_time=target, status="pending")
        if target <= now:
            # Bias the move so the model's hit-rate roughly matches its skill.
            hit = rng.random() < skill
            up = (direction == BULLISH) if hit else (direction != BULLISH)
            move = rng.uniform(0.005, 0.07) * (1 if up else -1)
            price_eval = round(base_price * (1 + move), 2)
            actual = BULLISH if price_eval > base_price else (BEARISH if price_eval < base_price else PUSH)
            ev.status = "evaluated"
            ev.evaluated_at = target
            ev.price_at_eval = price_eval
            ev.actual_direction = actual
            ev.is_correct = None if actual == PUSH else (direction == actual)
        s.add(ev)


if __name__ == "__main__":
    seed()
