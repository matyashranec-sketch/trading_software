from app.engine.scoreboard import Stat, full_scoreboard, list_predictions
from app.models import BULLISH, Evaluation, Prediction, utcnow


def _add(db, asset, model, *, correct: bool | None, horizon="24h", status="evaluated"):
    p = Prediction(
        asset=asset, model=model, direction=BULLISH,
        bullish_prob=60, bearish_prob=40, price_at_prediction=100.0,
        news_snapshot="[]", created_at=utcnow(),
    )
    db.add(p)
    db.flush()
    e = Evaluation(prediction_id=p.id, horizon=horizon, target_eval_time=utcnow(), status=status)
    if status == "evaluated":
        e.is_correct = correct
        e.actual_direction = "bullish" if correct else "bearish"
        e.price_at_eval = 101.0 if correct else 99.0
    db.add(e)
    return p


def test_stat_accuracy_none_without_decided():
    s = Stat("x", pending=3)
    assert s.decided == 0
    assert s.total == 3
    assert s.accuracy is None


def test_overall_accuracy(db):
    _add(db, "TSLA", "gem", correct=True)
    _add(db, "TSLA", "gem", correct=True)
    _add(db, "TSLA", "gem", correct=False)
    db.commit()

    board = full_scoreboard(db)["boards"]["24h"]
    assert board["overall"].correct == 2
    assert board["overall"].incorrect == 1
    assert board["overall"].accuracy == 66.7


def test_pending_not_counted_in_accuracy(db):
    _add(db, "BTC", "gem", correct=True)
    _add(db, "BTC", "gem", correct=None, status="pending")
    db.commit()

    board = full_scoreboard(db)["boards"]["24h"]
    btc = next(s for s in board["by_asset"] if s.label == "BTC")
    assert btc.correct == 1
    assert btc.pending == 1
    assert btc.accuracy == 100.0


def test_best_and_worst_model(db):
    _add(db, "TSLA", "good-model", correct=True)
    _add(db, "TSLA", "good-model", correct=True)
    _add(db, "TSLA", "bad-model", correct=False)
    _add(db, "TSLA", "bad-model", correct=False)
    db.commit()

    board = full_scoreboard(db)["boards"]["24h"]
    assert board["best_model"].label == "good-model"
    assert board["worst_model"].label == "bad-model"


def test_horizons_are_separate(db):
    _add(db, "BTC", "gem", correct=True, horizon="24h")
    _add(db, "BTC", "gem", correct=False, horizon="7d")
    db.commit()

    boards = full_scoreboard(db)["boards"]
    assert boards["24h"]["overall"].accuracy == 100.0
    assert boards["7d"]["overall"].accuracy == 0.0


def test_list_predictions_filters(db):
    _add(db, "TSLA", "gem", correct=True)
    _add(db, "BTC", "gem", correct=True)
    db.commit()

    assert len(list_predictions(db)) == 2
    assert len(list_predictions(db, asset="BTC")) == 1
