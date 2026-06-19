"""Generate AI signals: fetch news + price, ask the model(s), store everything.

Two entry points:

* :func:`generate_signals` — one decision per asset from the *trading model*,
  returned to the trader (and stored as ``Prediction`` rows so they still show on
  the accuracy leaderboard).
* :func:`run_predictions` — every configured model on every asset, purely to keep
  the model-accuracy leaderboard populated (optional; not on the trading path).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import ASSETS, HORIZONS, Asset, get_settings
from app.llm.base import LLMProvider, PredictionResult
from app.llm.provider import get_provider
from app.models import Evaluation, Prediction, utcnow
from app.sources.news import NewsItem, fetch_news
from app.sources.prices import PriceUnavailable, fetch_price

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """One actionable signal for the trader (a stored Prediction + context)."""

    asset: Asset
    prediction: Prediction
    has_fresh_news: bool
    news: list[NewsItem] = field(default_factory=list)

    @property
    def direction(self) -> str:
        return self.prediction.direction

    @property
    def confidence(self) -> float:
        return self.prediction.confidence

    @property
    def price(self) -> float:
        return self.prediction.price_at_prediction


def _pick_trading_model(models: list[str]) -> str:
    """The single model the bot trades on: configured one if usable, else first."""
    settings = get_settings()
    if settings.trading_model and settings.trading_model in models:
        return settings.trading_model
    return models[0]


def _has_fresh_news(news: list[NewsItem], within_hours: int) -> bool:
    if not news:
        return False
    cutoff = time.time() - within_hours * 3600
    return any(n.datetime >= cutoff for n in news)


def generate_signals(session: Session, provider: LLMProvider | None = None) -> list[Signal]:
    """Produce one signal per tradable asset using the trading model."""
    provider = provider or get_provider()
    models = provider.available_models()
    if not models:
        logger.warning("No usable AI models — set GEMINI_API_KEY; no signals generated.")
        return []

    settings = get_settings()
    model = _pick_trading_model(models)
    signals: list[Signal] = []

    for asset in ASSETS:
        if not asset.tradable:
            continue
        try:
            price = fetch_price(asset)
        except PriceUnavailable as exc:
            logger.warning("Skipping %s: %s", asset.symbol, exc)
            continue

        news = fetch_news(asset)
        news_json = json.dumps([n.to_dict() for n in news])
        try:
            result = provider.predict(model, asset, news)
        except Exception:
            logger.exception("Signal failed for %s/%s", asset.symbol, model)
            continue

        prediction = _store_prediction(session, asset, model, price, result, news_json)
        signals.append(
            Signal(
                asset=asset,
                prediction=prediction,
                has_fresh_news=_has_fresh_news(news, settings.news_fresh_hours),
                news=news,
            )
        )

    session.commit()
    return signals


def run_predictions(session: Session, provider: LLMProvider | None = None) -> dict:
    """Create predictions for every asset across every usable model (leaderboard).

    Returns a summary dict (counts + any errors).
    """
    provider = provider or get_provider()
    models = provider.available_models()
    summary: dict = {"created": 0, "models": models, "assets": [], "errors": []}

    if not models:
        summary["errors"].append(
            "No usable AI models — set GEMINI_API_KEY in .env (free at "
            "https://aistudio.google.com/app/apikey)."
        )
        return summary

    for asset in ASSETS:
        try:
            price = fetch_price(asset)
        except PriceUnavailable as exc:
            logger.warning("Skipping %s: %s", asset.symbol, exc)
            summary["errors"].append(f"{asset.symbol}: no price ({exc})")
            continue

        news = fetch_news(asset)
        news_json = json.dumps([n.to_dict() for n in news])

        for model in models:
            try:
                result = provider.predict(model, asset, news)
            except Exception as exc:  # one model failing must not stop the rest
                logger.exception("Prediction failed for %s/%s", asset.symbol, model)
                summary["errors"].append(f"{asset.symbol}/{model}: {exc}")
                continue

            _store_prediction(session, asset, model, price, result, news_json)
            summary["created"] += 1

        summary["assets"].append(asset.symbol)

    session.commit()
    return summary


def _store_prediction(
    session: Session,
    asset: Asset,
    model: str,
    price: float,
    result: PredictionResult,
    news_json: str,
) -> Prediction:
    now = utcnow()
    prediction = Prediction(
        created_at=now,
        asset=asset.symbol,
        model=model,
        direction=Prediction.direction_from_probs(result.bullish_prob, result.bearish_prob),
        bullish_prob=result.bullish_prob,
        bearish_prob=result.bearish_prob,
        price_at_prediction=price,
        rationale=result.rationale,
        news_snapshot=news_json,
    )
    session.add(prediction)
    session.flush()  # assign prediction.id

    for horizon_name, delta in HORIZONS.items():
        session.add(
            Evaluation(
                prediction_id=prediction.id,
                horizon=horizon_name,
                target_eval_time=now + delta,
                status="pending",
            )
        )
    return prediction
