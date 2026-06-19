from datetime import timedelta

import app.engine.evaluator as evaluator_mod
from app.engine.evaluator import _resolve, run_evaluations
from app.models import BEARISH, BULLISH, PUSH, Evaluation, Prediction, utcnow


def _eval(direction: str, start: float) -> Evaluation:
    p = Prediction(
        asset="TSLA", model="m", direction=direction,
        bullish_prob=60, bearish_prob=40, price_at_prediction=start,
        rationale="", news_snapshot="[]", created_at=utcnow(),
    )
    e = Evaluation(horizon="24h", target_eval_time=utcnow() - timedelta(hours=1), status="pending")
    e.prediction = p
    return e


def test_bullish_correct_when_price_up():
    e = _eval(BULLISH, 100.0)
    _resolve(e, 110.0, utcnow())
    assert e.actual_direction == BULLISH
    assert e.is_correct is True
    assert e.status == "evaluated"
    assert e.price_at_eval == 110.0


def test_bullish_incorrect_when_price_down():
    e = _eval(BULLISH, 100.0)
    _resolve(e, 90.0, utcnow())
    assert e.actual_direction == BEARISH
    assert e.is_correct is False


def test_bearish_correct_when_price_down():
    e = _eval(BEARISH, 100.0)
    _resolve(e, 95.0, utcnow())
    assert e.actual_direction == BEARISH
    assert e.is_correct is True


def test_push_when_unchanged_excluded_from_accuracy():
    e = _eval(BULLISH, 100.0)
    _resolve(e, 100.0, utcnow())
    assert e.actual_direction == PUSH
    assert e.is_correct is None


def test_run_evaluations_only_resolves_due(db, monkeypatch):
    p = Prediction(
        asset="BTC", model="m", direction=BULLISH,
        bullish_prob=70, bearish_prob=30, price_at_prediction=100.0,
        news_snapshot="[]", created_at=utcnow() - timedelta(days=2),
    )
    db.add(p)
    db.flush()
    db.add(Evaluation(prediction_id=p.id, horizon="24h",
                      target_eval_time=utcnow() - timedelta(hours=1), status="pending"))
    db.add(Evaluation(prediction_id=p.id, horizon="7d",
                      target_eval_time=utcnow() + timedelta(days=5), status="pending"))
    db.commit()

    monkeypatch.setattr(evaluator_mod, "fetch_price", lambda asset: 120.0)
    summary = run_evaluations(db)

    assert summary["evaluated"] == 1  # only the matured 24h evaluation
    resolved = [e for e in p.evaluations if e.status == "evaluated"]
    assert len(resolved) == 1
    assert resolved[0].horizon == "24h"
    assert resolved[0].is_correct is True
