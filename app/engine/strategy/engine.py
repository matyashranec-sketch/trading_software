"""Live signal generation for the order-flow strategy.

Mirrors the old :func:`app.engine.predictor.generate_signals` contract (returns a
list of signals the trader can act on, and logs each as a ``Prediction`` so the
accuracy leaderboard keeps working) — but the brain is the deterministic
:func:`app.engine.strategy.confluence.evaluate`, not the news LLM.

Market data comes from Binance **mainnet** public futures endpoints (real flow);
orders execute on the testnet via the broker. The confluence checklist is stored
as JSON in ``Prediction.news_snapshot`` (repurposed as a generic context blob —
no schema migration needed).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import ASSETS, HORIZONS, Asset, get_settings
from app.engine.strategy import confluence as C
from app.engine.strategy.confluence import ConfluenceResult, MarketSnapshot, StrategyParams
from app.models import BEARISH, BULLISH, Evaluation, Prediction, utcnow
from app.sources.market_data import (
    MarketDataUnavailable,
    fetch_depth,
    fetch_funding_rate,
    fetch_klines,
    fetch_open_interest,
)

logger = logging.getLogger(__name__)

MODEL_NAME = "orderflow-v1"


@dataclass
class StrategySignal:
    """One strategy decision for the trader (a stored Prediction + confluence)."""

    asset: Asset
    prediction: Prediction
    result: ConfluenceResult

    @property
    def passed(self) -> bool:
        return self.result.passed

    @property
    def is_long(self) -> bool:
        return self.result.direction == C.LONG

    @property
    def direction(self) -> str:
        return BULLISH if self.is_long else BEARISH

    @property
    def confidence(self) -> float:
        return self.result.score_pct

    @property
    def price(self) -> float:
        return self.prediction.price_at_prediction

    @property
    def stop_price(self) -> float | None:
        return self.result.stop_price

    @property
    def target_price(self) -> float | None:
        return self.result.target_price


def params_from_settings(settings=None) -> StrategyParams:
    """Build StrategyParams from Settings (falls back to dataclass defaults)."""
    s = settings or get_settings()
    d = StrategyParams()
    get = lambda name, default: getattr(s, name, default)  # noqa: E731
    return StrategyParams(
        trend_ema_period=get("strategy_trend_ema", d.trend_ema_period),
        atr_period=get("strategy_atr_period", d.atr_period),
        atr_min_pct=get("strategy_atr_min_pct", d.atr_min_pct),
        atr_max_pct=get("strategy_atr_max_pct", d.atr_max_pct),
        overext_atr_mult=get("strategy_overext_atr_mult", d.overext_atr_mult),
        reward_risk=get("strategy_reward_risk", d.reward_risk),
        atr_stop_mult=get("strategy_atr_stop_mult", d.atr_stop_mult),
        funding_cap=get("strategy_funding_cap", d.funding_cap),
        min_confluence=get("min_confluence", d.min_confluence),
    )


def build_snapshot(asset: Asset, settings=None) -> MarketSnapshot:
    """Fetch the multi-timeframe data the confluence needs (live, futures data)."""
    s = settings or get_settings()
    pair = asset.binance_symbol or f"{asset.symbol}USDT"
    futures = s.broker == "binance_futures"
    htf_i = getattr(s, "strategy_htf", "4h")
    mtf_i = getattr(s, "strategy_mtf", "1h")
    ltf_i = getattr(s, "strategy_ltf", "15m")

    htf = fetch_klines(pair, htf_i, limit=200, futures=futures)
    mtf = fetch_klines(pair, mtf_i, limit=300, futures=futures)
    ltf = fetch_klines(pair, ltf_i, limit=200, futures=futures)

    funding = oi = imbalance = None
    if futures:
        for fn, name in ((lambda: fetch_funding_rate(pair), "funding"),
                         (lambda: fetch_open_interest(pair), "open interest")):
            try:
                val = fn()
            except MarketDataUnavailable as exc:
                logger.debug("%s unavailable for %s: %s", name, pair, exc)
                val = None
            if name == "funding":
                funding = val
            else:
                oi = val
    try:
        imbalance = fetch_depth(pair, limit=100, futures=futures).imbalance()
    except MarketDataUnavailable as exc:
        logger.debug("depth unavailable for %s: %s", pair, exc)

    return MarketSnapshot(
        asset_symbol=asset.symbol, price=ltf[-1].close,
        htf=htf, mtf=mtf, ltf=ltf,
        funding_rate=funding, open_interest=oi, book_imbalance=imbalance,
    )


def generate_signals(session: Session, settings=None) -> list[StrategySignal]:
    """Evaluate every tradable asset; log directional signals; return them."""
    s = settings or get_settings()
    params = params_from_settings(s)
    signals: list[StrategySignal] = []

    for asset in ASSETS:
        if not asset.tradable:
            continue
        try:
            snap = build_snapshot(asset, s)
        except MarketDataUnavailable as exc:
            logger.warning("Skipping %s: %s", asset.symbol, exc)
            continue

        res = C.evaluate(snap, params)
        if res.direction is None:
            logger.info("%s: no directional bias (%s)", asset.symbol, res.rationale)
            continue

        prediction = _store_prediction(session, asset, snap.price, res)
        signals.append(StrategySignal(asset=asset, prediction=prediction, result=res))
        logger.info("%s: %s", asset.symbol, res.rationale)

    session.commit()
    return signals


def _store_prediction(session: Session, asset: Asset, price: float,
                      res: ConfluenceResult) -> Prediction:
    now = utcnow()
    is_long = res.direction == C.LONG
    context = json.dumps({
        "passed": res.passed,
        "direction": res.direction,
        "score": res.score,
        "max_score": res.max_score,
        "checks": res.checks,
        "features": res.features,
        "stop": res.stop_price,
        "target": res.target_price,
    })
    prediction = Prediction(
        created_at=now,
        asset=asset.symbol,
        model=MODEL_NAME,
        direction=BULLISH if is_long else BEARISH,
        bullish_prob=res.score_pct if is_long else 0.0,
        bearish_prob=0.0 if is_long else res.score_pct,
        price_at_prediction=price,
        rationale=res.rationale,
        news_snapshot=context,
    )
    session.add(prediction)
    session.flush()  # assign id

    for horizon_name, delta in HORIZONS.items():
        session.add(Evaluation(
            prediction_id=prediction.id, horizon=horizon_name,
            target_eval_time=now + delta, status="pending",
        ))
    return prediction
