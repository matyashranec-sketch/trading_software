"""Order-flow confluence — the single source of truth for trade decisions.

``evaluate()`` takes a :class:`MarketSnapshot` (multi-timeframe candles + a few
scalars) and returns a :class:`ConfluenceResult`: the trade direction, a strict
pass/fail, the per-condition checklist, and structure-based stop/target.

The **same function runs live and in the backtest** — that's what makes the
backtest trustworthy. Live-only inputs (order-book imbalance, funding) are
optional: when absent (as in a historical backtest) their checks simply don't
count, rather than silently passing.

Strategy intent (symmetric long/short): trade only **with** the higher-timeframe
trend, on a **pullback into value**, after a **liquidity sweep**, confirmed by
**order flow** (CVD divergence / delta) and a **break of structure**, with sane
**ATR risk** — and, on futures, only when **funding** isn't crowding our side.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.engine.strategy import features as F
from app.sources.market_data import Candle

LONG = "long"
SHORT = "short"

# Checks that must ALL pass for any trade (the non-negotiable core).
MANDATORY = ("trend", "cvd", "risk")


@dataclass(frozen=True)
class StrategyParams:
    """Tunable knobs (overridden from Settings in production; defaults here keep
    the strategy usable/testable standalone)."""

    trend_ema_period: int = 50
    atr_period: int = 14
    atr_min_pct: float = 0.003     # below this = dead market, skip
    atr_max_pct: float = 0.08      # above this = too wild, skip
    overext_atr_mult: float = 4.0  # price must be within N*ATR of the HTF trend EMA
    swing_left: int = 2
    swing_right: int = 2
    sweep_recent: int = 3
    vol_bins: int = 24
    reward_risk: float = 2.0       # target = entry +/- RR * risk
    atr_stop_mult: float = 1.5     # fallback stop distance when no sweep level
    funding_cap: float = 0.0005    # |funding| above this crowds that side
    min_confluence: int = 5        # how many checks must pass (strict)
    delta_strength_min: float = 0.15  # min |taker delta| / volume for the order-flow check
    delta_lookback: int = 3        # candles for the delta-strength read
    cvd_lookback: int = 20         # bars for the CVD-slope read


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    asset_symbol: str
    price: float
    htf: list[Candle]   # trend timeframe (e.g. 4h)
    mtf: list[Candle]   # structure / value / CVD (e.g. 1h)
    ltf: list[Candle]   # sweep / trigger (e.g. 15m)
    funding_rate: float | None = None
    open_interest: float | None = None
    book_imbalance: float | None = None  # None in backtest -> check not counted


@dataclass
class ConfluenceResult:
    direction: str | None
    passed: bool
    score: int                 # number of applicable checks that passed
    max_score: int             # number of applicable checks
    checks: dict[str, bool]
    stop_price: float | None = None
    target_price: float | None = None
    rationale: str = ""
    features: dict = field(default_factory=dict)

    @property
    def score_pct(self) -> float:
        """0–100, reused as the stored Prediction 'confidence'."""
        return round(100.0 * self.score / self.max_score, 1) if self.max_score else 0.0


def _no_trade(reason: str) -> ConfluenceResult:
    return ConfluenceResult(direction=None, passed=False, score=0, max_score=0,
                            checks={}, rationale=reason)


def evaluate(snap: MarketSnapshot, params: StrategyParams | None = None) -> ConfluenceResult:
    p = params or StrategyParams()
    htf, mtf, ltf = snap.htf, snap.mtf, snap.ltf

    # Need enough history on every timeframe to form structure.
    min_len = max(p.trend_ema_period, 2 * (p.swing_left + p.swing_right) + 4)
    if len(htf) < min_len or len(mtf) < min_len or len(ltf) < p.sweep_recent + 6:
        return _no_trade("insufficient history")

    price = snap.price
    htf_ema = F.ema_last([c.close for c in htf], p.trend_ema_period)
    structure = F.market_structure(htf, p.swing_left, p.swing_right)

    # --- pick a candidate side from the higher-timeframe trend ---
    if structure == "up":
        direction = LONG
    elif structure == "down":
        direction = SHORT
    else:
        return _no_trade("HTF structure is ranging — stand aside")

    # --- shared features ---
    a = F.atr(mtf, p.atr_period)
    atr_pct = a / price if price else 0.0
    mtf_cvd = F.cvd_series(mtf)
    fair = F.vwap(mtf)
    va = F.volume_profile(mtf, p.vol_bins)
    last_ltf = ltf[-1]
    args = (p.swing_left, p.swing_right)

    dstr = F.delta_strength(ltf, p.delta_lookback)
    cslope = F.cvd_slope(mtf_cvd, p.cvd_lookback)
    in_value = va.low <= price <= va.high   # trading at value, not extended

    checks: dict[str, bool] = {}
    feats: dict = {
        "structure": structure, "htf_ema": round(htf_ema, 6), "atr_pct": round(atr_pct, 5),
        "vwap": round(fair, 6), "poc": round(va.poc, 6),
        "value_low": round(va.low, 6), "value_high": round(va.high, 6),
        "cvd": round(mtf_cvd[-1], 4), "cvd_slope": round(cslope, 4),
        "delta_strength": round(dstr, 4),
        "funding": snap.funding_rate, "book_imbalance": snap.book_imbalance,
    }

    # risk filter (volatility sane + not over-extended from the trend EMA)
    risk_ok = (
        p.atr_min_pct <= atr_pct <= p.atr_max_pct
        and a > 0
        and abs(price - htf_ema) <= p.overext_atr_mult * a
    )
    checks["risk"] = risk_ok
    checks["location"] = in_value

    swept: F.Swing | None = None
    if direction == LONG:
        checks["trend"] = price > htf_ema
        swept = F.bullish_sweep(ltf, p.sweep_recent, *args)
        checks["sweep"] = swept is not None
        # real order flow: CVD divergence OR genuinely strong buy delta with rising CVD
        checks["cvd"] = F.bullish_cvd_divergence(mtf, mtf_cvd, *args) or (
            dstr >= p.delta_strength_min and cslope > 0
        )
        checks["bos"] = F.bullish_bos(ltf, *args)
        if snap.funding_rate is not None:
            checks["funding"] = snap.funding_rate <= p.funding_cap
        if snap.book_imbalance is not None:
            checks["obi"] = snap.book_imbalance > 0
    else:  # SHORT
        checks["trend"] = price < htf_ema
        swept = F.bearish_sweep(ltf, p.sweep_recent, *args)
        checks["sweep"] = swept is not None
        checks["cvd"] = F.bearish_cvd_divergence(mtf, mtf_cvd, *args) or (
            dstr <= -p.delta_strength_min and cslope < 0
        )
        checks["bos"] = F.bearish_bos(ltf, *args)
        if snap.funding_rate is not None:
            checks["funding"] = snap.funding_rate >= -p.funding_cap
        if snap.book_imbalance is not None:
            checks["obi"] = snap.book_imbalance < 0

    score = sum(1 for v in checks.values() if v)
    max_score = len(checks)
    mandatory_ok = all(checks.get(k, False) for k in MANDATORY)
    passed = mandatory_ok and score >= p.min_confluence

    stop_price = target_price = None
    if passed:
        stop_price, target_price = _stop_target(direction, price, a, swept, p)

    result = ConfluenceResult(
        direction=direction, passed=passed, score=score, max_score=max_score,
        checks=checks, stop_price=stop_price, target_price=target_price,
        rationale=_rationale(direction, checks, passed, mandatory_ok, p),
        features=feats,
    )
    return result


def _stop_target(direction: str, price: float, atr: float, swept, p: StrategyParams):
    """Structure-based stop (just beyond the swept level, else ATR) + RR target."""
    buffer = 0.1 * atr
    if direction == LONG:
        stop = (swept.price - buffer) if swept else (price - p.atr_stop_mult * atr)
        stop = min(stop, price - buffer)  # never above entry
        risk = price - stop
        return round(stop, 8), round(price + p.reward_risk * risk, 8)
    stop = (swept.price + buffer) if swept else (price + p.atr_stop_mult * atr)
    stop = max(stop, price + buffer)
    risk = stop - price
    return round(stop, 8), round(price - p.reward_risk * risk, 8)


def _rationale(direction, checks, passed, mandatory_ok, p) -> str:
    marks = " ".join(f"{'✓' if v else '✗'}{k}" for k, v in checks.items())
    n = sum(1 for v in checks.values() if v)
    verdict = (
        f"TRADE {direction.upper()}" if passed
        else ("no trade — mandatory check failed" if not mandatory_ok
              else f"no trade — {n}/{p.min_confluence} confluence")
    )
    return f"{verdict} | {marks}"
