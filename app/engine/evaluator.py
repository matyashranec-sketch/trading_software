"""Evaluate matured predictions against the real current price."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import ASSETS_BY_SYMBOL
from app.models import BEARISH, BULLISH, PUSH, Evaluation, utcnow
from app.sources.prices import PriceUnavailable, fetch_price

logger = logging.getLogger(__name__)


def run_evaluations(session: Session) -> dict:
    """Resolve every pending evaluation whose target time has passed."""
    now = utcnow()
    due = session.scalars(
        select(Evaluation)
        .where(Evaluation.status == "pending", Evaluation.target_eval_time <= now)
        .options(selectinload(Evaluation.prediction))
    ).all()

    summary: dict = {"evaluated": 0, "skipped": 0, "errors": []}
    price_cache: dict[str, float] = {}  # one price fetch per asset per run

    for ev in due:
        asset = ASSETS_BY_SYMBOL.get(ev.prediction.asset)
        if asset is None:
            summary["skipped"] += 1
            continue
        try:
            if asset.symbol not in price_cache:
                price_cache[asset.symbol] = fetch_price(asset)
        except PriceUnavailable as exc:
            logger.warning("Eval skipped for %s: %s", asset.symbol, exc)
            summary["skipped"] += 1
            summary["errors"].append(f"{asset.symbol}: {exc}")
            continue

        _resolve(ev, price_cache[asset.symbol], now)
        summary["evaluated"] += 1

    session.commit()
    return summary


def _resolve(ev: Evaluation, price: float, now: datetime) -> None:
    start = ev.prediction.price_at_prediction
    if price > start:
        actual = BULLISH
    elif price < start:
        actual = BEARISH
    else:
        actual = PUSH

    ev.price_at_eval = price
    ev.actual_direction = actual
    ev.evaluated_at = now
    ev.status = "evaluated"
    # push (no move) is excluded from accuracy but stays visible
    ev.is_correct = None if actual == PUSH else (ev.prediction.direction == actual)
