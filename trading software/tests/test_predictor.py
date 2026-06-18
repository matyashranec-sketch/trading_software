import app.engine.predictor as predictor_mod
from app.config import ASSETS
from app.engine.predictor import run_predictions
from app.llm.base import LLMProvider, PredictionResult
from app.models import Evaluation, Prediction


class FakeProvider(LLMProvider):
    def available_models(self):
        return ["fake-1", "fake-2"]

    def predict(self, model, asset, news):
        return PredictionResult(bullish_prob=70, bearish_prob=30, rationale="because")


def test_run_predictions_creates_predictions_and_evaluations(db, monkeypatch):
    monkeypatch.setattr(predictor_mod, "fetch_price", lambda asset: 100.0)
    monkeypatch.setattr(predictor_mod, "fetch_news", lambda asset: [])

    summary = run_predictions(db, provider=FakeProvider())

    expected = len(ASSETS) * 2  # 2 models
    assert summary["created"] == expected
    assert db.query(Prediction).count() == expected
    assert db.query(Evaluation).count() == expected * 2  # 24h + 7d each

    p = db.query(Prediction).first()
    assert p.direction == "bullish"
    assert p.bullish_prob == 70


def test_run_predictions_reports_no_models(db):
    class Empty(LLMProvider):
        def available_models(self):
            return []

        def predict(self, model, asset, news):  # pragma: no cover
            raise AssertionError("should not be called")

    summary = run_predictions(db, provider=Empty())
    assert summary["created"] == 0
    assert summary["errors"]
