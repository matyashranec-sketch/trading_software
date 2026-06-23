"""Integration tests for the confluence evaluator (side selection + gating)."""
from dataclasses import replace

from app.engine.strategy.confluence import LONG, MarketSnapshot, StrategyParams, evaluate
from app.sources.market_data import Candle


def mk(low, high, close, *, open=None, vol=100.0, taker=60.0, t=0):
    op = close if open is None else open
    return Candle(open_time=t, open=op, high=high, low=low, close=close, volume=vol,
                  close_time=t + 1, quote_volume=vol * close, trades=10, taker_buy_base=taker)


def _zigzag(pivots, leg=4, vol=100.0, taker=60.0):
    closes = []
    prev = pivots[0]
    for nxt in pivots[1:]:
        for s in range(1, leg + 1):
            closes.append(prev + (nxt - prev) * s / leg)
        prev = nxt
    out = []
    for i, cl in enumerate(closes):
        op = closes[i - 1] if i > 0 else cl
        hi = max(op, cl) * 1.003
        lo = min(op, cl) * 0.997
        out.append(mk(low=lo, high=hi, close=cl, open=op, vol=vol, taker=taker, t=i))
    return out


# Relaxed thresholds: test the *logic* (side + checks), not magic numbers.
PARAMS = StrategyParams(
    trend_ema_period=20, atr_min_pct=0.0, atr_max_pct=1.0, overext_atr_mult=999,
    min_confluence=3, swing_left=2, swing_right=2, sweep_recent=3,
)

UPTREND = [100, 96, 105, 101, 110, 106, 115, 111, 120, 116, 125]
RANGE = [100, 96, 100, 96, 100, 96, 100, 96, 100, 96, 100]


def test_ranging_market_stands_aside():
    rng = _zigzag(RANGE)
    snap = MarketSnapshot(asset_symbol="BTC", price=rng[-1].close, htf=rng, mtf=rng, ltf=rng)
    res = evaluate(snap, PARAMS)
    assert res.direction is None and res.passed is False


def test_uptrend_selects_long_and_passes_core_checks():
    up = _zigzag(UPTREND)
    # Last candle bullish with positive delta -> satisfies the CVD (order-flow) check.
    up[-1] = mk(low=up[-1].low, high=up[-1].high, close=up[-1].high,
                open=up[-1].low, vol=100, taker=95, t=up[-1].open_time)
    price = up[-1].close
    snap = MarketSnapshot(asset_symbol="BTC", price=price, htf=up, mtf=up, ltf=up)
    res = evaluate(snap, PARAMS)
    assert res.direction == LONG
    assert res.checks["trend"] is True   # price above the trend EMA
    assert res.checks["cvd"] is True      # positive-delta bullish trigger
    assert res.checks["risk"] is True
    assert res.features["structure"] == "up"


def test_weak_delta_no_longer_passes_order_flow_check():
    up = _zigzag(UPTREND)
    # weaken the last few candles to near-zero delta (taker ~= half of volume)
    for i in range(-PARAMS.delta_lookback, 0):
        c = up[i]
        up[i] = mk(low=c.low, high=c.high, close=c.close, open=c.open,
                   vol=100, taker=51, t=c.open_time)
    snap = MarketSnapshot(asset_symbol="BTC", price=up[-1].close, htf=up, mtf=up, ltf=up)
    res = evaluate(snap, PARAMS)
    assert res.checks["cvd"] is False   # no divergence + weak delta -> order flow fails
    assert res.passed is False          # cvd is mandatory


def test_modes_use_different_checklists():
    up = _zigzag(UPTREND)
    snap = MarketSnapshot(asset_symbol="BTC", price=up[-1].close, htf=up, mtf=up, ltf=up)
    rev = evaluate(snap, replace(PARAMS, mode="reversal"))
    mom = evaluate(snap, replace(PARAMS, mode="momentum"))
    assert "sweep" in rev.checks and "sweep" not in mom.checks  # dispatch differs
    assert rev.features["mode"] == "reversal" and mom.features["mode"] == "momentum"


def test_momentum_enters_on_confirmed_breakout():
    up = _zigzag(UPTREND)
    # strong aggressive buying on the breakout candle
    up[-1] = mk(low=up[-1].low, high=up[-1].high, close=up[-1].high,
                open=up[-1].low, vol=100, taker=95, t=up[-1].open_time)
    snap = MarketSnapshot(asset_symbol="BTC", price=up[-1].close, htf=up, mtf=up, ltf=up)
    res = evaluate(snap, replace(PARAMS, mode="momentum"))
    assert res.direction == LONG
    assert res.checks["bos"] is True and res.checks["cvd"] is True
    assert res.checks["location"] is True   # broke out above the value area
    assert res.passed is True


def test_momentum_rejects_weak_delta_breakout():
    up = _zigzag(UPTREND)
    for i in range(-PARAMS.delta_lookback, 0):
        c = up[i]
        up[i] = mk(low=c.low, high=c.high, close=c.close, open=c.open,
                   vol=100, taker=51, t=c.open_time)  # weak delta = possible fake breakout
    snap = MarketSnapshot(asset_symbol="BTC", price=up[-1].close, htf=up, mtf=up, ltf=up)
    res = evaluate(snap, replace(PARAMS, mode="momentum"))
    assert res.checks["cvd"] is False and res.passed is False


def test_funding_and_obi_checks_only_count_when_present():
    up = _zigzag(UPTREND)
    base = MarketSnapshot(asset_symbol="BTC", price=up[-1].close, htf=up, mtf=up, ltf=up)
    res_plain = evaluate(base, PARAMS)
    assert "funding" not in res_plain.checks and "obi" not in res_plain.checks

    with_extras = MarketSnapshot(
        asset_symbol="BTC", price=up[-1].close, htf=up, mtf=up, ltf=up,
        funding_rate=0.0001, book_imbalance=0.5,
    )
    res = evaluate(with_extras, PARAMS)
    assert "funding" in res.checks and "obi" in res.checks
    assert res.max_score == res_plain.max_score + 2
