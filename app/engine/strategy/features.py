"""Pure feature functions over candle series — the building blocks of the
order-flow confluence. Everything here is deterministic and side-effect free so
the **same code runs live and in the backtest** (no logic drift).

No numpy/pandas on purpose: the series are short (hundreds of bars) and keeping
this dependency-free keeps the bot light on a tiny VM.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.sources.market_data import Candle


# --------------------------------------------------------------------------- #
# Moving averages / volatility
# --------------------------------------------------------------------------- #
def ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average series (same length as ``values``)."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema_last(values: list[float], period: int) -> float:
    return ema(values, period)[-1] if values else 0.0


def true_ranges(candles: list[Candle]) -> list[float]:
    if not candles:
        return []
    trs = [candles[0].high - candles[0].low]
    prev_close = candles[0].close
    for c in candles[1:]:
        trs.append(max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close)))
        prev_close = c.close
    return trs


def atr(candles: list[Candle], period: int = 14) -> float:
    """Average True Range (simple mean of the last ``period`` true ranges)."""
    trs = true_ranges(candles)
    if not trs:
        return 0.0
    window = trs[-period:] if len(trs) >= period else trs
    return sum(window) / len(window)


# --------------------------------------------------------------------------- #
# Swing structure
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Swing:
    index: int
    price: float


def swing_highs(candles: list[Candle], left: int = 2, right: int = 2) -> list[Swing]:
    """Fractal pivot highs: a high strictly above its ``left``/``right`` neighbours."""
    out: list[Swing] = []
    for i in range(left, len(candles) - right):
        h = candles[i].high
        if all(candles[j].high < h for j in range(i - left, i)) and all(
            candles[j].high <= h for j in range(i + 1, i + right + 1)
        ):
            out.append(Swing(i, h))
    return out


def swing_lows(candles: list[Candle], left: int = 2, right: int = 2) -> list[Swing]:
    """Fractal pivot lows: a low strictly below its ``left``/``right`` neighbours."""
    out: list[Swing] = []
    for i in range(left, len(candles) - right):
        low = candles[i].low
        if all(candles[j].low > low for j in range(i - left, i)) and all(
            candles[j].low >= low for j in range(i + 1, i + right + 1)
        ):
            out.append(Swing(i, low))
    return out


def market_structure(candles: list[Candle], left: int = 2, right: int = 2) -> str:
    """Classify trend from the last two swing highs and lows.

    Returns ``"up"`` (HH + HL), ``"down"`` (LH + LL) or ``"range"``.
    """
    highs = swing_highs(candles, left, right)
    lows = swing_lows(candles, left, right)
    if len(highs) < 2 or len(lows) < 2:
        return "range"
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl:
        return "up"
    if lh and ll:
        return "down"
    return "range"


# --------------------------------------------------------------------------- #
# Order flow: CVD + divergence
# --------------------------------------------------------------------------- #
def cvd_series(candles: list[Candle]) -> list[float]:
    """Cumulative Volume Delta: running sum of per-candle taker delta."""
    out: list[float] = []
    run = 0.0
    for c in candles:
        run += c.delta
        out.append(run)
    return out


def bullish_cvd_divergence(candles: list[Candle], cvd: list[float],
                           left: int = 2, right: int = 2) -> bool:
    """Price prints a lower low while CVD prints a higher low (absorption / sellers
    exhausted) — a bullish order-flow divergence."""
    lows = swing_lows(candles, left, right)
    if len(lows) < 2:
        return False
    prev, last = lows[-2], lows[-1]
    return last.price < prev.price and cvd[last.index] > cvd[prev.index]


def bearish_cvd_divergence(candles: list[Candle], cvd: list[float],
                           left: int = 2, right: int = 2) -> bool:
    """Price prints a higher high while CVD prints a lower high — bearish divergence."""
    highs = swing_highs(candles, left, right)
    if len(highs) < 2:
        return False
    prev, last = highs[-2], highs[-1]
    return last.price > prev.price and cvd[last.index] < cvd[prev.index]


# --------------------------------------------------------------------------- #
# Liquidity sweeps (stop runs + reclaim)
# --------------------------------------------------------------------------- #
def bullish_sweep(candles: list[Candle], recent: int = 3,
                  left: int = 2, right: int = 2) -> Swing | None:
    """A recent bar pierced a prior swing low (stop run) and price closed back above it.

    Returns the swept swing low, or ``None``.
    """
    if len(candles) <= recent:
        return None
    prior = [s for s in swing_lows(candles, left, right) if s.index < len(candles) - recent]
    if not prior:
        return None
    level = min(prior, key=lambda s: s.price)  # the most obvious resting liquidity
    window = candles[-recent:]
    pierced = any(c.low < level.price for c in window)
    reclaimed = candles[-1].close > level.price
    return level if pierced and reclaimed else None


def bearish_sweep(candles: list[Candle], recent: int = 3,
                  left: int = 2, right: int = 2) -> Swing | None:
    """A recent bar pierced a prior swing high and price closed back below it."""
    if len(candles) <= recent:
        return None
    prior = [s for s in swing_highs(candles, left, right) if s.index < len(candles) - recent]
    if not prior:
        return None
    level = max(prior, key=lambda s: s.price)
    window = candles[-recent:]
    pierced = any(c.high > level.price for c in window)
    reclaimed = candles[-1].close < level.price
    return level if pierced and reclaimed else None


# --------------------------------------------------------------------------- #
# Break of structure
# --------------------------------------------------------------------------- #
def bullish_bos(candles: list[Candle], left: int = 2, right: int = 2) -> bool:
    """Last close breaks above the most recent confirmed swing high."""
    highs = swing_highs(candles, left, right)
    return bool(highs) and candles[-1].close > highs[-1].price


def bearish_bos(candles: list[Candle], left: int = 2, right: int = 2) -> bool:
    """Last close breaks below the most recent confirmed swing low."""
    lows = swing_lows(candles, left, right)
    return bool(lows) and candles[-1].close < lows[-1].price


# --------------------------------------------------------------------------- #
# Location: volume profile + VWAP
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ValueArea:
    poc: float        # price with the most traded volume
    low: float        # value-area low (≈70% volume band)
    high: float       # value-area high


def volume_profile(candles: list[Candle], bins: int = 24,
                   value_pct: float = 0.70) -> ValueArea:
    """Approximate volume profile from candles (volume binned by typical price)."""
    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    last = candles[-1].close
    if hi <= lo:
        return ValueArea(poc=last, low=lo, high=hi)
    width = (hi - lo) / bins
    vol = [0.0] * bins
    for c in candles:
        tp = (c.high + c.low + c.close) / 3.0
        b = min(bins - 1, int((tp - lo) / width))
        vol[b] += c.volume

    poc_bin = max(range(bins), key=lambda i: vol[i])
    total = sum(vol)
    target = value_pct * total
    acc = vol[poc_bin]
    lo_b = hi_b = poc_bin
    while acc < target and (lo_b > 0 or hi_b < bins - 1):
        left = vol[lo_b - 1] if lo_b > 0 else -1.0
        right = vol[hi_b + 1] if hi_b < bins - 1 else -1.0
        if right >= left:
            hi_b += 1
            acc += vol[hi_b]
        else:
            lo_b -= 1
            acc += vol[lo_b]
    return ValueArea(
        poc=lo + (poc_bin + 0.5) * width,
        low=lo + lo_b * width,
        high=lo + (hi_b + 1) * width,
    )


def vwap(candles: list[Candle]) -> float:
    """Volume-weighted average price anchored at the start of the given window."""
    num = den = 0.0
    for c in candles:
        tp = (c.high + c.low + c.close) / 3.0
        num += tp * c.volume
        den += c.volume
    return num / den if den > 0 else candles[-1].close
