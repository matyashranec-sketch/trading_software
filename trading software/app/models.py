"""ORM models.

All timestamps are stored as **naive UTC** (SQLite does not persist tzinfo, so
keeping everything naive UTC avoids aware/naive comparison bugs).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Direction / result constants
BULLISH = "bullish"
BEARISH = "bearish"
PUSH = "push"  # price unchanged -> excluded from accuracy, still shown


def utcnow() -> datetime:
    """Naive UTC now (matches how datetimes are stored)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Prediction(Base):
    """One prediction = one model, one asset, one point in time."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    asset: Mapped[str] = mapped_column(String(16), index=True)
    model: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # bullish | bearish
    bullish_prob: Mapped[float] = mapped_column(Float)
    bearish_prob: Mapped[float] = mapped_column(Float)
    price_at_prediction: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text, default="")
    news_snapshot: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of headlines

    evaluations: Mapped[list["Evaluation"]] = relationship(
        back_populates="prediction",
        cascade="all, delete-orphan",
        order_by="Evaluation.target_eval_time",
    )

    @staticmethod
    def direction_from_probs(bullish_prob: float, bearish_prob: float) -> str:
        return BULLISH if bullish_prob >= bearish_prob else BEARISH


class Evaluation(Base):
    """Outcome of a prediction at a given horizon (24h, 7d, ...)."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.id"), index=True
    )
    horizon: Mapped[str] = mapped_column(String(8), index=True)  # "24h" | "7d"
    target_eval_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True
    )  # pending | evaluated
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    price_at_eval: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    prediction: Mapped["Prediction"] = relationship(back_populates="evaluations")
