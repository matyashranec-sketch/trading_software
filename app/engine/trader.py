"""Trading engine — turn order-flow confluence signals into real (testnet) orders.

Run every ~15–60 min by the scheduler. Each run:

1. generate one signal per asset from the order-flow **confluence** engine
   (deterministic rules — no news, no LLM);
2. gate it **twice**: trade only when the strict confluence checklist **passes**
   *and* the LLM (Gemini) confirms the same setup (``confirm_setup`` — fail-open if
   the model is unavailable), in the direction the higher-timeframe trend allows
   (long **or** short on futures);
3. size by **risk** (fixed % of a virtual $10k paper account — see
   ``virtual_account``), respecting position caps / leverage / cash buffer and
   idempotency;
4. log a ``Trade`` (with the confluence + LLM rationale that drove it) + an
   ``EquitySnapshot`` (virtual equity, so the curve starts cleanly at $10k).

``run_sync`` reconciles open trades against the broker, applies the
structure-based stop-loss / take-profit, records equity and scores matured
signals. Nothing is ever deleted — losing trades stay visible.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.broker import Account, Broker, Position, get_broker
from app.broker.base import LONG, SHORT
from app.config import ASSETS, Asset, get_settings
from app.engine.evaluator import run_evaluations
from app.engine.strategy.engine import StrategySignal, generate_signals
from app.models import (
    CLOSE_MAX_HOLD,
    CLOSE_SIGNAL,
    CLOSE_STOP_LOSS,
    CLOSE_TAKE_PROFIT,
    SIDE_BUY,
    SIDE_SELL,
    TRADE_CLOSED,
    TRADE_OPEN,
    TRADE_SUBMITTED,
    EquitySnapshot,
    Evaluation,
    Prediction,
    Trade,
    utcnow,
)
from app.sources.market_data import interval_ms
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
        if ps == target or ps == f"{target}USD" or ps == f"{target}USDT":
            return p
    return None


def _config_symbol(broker_symbol: str) -> str | None:
    ps = _norm(broker_symbol)
    for a in ASSETS:
        sym = _norm(a.symbol)
        if ps == sym or ps == f"{sym}USD" or ps == f"{sym}USDT":
            return a.symbol
    return None


# --------------------------------------------------------------------------- #
# Decision logic (pure — easy to unit test)
# --------------------------------------------------------------------------- #
def decide(signal: StrategySignal, holding: Position | None, open_count: int,
           settings=None) -> Decision:
    """Gate a confluence signal into an action (long/short/close/hold)."""
    settings = settings or get_settings()

    if not signal.passed:
        return Decision(ACTION_HOLD, signal.result.rationale or "confluence not met")

    if signal.is_long:
        if holding and holding.side == LONG:
            return Decision(ACTION_HOLD, "already long")
        if holding and holding.side == SHORT:
            return Decision(ACTION_CLOSE, "long signal vs short — close first")
        if open_count >= settings.max_open_positions:
            return Decision(ACTION_HOLD, "max open positions reached")
        return Decision(ACTION_BUY, "long confluence passed")

    # short signal
    if not settings.allow_short:
        if holding and holding.side == LONG:
            return Decision(ACTION_CLOSE, "short signal — exit long")
        return Decision(ACTION_HOLD, "short signal but shorting disabled")
    if holding and holding.side == SHORT:
        return Decision(ACTION_HOLD, "already short")
    if holding and holding.side == LONG:
        return Decision(ACTION_CLOSE, "short signal vs long — close first")
    if open_count >= settings.max_open_positions:
        return Decision(ACTION_HOLD, "max open positions reached")
    return Decision(ACTION_SHORT, "short confluence passed")


def size_by_risk(account: Account, signal: StrategySignal, settings=None) -> float:
    """Notional sized so the structure stop risks ``risk_per_trade_pct`` of equity.

    qty = risk_amount / stop_distance  ->  notional = qty * entry. Capped by the
    per-position notional limit (max_position_pct * leverage) and deployable
    margin (cash * leverage * (1 - buffer)).
    """
    settings = settings or get_settings()
    entry, stop = signal.price, signal.stop_price
    if not entry or stop is None:
        return 0.0
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return 0.0
    leverage = max(1, getattr(settings, "futures_leverage", 1))
    risk_amount = account.equity * settings.risk_per_trade_pct
    notional = risk_amount * entry / stop_dist
    notional_cap = account.equity * settings.max_position_pct * leverage
    deployable = account.cash * leverage * (1.0 - settings.cash_buffer_pct)
    return max(0.0, min(notional, notional_cap, deployable))


def virtual_account(session: Session, positions: list[Position], settings=None) -> Account:
    """A virtual paper account anchored at ``paper_starting_equity`` ($10k).

    Equity/cash are derived from the bot's **own** trades, not the testnet's
    (large, arbitrary) fake balance, so the equity curve and sizing both behave
    like a clean $10k book:

        wallet = start + realized PnL (closed trades)
        equity = wallet + unrealized PnL (open positions)
        cash   = wallet - margin locked by open positions

    With no trades yet this returns exactly ``start`` — the curve begins at $10k.
    """
    settings = settings or get_settings()
    start = settings.paper_starting_equity
    leverage = max(1, getattr(settings, "futures_leverage", 1))

    realized = session.scalar(
        select(func.coalesce(func.sum(Trade.pnl), 0.0)).where(Trade.status == TRADE_CLOSED)
    ) or 0.0
    unrealized = sum(p.unrealized_pl for p in positions)
    used_margin = sum(p.market_value for p in positions) / leverage

    wallet = start + realized
    equity = wallet + unrealized
    cash = max(0.0, wallet - used_margin)
    return Account(equity=equity, cash=cash, buying_power=cash * leverage)


# --------------------------------------------------------------------------- #
# Main entry points
# --------------------------------------------------------------------------- #
def run_trading(session: Session, broker: Broker | None = None, dry_run: bool = False,
                signals: list[StrategySignal] | None = None,
                confirmer: Callable[[Asset, StrategySignal], tuple[bool, object]] | None = None) -> dict:
    settings = get_settings()
    broker = broker or get_broker()
    confirm = confirmer or confirm_setup  # Gemini second gate over the order-flow signal

    signals = generate_signals(session) if signals is None else signals
    positions = broker.get_positions()
    account = virtual_account(session, positions, settings)
    open_count = len(positions)
    pending = {s for s in (_config_symbol(o.symbol) for o in broker.list_open_orders()) if s}

    summary: dict = {
        "dry_run": dry_run,
        "equity": account.equity,
        "cash": account.cash,
        "signals": len(signals),
        "actions": [],
    }

    for sig in signals:
        symbol = sig.asset.symbol
        holding = _position_for(sig.asset, positions)

        if symbol in pending:
            _record_action(summary, sig, Decision(ACTION_HOLD, "pending order exists"))
            continue

        decision = decide(sig, holding, open_count, settings)

        # Second gate: only open a new position if the LLM also confirms the setup
        # (fail-open — confirm() returns True when the LLM is unavailable).
        verdict = None
        if decision.action in (ACTION_BUY, ACTION_SHORT):
            ok, verdict = confirm(sig.asset, sig)
            if not ok:
                reason = "LLM rejected setup"
                if verdict is not None and verdict.rationale:
                    reason = f"LLM rejected: {verdict.rationale[:160]}"
                decision = Decision(ACTION_HOLD, reason)

        notional = None
        if decision.action in (ACTION_BUY, ACTION_SHORT):
            notional = size_by_risk(account, sig, settings)
            if notional < MIN_NOTIONAL:
                decision = Decision(ACTION_HOLD, "insufficient margin / buffer")

        entry = _record_action(summary, sig, decision, notional, verdict)
        if dry_run or decision.action == ACTION_HOLD:
            continue

        try:
            order = None
            if decision.action == ACTION_BUY:
                order = broker.submit_order(symbol, SIDE_BUY, notional=notional)
                _open_trade(session, sig, SIDE_BUY, notional, order, settings, verdict)
                open_count += 1
            elif decision.action == ACTION_SHORT:
                order = broker.submit_order(symbol, SIDE_SELL, notional=notional)
                _open_trade(session, sig, SIDE_SELL, notional, order, settings, verdict)
                open_count += 1
            elif decision.action == ACTION_CLOSE:
                order = broker.close_position(symbol)
                exit_price = order.filled_avg_price or sig.price
                _close_trade(session, symbol, exit_price, CLOSE_SIGNAL, holding)
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
    """Reconcile open trades with the broker, apply stop/take/time exits, record
    equity, and score matured signals."""
    settings = get_settings()
    broker = broker or get_broker()

    positions = broker.get_positions()
    account = virtual_account(session, positions, settings)
    summary: dict = {"reconciled": 0, "closed": 0, "equity": account.equity, "actions": []}

    hold_ms = _max_hold_ms(settings)
    now = utcnow()

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
        if not reason and hold_ms and trade.created_at is not None:
            age_ms = (now - trade.created_at).total_seconds() * 1000
            if age_ms >= hold_ms:
                reason = CLOSE_MAX_HOLD
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
def _open_trade(session: Session, sig: StrategySignal, side: str, notional: float | None,
                order, settings, verdict=None) -> Trade:
    entry_price = order.filled_avg_price or sig.price  # refined later in sync
    stop_price = sig.stop_price
    take_profit = sig.target_price
    if stop_price is None:  # strategy should always provide one; fall back just in case
        stop_price, take_profit = _risk_exits(side, entry_price, settings)
    rationale = sig.prediction.rationale
    if verdict is not None:  # the LLM confirmation that opened the second gate
        prob = verdict.bullish_prob if sig.is_long else verdict.bearish_prob
        rationale = f"{rationale} || LLM ✓ {prob:.0f}%: {verdict.rationale}".strip()
    trade = Trade(
        asset=sig.asset.symbol,
        side=side,
        status=TRADE_SUBMITTED,
        qty=order.qty,
        notional=notional,
        entry_price=entry_price,
        alpaca_order_id=order.id,
        model=sig.prediction.model,
        rationale=rationale,
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
    """Fallback fixed-pct exits (only used if the strategy supplied no levels)."""
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


def _max_hold_ms(settings) -> float:
    """Live time-stop duration = max_hold_bars × the LTF interval (matches backtest)."""
    bars = getattr(settings, "max_hold_bars", 0)
    if not bars:
        return 0.0
    try:
        return bars * interval_ms(getattr(settings, "strategy_ltf", "15m"))
    except Exception:
        return 0.0


def _record_equity(session: Session, account: Account) -> EquitySnapshot:
    snap = EquitySnapshot(
        ts=utcnow(),
        equity=account.equity,
        cash=account.cash,
        buying_power=account.buying_power,
    )
    session.add(snap)
    return snap


def _record_action(summary: dict, sig: StrategySignal, decision: Decision,
                   notional: float | None = None, verdict=None) -> dict:
    res = sig.result
    entry = {
        "asset": sig.asset.symbol,
        "direction": res.direction,
        "score": f"{res.score}/{res.max_score}",
        "passed": res.passed,
        "action": decision.action,
        "reason": decision.reason,
        "notional": round(notional, 2) if notional else None,
        "order_id": None,
    }
    if verdict is not None:
        entry["llm"] = {
            "bullish_prob": verdict.bullish_prob,
            "bearish_prob": verdict.bearish_prob,
            "rationale": verdict.rationale,
        }
    summary["actions"].append(entry)
    logger.info(
        "%s: %s (%s) — %s score=%s/%s passed=%s",
        sig.asset.symbol, decision.action, decision.reason,
        res.direction, res.score, res.max_score, res.passed,
    )
    return entry


# --------------------------------------------------------------------------- #
# LLM confirmation gate (the order-flow setup must also convince the model)
# --------------------------------------------------------------------------- #
def _setup_context(sig: StrategySignal) -> dict:
    """Compact, model-friendly description of the order-flow setup to be judged."""
    r = sig.result
    return {
        "asset": sig.asset.symbol,
        "direction": r.direction,
        "mode": r.features.get("mode"),
        "confluence": f"{r.score}/{r.max_score}",
        "checks": r.checks,
        "features": r.features,
        "price": sig.price,
        "stop": r.stop_price,
        "target": r.target_price,
    }


def _verdict_ok(sig: StrategySignal, verdict, settings) -> bool:
    """The model agrees if its probability *in the setup's direction* clears the bar."""
    prob = verdict.bullish_prob if sig.is_long else verdict.bearish_prob
    return prob >= settings.llm_confirm_min


def confirm_setup(asset: Asset, sig: StrategySignal, provider=None, settings=None):
    """Ask the LLM to confirm an order-flow setup. Returns ``(ok, verdict | None)``.

    Fail-open: if confirmation is disabled, no model is usable, or the call errors
    after retries, returns ``(True, None)`` so the bot trades on the order-flow
    signal alone (per configuration).
    """
    settings = settings or get_settings()
    if not getattr(settings, "require_llm_confirmation", True):
        return True, None
    try:
        from app.llm.provider import get_provider

        provider = provider or get_provider()
        models = provider.available_models()
        judge = getattr(provider, "judge_setup", None)
        if not models or judge is None:
            logger.info("LLM confirm skipped for %s — no usable model (fail-open).", asset.symbol)
            return True, None
        model = settings.trading_model if settings.trading_model in models else models[0]
        verdict = judge(model, asset, _setup_context(sig))
    except Exception:
        logger.exception("LLM confirm errored for %s — fail-open.", asset.symbol)
        return True, None
    ok = _verdict_ok(sig, verdict, settings)
    logger.info(
        "%s: LLM %s (bull=%.0f/bear=%.0f) — %s",
        asset.symbol, "confirmed" if ok else "rejected",
        verdict.bullish_prob, verdict.bearish_prob, verdict.rationale,
    )
    return ok, verdict


# --------------------------------------------------------------------------- #
# Maintenance
# --------------------------------------------------------------------------- #
def reset_paper_data(session: Session, dry_run: bool = False) -> dict:
    """Wipe trade / equity / leaderboard history for a clean $10k restart.

    Deletes every Evaluation, Trade, Prediction and EquitySnapshot so the equity
    curve and stats start fresh. Used once when migrating accounts/strategies — the
    "never delete a losing trade" rule holds *within* a strategy's life, not across
    a deliberate account reset. Returns the row counts; ``dry_run`` reports them
    without deleting anything.
    """
    counts = {
        "evaluations": session.scalar(select(func.count()).select_from(Evaluation)) or 0,
        "trades": session.scalar(select(func.count()).select_from(Trade)) or 0,
        "predictions": session.scalar(select(func.count()).select_from(Prediction)) or 0,
        "equity_snapshots": session.scalar(select(func.count()).select_from(EquitySnapshot)) or 0,
    }
    if dry_run:
        return counts
    # Children before parents (Evaluation / Trade reference Prediction).
    session.execute(delete(Evaluation))
    session.execute(delete(Trade))
    session.execute(delete(Prediction))
    session.execute(delete(EquitySnapshot))
    session.commit()
    return counts
