import time

import app.engine.predictor as predictor_mod
import app.engine.trader as trader_mod
from app.broker.base import Account
from app.config import Asset, Settings
from app.engine.predictor import Signal
from app.engine.trader import (
    ACTION_BUY,
    ACTION_CLOSE,
    ACTION_HOLD,
    decide,
    run_sync,
    run_trading,
    size_notional,
)
from app.llm.base import LLMProvider, PredictionResult
from app.models import (
    BEARISH,
    BULLISH,
    SIDE_BUY,
    TRADE_CLOSED,
    TRADE_OPEN,
    TRADE_SUBMITTED,
    EquitySnapshot,
    Prediction,
    Trade,
)
from app.sources.news import NewsItem
from tests.conftest import FakeBroker, long_position

AAPL = Asset("AAPL", "Apple", "stock")
BTC = Asset("BTC", "Bitcoin", "crypto", coingecko_id="bitcoin")


class StubProvider(LLMProvider):
    def __init__(self, bullish=80.0, bearish=20.0):
        self.bullish, self.bearish = bullish, bearish

    def available_models(self):
        return ["stub-model"]

    def predict(self, model, asset, news):
        return PredictionResult(self.bullish, self.bearish, "why")


def _fresh():
    return [NewsItem("h", "s", "src", "u", int(time.time()))]


def _stub_signals(monkeypatch, assets, *, price=100.0, news=None):
    monkeypatch.setattr(predictor_mod, "ASSETS", assets)
    monkeypatch.setattr(predictor_mod, "fetch_price", lambda asset: price)
    monkeypatch.setattr(
        predictor_mod, "fetch_news",
        lambda asset: _fresh() if news is None else news,
    )


def make_signal(direction, conf=80.0, fresh=True, asset=AAPL):
    bull, bear = (conf, 100 - conf) if direction == BULLISH else (100 - conf, conf)
    pred = Prediction(
        asset=asset.symbol, model="m", direction=direction,
        bullish_prob=bull, bearish_prob=bear, price_at_prediction=100.0,
        rationale="", news_snapshot="[]",
    )
    return Signal(asset=asset, prediction=pred, has_fresh_news=fresh, news=[])


# --------------------------------------------------------------------------- #
# decide() — pure decision logic
# --------------------------------------------------------------------------- #
def test_decide_buys_on_bullish_fresh_high_confidence():
    d = decide(make_signal(BULLISH, 80), None, 0, True, Settings())
    assert d.action == ACTION_BUY


def test_decide_holds_without_fresh_news():
    d = decide(make_signal(BULLISH, 90, fresh=False), None, 0, True, Settings())
    assert d.action == ACTION_HOLD and "fresh" in d.reason


def test_decide_holds_on_low_confidence():
    d = decide(make_signal(BULLISH, 55), None, 0, True, Settings())
    assert d.action == ACTION_HOLD and "confidence" in d.reason


def test_decide_holds_stock_when_market_closed():
    d = decide(make_signal(BULLISH, 80), None, 0, False, Settings())
    assert d.action == ACTION_HOLD and "market" in d.reason


def test_decide_holds_when_already_long():
    holding = long_position("AAPL", 10, 90)
    d = decide(make_signal(BULLISH, 80), holding, 1, True, Settings())
    assert d.action == ACTION_HOLD and "already long" in d.reason


def test_decide_closes_long_on_bearish():
    holding = long_position("AAPL", 10, 90)
    d = decide(make_signal(BEARISH, 80), holding, 1, True, Settings())
    assert d.action == ACTION_CLOSE


def test_decide_holds_bearish_without_position_when_no_short():
    d = decide(make_signal(BEARISH, 80), None, 0, True, Settings(allow_short=False))
    assert d.action == ACTION_HOLD


def test_decide_respects_max_open_positions():
    d = decide(make_signal(BULLISH, 80), None, 5, True, Settings(max_open_positions=5))
    assert d.action == ACTION_HOLD and "max open" in d.reason


def test_decide_crypto_ignores_market_hours():
    d = decide(make_signal(BULLISH, 80, asset=BTC), None, 0, False, Settings())
    assert d.action == ACTION_BUY


# --------------------------------------------------------------------------- #
# size_notional()
# --------------------------------------------------------------------------- #
def test_size_notional_uses_position_pct():
    acct = Account(equity=10_000, cash=10_000, buying_power=10_000)
    assert size_notional(acct, 80, Settings(max_position_pct=0.10)) == 1_000


def test_size_notional_capped_by_cash_buffer():
    acct = Account(equity=10_000, cash=500, buying_power=10_000)
    # target 1000 but only 500*(1-0.1)=450 deployable
    assert size_notional(acct, 80, Settings(max_position_pct=0.10)) == 450


def test_size_notional_scales_by_confidence():
    acct = Account(equity=10_000, cash=10_000, buying_power=10_000)
    s = Settings(max_position_pct=0.10, scale_size_by_confidence=True)
    assert size_notional(acct, 80, s) == 800


# --------------------------------------------------------------------------- #
# run_trading() — end to end with a fake broker
# --------------------------------------------------------------------------- #
def test_run_trading_opens_long(db, monkeypatch):
    _stub_signals(monkeypatch, [AAPL])
    broker = FakeBroker(equity=10_000, cash=10_000)

    summary = run_trading(db, broker=broker, provider=StubProvider(80, 20))

    assert broker.submitted == [("AAPL", "buy", 1_000.0, None)]
    trades = db.query(Trade).all()
    assert len(trades) == 1
    t = trades[0]
    assert t.side == SIDE_BUY and t.status == TRADE_SUBMITTED
    assert t.notional == 1_000.0 and t.entry_price == 100.0
    assert t.model == "stub-model" and t.prediction_id is not None
    assert db.query(EquitySnapshot).count() == 1
    assert summary["actions"][0]["action"] == ACTION_BUY


def test_run_trading_holds_without_fresh_news(db, monkeypatch):
    _stub_signals(monkeypatch, [AAPL], news=[])  # no news at all
    broker = FakeBroker()

    run_trading(db, broker=broker, provider=StubProvider(90, 10))

    assert broker.submitted == []
    assert db.query(Trade).count() == 0


def test_run_trading_holds_on_low_confidence(db, monkeypatch):
    _stub_signals(monkeypatch, [AAPL])
    broker = FakeBroker()

    run_trading(db, broker=broker, provider=StubProvider(55, 45))

    assert broker.submitted == []
    assert db.query(Trade).count() == 0


def test_run_trading_closes_long_on_bearish(db, monkeypatch):
    _stub_signals(monkeypatch, [AAPL])
    db.add(Trade(asset="AAPL", side=SIDE_BUY, status=TRADE_OPEN,
                 entry_price=90.0, qty=10.0, model="m"))
    db.commit()
    broker = FakeBroker(positions=[long_position("AAPL", 10, 90)])

    run_trading(db, broker=broker, provider=StubProvider(20, 80))

    assert broker.closed == ["AAPL"]
    t = db.query(Trade).filter_by(status=TRADE_CLOSED).one()
    assert t.exit_price == 100.0
    assert t.pnl == 100.0          # (100-90)*10
    assert t.pnl_pct == 11.11
    assert t.close_reason == "signal"


def test_run_trading_dry_run_places_nothing(db, monkeypatch):
    _stub_signals(monkeypatch, [AAPL])
    broker = FakeBroker()

    summary = run_trading(db, broker=broker, provider=StubProvider(80, 20), dry_run=True)

    assert broker.submitted == []
    assert db.query(Trade).count() == 0
    assert db.query(EquitySnapshot).count() == 0  # dry run writes no equity
    assert summary["dry_run"] is True
    assert summary["actions"][0]["action"] == ACTION_BUY  # but only "intended"


def test_run_trading_skips_when_pending_order(db, monkeypatch):
    from app.broker.base import OrderResult

    _stub_signals(monkeypatch, [AAPL])
    broker = FakeBroker(open_orders=[OrderResult(id="9", symbol="AAPL", side="buy", status="new")])

    run_trading(db, broker=broker, provider=StubProvider(80, 20))

    assert broker.submitted == []
    assert db.query(Trade).count() == 0


def test_run_trading_crypto_trades_when_market_closed(db, monkeypatch):
    _stub_signals(monkeypatch, [BTC])
    broker = FakeBroker(market_open=False)

    run_trading(db, broker=broker, provider=StubProvider(80, 20))

    assert broker.submitted and broker.submitted[0][0] == "BTC"


# --------------------------------------------------------------------------- #
# run_sync() — reconcile + risk exits
# --------------------------------------------------------------------------- #
def test_run_sync_reconciles_open_trade(db, monkeypatch):
    monkeypatch.setattr(trader_mod, "fetch_price", lambda asset: 100.0)
    db.add(Trade(asset="AAPL", side=SIDE_BUY, status=TRADE_SUBMITTED))
    db.commit()
    broker = FakeBroker(positions=[long_position("AAPL", 10, 95)])

    summary = run_sync(db, broker=broker)

    t = db.query(Trade).one()
    assert t.status == TRADE_OPEN and t.entry_price == 95 and t.qty == 10
    assert summary["reconciled"] == 1
    assert db.query(EquitySnapshot).count() == 1


def test_run_sync_triggers_stop_loss(db, monkeypatch):
    monkeypatch.setattr(trader_mod, "fetch_price", lambda asset: 90.0)  # below stop
    db.add(Trade(asset="AAPL", side=SIDE_BUY, status=TRADE_OPEN,
                 entry_price=100.0, qty=10.0, stop_price=92.0))
    db.commit()
    broker = FakeBroker(positions=[long_position("AAPL", 10, 100)])

    summary = run_sync(db, broker=broker)

    assert broker.closed == ["AAPL"]
    t = db.query(Trade).one()
    assert t.status == TRADE_CLOSED and t.close_reason == "stop_loss"
    assert t.pnl == -100.0
    assert summary["closed"] == 1
