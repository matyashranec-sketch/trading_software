"""Trading engine — turn AI signals into real (paper) Alpaca orders.

Run every ~2h by cron. Each run:

1. generate one signal per asset (news -> Gemini);
2. gate it: trade only on **fresh news** and **high confidence** (the user's
   "po news, když si je jistejší" rule);
3. size and place the order, respecting position caps, cash buffer, market hours
   (stocks) and idempotency (don't double-open);
4. log a ``Trade`` (with the rationale + news that drove it) and an
   ``EquitySnapshot``.

``run_sync`` reconciles open trades against Alpaca, applies optional stop-loss /
take-profit exits, records equity and scores matured signals. Nothing is ever
deleted — losing trades stay visible.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.broker import Account, Broker, Position, get_broker
from app.broker.base import LONG, SHORT
from app.config import ASSETS, Asset, get_settings
from app.engine.evaluator import run_evaluations
from app.engine.predictor import Signal, generate_signals
from app.models import (
    BULLISH,
    CLOSE_SIGNAL,
    CLOSE_STOP_LOSS,
    CLOSE_TAKE_PROFIT,
    SIDE_BUY,
    SIDE_SELL,
    TRADE_CLOSED,
    TRADE_OPEN,
    TRADE_SUBMITTED,
    EquitySnapshot,
    Trade,
    utcnow,
)
from app.sources.prices import PriceUnavailable, fetch_price

logger = logging.getLogger(__name__)

MIN_NOTIONAL = 1.0  # don't bother placing dust orders

ACTION_BUY = "buy"
ACTION_SHORT = "short"
ACTION_CLOSE = "close"
ACTION_HOLD = "hold"


@dataclass
class Decision:
    action: str
    reason: str


# --------------------------------------------------------------------------- #
# Symbol <-> position matching (broker may return "BTCUSD" for our "BTC")
# --------------------------------------------------------------------------- #
def _norm(symbol: str) -> str:
    return symbol.upper().replace("/", "")


def _position_for(asset: Asset, positions: list[Position]) -> Position | None:
    target = _norm(asset.symbol)
    for p in positions:
        ps = _norm(p.symbol)
        if ps == target or ps == f"{target}USD":
            return p
    return None


def _config_symbol(broker_symbol: str) -> str | None:
    ps = _norm(broker_symbol)
    for a in ASSETS:
        sym = _norm(a.symbol)
        if ps == sym or ps == f"{sym}USD":
            return a.symbol
    return None


# --------------------------------------------------------------------------- #
# Decision logic (pure — easy to unit test)
# --------------------------------------------------------------------------- #
def decide(signal: Signal, holding: Position | None, open_count: int, market_open: bool,
           settings=None) -> Decision:
    settings = settings or get_settings()

    if signal.asset.kind == "stock" and not market_open:
        return Decision(ACTION_HOLD, "market closed")
    if settings.require_fresh_news and not signal.has_fresh_news:
        return Decision(ACTION_HOLD, "no fresh news")
    if signal.confidence < settings.min_confidence:
        return Decision(
            ACTION_HOLD, f"confidence {signal.confidence:.0f} < {settings.min_confidence:.0f}"
        )

    if signal.direction == BULLISH:
        if holding and holding.side == LONG:
            return Decision(ACTION_HOLD, "already long")
        if holding and holding.side == SHORT:
            return Decision(ACTION_CLOSE, "bullish signal vs short — cover")
        if open_count >= settings.max_open_positions:
            return Decision(ACTION_HOLD, "max open positions reached")
        return Decision(ACTION_BUY, "bullish + fresh news + high confidence")

    # bearish
    if holding and holding.side == LONG:
        return Decision(ACTION_CLOSE, "bearish signal — exit long")
    if settings.allow_short:
        if holding and holding.side == SHORT:
            return Decision(ACTION_HOLD, "already short")
        if open_count >= settings.max_open_positions:
            return Decision(ACTION_HOLD, "max open positions reached")
        return Decision(ACTION_SHORT, "bearish + fresh news + high confidence")
    return Decision(ACTION_HOLD, "bearish, nothing to close (shorting disabled)")


def size_notional(account: Account, confidence: float, settings=None) -> float:
    """Target dollar size for a new position, after risk caps and cash buffer."""
    settings = settings or get_settings()
    size = account.equity * settings.max_position_pct
    if settings.scale_size_by_confidence:
        size *= confidence / 100.0
    deployable = account.cash * (1.0 - settings.cash_buffer_pct)
    return max(0.0, min(size, deployable))


# --------------------------------------------------------------------------- #
# Main entry points
# --------------------------------------------------------------------------- #
def run_trading(session: Session, broker: Broker | None = None, provider=None,
                dry_run: bool = False) -> dict:
    settings = get_settings()
    broker = broker or get_broker()

    signals = generate_signals(session, provider=provider)
    account = broker.get_account()
    positions = broker.get_positions()
    open_count = len(positions)
    market_open = broker.is_market_open()
    pending = {s for s in (_config_symbol(o.symbol) for o in broker.list_open_orders()) if s}

    summary: dict = {
        "dry_run": dry_run,
        "equity": account.equity,
        "cash": account.cash,
        "signals": len(signals),
        "market_open": market_open,
        "actions": [],
    }

    for sig in signals:
        symbol = sig.asset.symbol
        holding = _position_for(sig.asset, positions)

        if symbol in pending:
            _record_action(summary, sig, Decision(ACTION_HOLD, "pending order exists"))
            continue

        decision = decide(sig, holding, open_count, market_open, settings)

        notional = None
        if decision.action in (ACTION_BUY, ACTION_SHORT):
            notional = size_notional(account, sig.confidence, settings)
            if notional < MIN_NOTIONAL:
                decision = Decision(ACTION_HOLD, "insufficient cash / buffer")

        entry = _record_action(summary, sig, decision, notional)
        if dry_run or decision.action == ACTION_HOLD:
            continue

        try:
            order = None
            if decision.action == ACTION_BUY:
                order = broker.submit_order(symbol, SIDE_BUY, notional=notional)
                _open_trade(session, sig, SIDE_BUY, notional, order, settings)
                open_count += 1
            elif decision.action == ACTION_SHORT:
                order = broker.submit_order(symbol, SIDE_SELL, notional=notional)
                _open_trade(session, sig, SIDE_SELL, notional, order, settings)
                open_count += 1
            elif decision.action == ACTION_CLOSE:
                order = broker.close_position(symbol)
                _close_trade(session, symbol, sig.price, CLOSE_SIGNAL, holding)
                open_count = max(0, open_count - 1)
            if order is not None:
                entry["order_id"] = order.id
        except Exception as exc:  # one asset failing must not abort the run
            logger.exception("Order failed for %s", symbol)
            entry["error"] = str(exc)

    if not dry_run:
        _record_equity(session, account)
    session.commit()
    return summary


def run_sync(session: Session, broker: Broker | None = None) -> dict:
    """Reconcile open trades with the broker, apply stop/take exits, record equity,
    and score matured signals."""
    settings = get_settings()
    broker = broker or get_broker()

    account = broker.get_account()
    positions = broker.get_positions()
    summary: dict = {"reconciled": 0, "closed": 0, "equity": account.equity, "actions": []}

    open_trades = session.scalars(
        select(Trade).where(Trade.status.in_([TRADE_SUBMITTED, TRADE_OPEN]))
    ).all()

    for trade in open_trades:
        asset = next((a for a in ASSETS if a.symbol == trade.asset), None)
        pos = _position_for(asset, positions) if asset else None
        if pos is None:
            continue  # position not present yet (or closed elsewhere) — leave untouched

        if trade.entry_price is None:
            trade.entry_price = pos.avg_entry_price
        if trade.qty is None:
            trade.qty = pos.qty
        if trade.status == TRADE_SUBMITTED:
            trade.status = TRADE_OPEN
        summary["reconciled"] += 1

        try:
            price = fetch_price(asset)
        except PriceUnavailable:
            continue
        reason = _exit_reason(trade, price)
        if reason:
            broker.close_position(trade.asset)
            _close_trade(session, trade.asset, price, reason, pos)
            summary["closed"] += 1
            summary["actions"].append({"asset": trade.asset, "action": "close", "reason": reason})

    _record_equity(session, account)
    session.commit()

    summary["evaluations"] = run_evaluations(session)
    return summary


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _open_trade(session: Session, sig: Signal, side: str, notional: float | None,
                order, settings) -> Trade:
    entry_price = order.filled_avg_price or sig.price  # refined later in sync
    stop_price, take_profit = _risk_exits(side, entry_price, settings)
    trade = Trade(
        asset=sig.asset.symbol,
        side=side,
        status=TRADE_SUBMITTED,
        qty=order.qty,
        notional=notional,
        entry_price=entry_price,
        alpaca_order_id=order.id,
        model=sig.prediction.model,
        rationale=sig.prediction.rationale,
        stop_price=stop_price,
        take_profit=take_profit,
        prediction_id=sig.prediction.id,
    )
    session.add(trade)
    return trade


def _close_trade(session: Session, symbol: str, exit_price: float | None, reason: str,
                 holding: Position | None) -> Trade | None:
    trade = session.scalars(
        select(Trade)
        .where(Trade.asset == symbol, Trade.status.in_([TRADE_SUBMITTED, TRADE_OPEN]))
        .order_by(Trade.created_at.desc())
    ).first()
    if trade is None:
        return None

    if exit_price is None and holding is not None and holding.qty:
        exit_price = holding.market_value / holding.qty
    entry = trade.entry_price or (holding.avg_entry_price if holding else None)
    qty = trade.qty or (holding.qty if holding else None)

    trade.exit_price = exit_price
    trade.closed_at = utcnow()
    trade.status = TRADE_CLOSED
    trade.close_reason = reason
    if entry and exit_price:
        if trade.side == SIDE_BUY:  # long
            trade.pnl_pct = round((exit_price - entry) / entry * 100, 2)
            trade.pnl = round((exit_price - entry) * qty, 2) if qty else None
        else:  # short
            trade.pnl_pct = round((entry - exit_price) / entry * 100, 2)
            trade.pnl = round((entry - exit_price) * qty, 2) if qty else None
    return trade


def _risk_exits(side: str, entry_price: float, settings) -> tuple[float | None, float | None]:
    if not entry_price:
        return None, None
    slp, tpp = settings.stop_loss_pct, settings.take_profit_pct
    if side == SIDE_BUY:  # long
        stop = entry_price * (1 - slp) if slp > 0 else None
        take = entry_price * (1 + tpp) if tpp > 0 else None
    else:  # short
        stop = entry_price * (1 + slp) if slp > 0 else None
        take = entry_price * (1 - tpp) if tpp > 0 else None
    return stop, take


def _exit_reason(trade: Trade, price: float) -> str | None:
    if trade.side == SIDE_BUY:  # long
        if trade.stop_price and price <= trade.stop_price:
            return CLOSE_STOP_LOSS
        if trade.take_profit and price >= trade.take_profit:
            return CLOSE_TAKE_PROFIT
    else:  # short
        if trade.stop_price and price >= trade.stop_price:
            return CLOSE_STOP_LOSS
        if trade.take_profit and price <= trade.take_profit:
            return CLOSE_TAKE_PROFIT
    return None


def _record_equity(session: Session, account: Account) -> EquitySnapshot:
    snap = EquitySnapshot(
        ts=utcnow(),
        equity=account.equity,
        cash=account.cash,
        buying_power=account.buying_power,
    )
    session.add(snap)
    return snap


def _record_action(summary: dict, sig: Signal, decision: Decision,
                   notional: float | None = None) -> dict:
    entry = {
        "asset": sig.asset.symbol,
        "direction": sig.direction,
        "confidence": sig.confidence,
        "fresh_news": sig.has_fresh_news,
        "action": decision.action,
        "reason": decision.reason,
        "notional": round(notional, 2) if notional else None,
        "order_id": None,
    }
    summary["actions"].append(entry)
    logger.info(
        "%s: %s (%s) — dir=%s conf=%.0f fresh=%s",
        sig.asset.symbol, decision.action, decision.reason,
        sig.direction, sig.confidence, sig.has_fresh_news,
    )
    return entry
