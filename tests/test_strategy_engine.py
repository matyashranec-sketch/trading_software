"""Tests for the strategy signal generator (DB logging + signal shape)."""
from app.config import HORIZONS
from app.engine.strategy import engine as E
from app.engine.strategy.confluence import MarketSnapshot
from app.models import BULLISH, Evaluation, Prediction
from app.sources.market_data import Candle


def _uptrend(n_pivots=18, leg=5):
    pivots = []
    for k in range(n_pivots):
        pivots.append(100 + 4 * (k // 2) if k % 2 == 0 else 108 + 4 * (k // 2))
    closes = []
    prev = pivots[0]
    for nxt in pivots[1:]:
        for s in range(1, leg + 1):
            closes.append(prev + (nxt - prev) * s / leg)
        prev = nxt
    out = []
    for i, cl in enumerate(closes):
        op = closes[i - 1] if i > 0 else cl
        out.append(Candle(open_time=i, open=op, high=max(op, cl) * 1.003,
                          low=min(op, cl) * 0.997, close=cl, volume=100.0,
                          close_time=i + 1, quote_volume=100.0 * cl, trades=10,
                          taker_buy_base=70.0))
    return out


def test_generate_signals_logs_predictions(db, monkeypatch):
    up = _uptrend()
    snap = MarketSnapshot(asset_symbol="BTC", price=up[-1].close, htf=up, mtf=up, ltf=up)
    monkeypatch.setattr(E, "build_snapshot", lambda asset, settings=None: snap)

    signals = E.generate_signals(db)

    assert signals, "expected directional signals in an uptrend"
    for sig in signals:
        assert sig.prediction.model == E.MODEL_NAME
        assert sig.direction == BULLISH          # uptrend -> long bias
        assert sig.prediction.bullish_prob >= sig.prediction.bearish_prob

    preds = db.query(Prediction).all()
    assert len(preds) == len(signals)
    evals = db.query(Evaluation).count()
    assert evals == len(signals) * len(HORIZONS)
    # context JSON (confluence breakdown) is stored for transparency
    assert '"checks"' in preds[0].news_snapshot
