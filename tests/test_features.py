"""Unit tests for the strategy feature functions (CVD, divergence, sweeps, …)."""
from app.engine.strategy import features as F
from app.sources.market_data import Candle


def mk(low, high, close, *, open=None, vol=100.0, taker=60.0, t=0):
    op = close if open is None else open
    return Candle(open_time=t, open=op, high=high, low=low, close=close, volume=vol,
                  close_time=t + 1, quote_volume=vol * close, trades=10, taker_buy_base=taker)


def test_ema_matches_manual():
    out = F.ema([1, 2, 3, 4], 3)  # k = 0.5
    assert abs(out[-1] - 3.125) < 1e-9


def test_atr_constant_range():
    candles = [mk(low=98, high=100, close=99, open=99) for _ in range(20)]
    assert abs(F.atr(candles, 14) - 2.0) < 1e-6


def test_cvd_accumulates_delta():
    candles = [mk(low=1, high=2, close=1.5, vol=100, taker=70) for _ in range(3)]
    # delta per candle = 2*70-100 = 40
    assert F.cvd_series(candles) == [40.0, 80.0, 120.0]


def test_market_structure_uptrend_and_range():
    up = _zigzag([100, 96, 104, 100, 108, 104, 112])
    assert F.market_structure(up) == "up"
    rng = _zigzag([100, 96, 100, 96, 100, 96, 100])
    assert F.market_structure(rng) == "range"


def test_bullish_cvd_divergence():
    # Two swing lows: idx2 @100 then idx7 @98 (lower low) but CVD higher at idx7.
    rows = [
        mk(low=105, high=106, close=105.5, taker=50),   # 0
        mk(low=102, high=104, close=103, taker=50),     # 1
        mk(low=100, high=103, close=101, taker=50),     # 2 swing low #1
        mk(low=101, high=104, close=103, taker=90),     # 3  +80
        mk(low=102, high=105, close=104, taker=90),     # 4
        mk(low=101, high=104, close=102, taker=90),     # 5
        mk(low=100.5, high=103, close=101, taker=90),   # 6
        mk(low=98, high=101, close=99, taker=90),       # 7 swing low #2 (lower)
        mk(low=100, high=102, close=101, taker=50),     # 8
        mk(low=101, high=103, close=102, taker=50),     # 9
        mk(low=102, high=104, close=103, taker=50),     # 10
    ]
    cvd = F.cvd_series(rows)
    assert F.bullish_cvd_divergence(rows, cvd) is True
    assert F.bearish_cvd_divergence(rows, cvd) is False


def test_bullish_sweep_detects_stop_run_and_reclaim():
    rows = [
        mk(low=106, high=107, close=105),   # 0
        mk(low=104, high=105, close=103),   # 1
        mk(low=102, high=103, close=101),   # 2
        mk(low=100, high=103, close=101),   # 3 swing low @100
        mk(low=101, high=104, close=102),   # 4
        mk(low=103, high=106, close=104),   # 5
        mk(low=104, high=107, close=105),   # 6
        mk(low=105, high=108, close=106),   # 7
        mk(low=106, high=109, close=107),   # 8
        mk(low=103, high=106, close=104),   # 9
        mk(low=99, high=103, close=102),    # 10 wick pierces 100
        mk(low=101, high=104, close=103),   # 11 closes back above -> reclaim
    ]
    swept = F.bullish_sweep(rows, recent=3)
    assert swept is not None and swept.price == 100


def test_bullish_bos_breaks_recent_swing_high():
    rows = [
        mk(low=99, high=101, close=100),
        mk(low=100, high=103, close=101),
        mk(low=101, high=105, close=102),   # swing high @105
        mk(low=100, high=103, close=101),
        mk(low=99, high=102, close=100),
        mk(low=101, high=104, close=103),
        mk(low=104, high=107, close=106),   # close 106 > 105 -> BOS up
    ]
    assert F.bullish_bos(rows) is True


def test_volume_profile_poc_at_heavy_price():
    rows = [mk(low=49, high=51, close=50, vol=1000) for _ in range(5)]
    rows += [mk(low=59, high=61, close=60, vol=10) for _ in range(5)]
    va = F.volume_profile(rows, bins=24)
    assert abs(va.poc - 50) < 2.0  # POC sits at the heavy 50 level


def _zigzag(pivots, leg=3, vol=100.0, taker=60.0):
    """Build candles tracing a path through pivot prices (clean fractal swings)."""
    closes = []
    prev = pivots[0]
    for nxt in pivots[1:]:
        for s in range(1, leg + 1):
            closes.append(prev + (nxt - prev) * s / leg)
        prev = nxt
    out = []
    for i, cl in enumerate(closes):
        op = closes[i - 1] if i > 0 else cl
        hi = max(op, cl) * 1.002
        lo = min(op, cl) * 0.998
        out.append(mk(low=lo, high=hi, close=cl, open=op, vol=vol, taker=taker, t=i))
    return out
