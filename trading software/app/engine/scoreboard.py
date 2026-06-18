"""Aggregate predictions/evaluations into leaderboard statistics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import ASSETS, HORIZONS
from app.models import Evaluation, Prediction, utcnow


@dataclass
class Stat:
    """Tally for one bucket (overall / asset / model / time window)."""

    label: str
    correct: int = 0
    incorrect: int = 0
    pending: int = 0
    push: int = 0

    @property
    def decided(self) -> int:
        return self.correct + self.incorrect

    @property
    def total(self) -> int:
        return self.correct + self.incorrect + self.pending + self.push

    @property
    def accuracy(self) -> float | None:
        return round(self.correct / self.decided * 100, 1) if self.decided else None


def _tally(stat: Stat, ev: Evaluation) -> None:
    if ev.status != "evaluated":
        stat.pending += 1
    elif ev.is_correct is None:  # push (no price move)
        stat.push += 1
    elif ev.is_correct:
        stat.correct += 1
    else:
        stat.incorrect += 1


def full_scoreboard(session: Session) -> dict:
    """Everything the leaderboard page needs, per horizon."""
    now = utcnow()
    boards = {h: _board_for_horizon(session, h, now) for h in HORIZONS}
    return {"horizons": list(HORIZONS.keys()), "boards": boards}


def _board_for_horizon(session: Session, horizon: str, now) -> dict:
    rows = session.execute(
        select(Evaluation, Prediction)
        .join(Prediction, Evaluation.prediction_id == Prediction.id)
        .where(Evaluation.horizon == horizon)
    ).all()

    overall = Stat("Overall")
    overall_30d = Stat("Last 30 days")
    overall_90d = Stat("Last 90 days")
    by_asset = {a.symbol: Stat(a.symbol) for a in ASSETS}
    by_model: dict[str, Stat] = {}

    d30, d90 = now - timedelta(days=30), now - timedelta(days=90)

    for ev, pred in rows:
        _tally(overall, ev)
        _tally(by_asset.setdefault(pred.asset, Stat(pred.asset)), ev)
        _tally(by_model.setdefault(pred.model, Stat(pred.model)), ev)
        if pred.created_at >= d30:
            _tally(overall_30d, ev)
        if pred.created_at >= d90:
            _tally(overall_90d, ev)

    models = list(by_model.values())
    decided_models = [m for m in models if m.decided > 0]
    best = max(decided_models, key=lambda s: s.accuracy, default=None)
    worst = min(decided_models, key=lambda s: s.accuracy, default=None)

    return {
        "overall": overall,
        "overall_30d": overall_30d,
        "overall_90d": overall_90d,
        "by_asset": [by_asset[a.symbol] for a in ASSETS],
        "by_model": sorted(
            models, key=lambda s: (s.accuracy if s.accuracy is not None else -1.0), reverse=True
        ),
        "best_model": best,
        "worst_model": worst,
    }


def list_predictions(
    session: Session,
    asset: str | None = None,
    model: str | None = None,
    limit: int = 300,
) -> list[Prediction]:
    """Most recent predictions (with evaluations eager-loaded) for the log page."""
    q = select(Prediction).options(selectinload(Prediction.evaluations))
    if asset:
        q = q.where(Prediction.asset == asset)
    if model:
        q = q.where(Prediction.model == model)
    q = q.order_by(Prediction.created_at.desc()).limit(limit)
    return list(session.scalars(q).all())


def known_models(session: Session) -> list[str]:
    return list(session.scalars(select(Prediction.model).distinct().order_by(Prediction.model)).all())
