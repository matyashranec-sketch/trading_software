"""ORM models.

Two layers, both kept forever and fully public (transparency is the point):

* ``Prediction`` / ``Evaluation`` — the AI signal log and how it scored against
  the real price (the accuracy "leaderboard").
* ``Trade`` / ``EquitySnapshot`` — the real (paper) trades the bot placed because
  of those signals, plus the account equity over time.

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

# Trade side / status constants
SIDE_BUY = "buy"
SIDE_SELL = "sell"
TRADE_SUBMITTED = "submitted"  # order sent, not confirmed filled yet
TRADE_OPEN = "open"            # position held
TRADE_CLOSED = "closed"        # position exited
TRADE_CANCELED = "canceled"    # order never resulted in a position

# Why a position was closed
CLOSE_SIGNAL = "signal"
CLOSE_STOP_LOSS = "stop_loss"
CLOSE_TAKE_PROFIT = "take_profit"
CLOSE_MAX_HOLD = "max_hold"  # held longer than max_hold_bars -> time stop


def utcnow() -> datetime:
    """Naive UTC now (matches how datetimes are stored)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Prediction(Base):
    """One signal = one model, one asset, one point in time."""

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
    trades: Mapped[list["Trade"]] = relationship(back_populates="prediction")

    @staticmethod
    def direction_from_probs(bullish_prob: float, bearish_prob: float) -> str:
        return BULLISH if bullish_prob >= bearish_prob else BEARISH

    @property
    def confidence(self) -> float:
        """How sure the model is, regardless of direction (0-100)."""
        return max(self.bullish_prob, self.bearish_prob)


class Evaluation(Base):
    """Outcome of a signal at a given horizon (24h, 7d, ...)."""

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


class Trade(Base):
    """A real (paper) position the bot opened because of a signal.

    One row tracks a full position lifecycle: opened by a buy, later closed by a
    sell, with entry/exit prices and realized P&L. Nothing is ever deleted —
    losing trades stay as visible as winners.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    asset: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))  # buy | sell (opening side)
    status: Mapped[str] = mapped_column(String(16), default=TRADE_SUBMITTED, index=True)

    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional: Mapped[float | None] = mapped_column(Float, nullable=True)  # $ targeted
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    alpaca_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")

    # Optional risk exits (set from config; 0/None = disabled)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Close / outcome
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)

    prediction_id: Mapped[int | None] = mapped_column(
        ForeignKey("predictions.id"), nullable=True, index=True
    )
    prediction: Mapped["Prediction | None"] = relationship(back_populates="trades")

    @property
    def is_open(self) -> bool:
        return self.status in (TRADE_SUBMITTED, TRADE_OPEN)


class EquitySnapshot(Base):
    """Account equity / cash sampled on each bot run — drives the equity curve."""

    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    buying_power: Mapped[float] = mapped_column(Float)
