"""Generate predictions: fetch news + price, ask every model, store everything."""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.config import ASSETS, HORIZONS, Asset
from app.llm.base import LLMProvider, PredictionResult
from app.llm.provider import get_provider
from app.models import Evaluation, Prediction, utcnow
from app.sources.news import fetch_news
from app.sources.prices import PriceUnavailable, fetch_price

logger = logging.getLogger(__name__)


def run_predictions(session: Session, provider: LLMProvider | None = None) -> dict:
    """Create predictions for every asset across every usable model.

    Returns a summary dict (counts + any errors) for the API/UI.
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
