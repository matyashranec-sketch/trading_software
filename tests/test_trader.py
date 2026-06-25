import app.engine.trader as trader_mod
from app.broker.base import Account, Position
from app.config import Asset, Settings
from app.engine.strategy.confluence import LONG, SHORT, ConfluenceResult
from app.engine.strategy.engine import StrategySignal
from app.engine.trader import (
    ACTION_BUY,
    ACTION_CLOSE,
    ACTION_HOLD,
    ACTION_SHORT,
    confirm_setup,
    decide,
    reset_paper_data,
    run_sync,
    run_trading,
    size_by_risk,
    virtual_account,
)
from app.llm.base import PredictionResult
from app.models import (
    BEARISH,
    BULLISH,
    SIDE_BUY,
    SIDE_SELL,
    TRADE_CLOSED,
    TRADE_OPEN,
    TRADE_SUBMITTED,
    Evaluation,
    EquitySnapshot,
    Prediction,
    Trade,
    utcnow,
)
from tests.conftest import FakeBroker, long_position, short_position

BTC = Asset("BTC", "Bitcoin", "crypto", coingecko_id="bitcoin", binance_symbol="BTCUSDT")


def _approve(asset, sig):
    """Confirmer stub that endorses the setup in its own direction."""
    if sig.is_long:
        v = PredictionResult(bullish_prob=80.0, bearish_prob=20.0, rationale="confirmed")
    else:
        v = PredictionResult(bullish_prob=20.0, bearish_prob=80.0, rationale="confirmed")
    return True, v


def _reject(asset, sig):
    return False, PredictionResult(bullish_prob=45.0, bearish_prob=55.0, rationale="too weak")


class _FakeProvider:
    """Minimal LLM provider for confirm_setup() tests (no network)."""

    def __init__(self, models=("m",), verdict=None, raise_exc=False):
        self._models = list(models)
        self._verdict = verdict
        self._raise = raise_exc

    def available_models(self):
        return list(self._models)

    def judge_setup(self, model, asset, setup):
        if self._raise:
            raise RuntimeError("boom")
        return self._verdict


def make_signal(direction=LONG, *, passed=True, price=100.0, stop=None, target=None,
                asset=BTC, score=5, max_score=6, db=None):
    if direction == LONG:
        stop = 95.0 if stop is None else stop
        target = 110.0 if target is None else target
        bull, bear, pdir = score / max_score * 100, 0.0, BULLISH
    else:
        stop = 105.0 if stop is None else stop
        target = 90.0 if target is None else target
        bull, bear, pdir = 0.0, score / max_score * 100, BEARISH
    res = ConfluenceResult(direction=direction, passed=passed, score=score, max_score=max_score,
                           checks={}, stop_price=stop, target_price=target, rationale="setup")
    pred = Prediction(asset=asset.symbol, model="orderflow-v1", direction=pdir,
                      bullish_prob=bull, bearish_prob=bear, price_at_prediction=price,
                      rationale="setup", news_snapshot="{}")
    if db is not None:
        db.add(pred)
        db.flush()
    return StrategySignal(asset=asset, prediction=pred, result=res)


# --------------------------------------------------------------------------- #
# decide() — pure decision logic
# --------------------------------------------------------------------------- #
def test_decide_buys_on_passing_long():
    assert decide(make_signal(LONG), None, 0, Settings()).action == ACTION_BUY


def test_decide_holds_when_confluence_fails():
    d = decide(make_signal(LONG, passed=False), None, 0, Settings())
    assert d.action == ACTION_HOLD


def test_decide_shorts_on_passing_short_when_enabled():
    d = decide(make_signal(SHORT), None, 0, Settings(allow_short=True))
    assert d.action == ACTION_SHORT


def test_decide_short_disabled_holds_when_flat():
    d = decide(make_signal(SHORT), None, 0, Settings(allow_short=False))
    assert d.action == ACTION_HOLD


def test_decide_short_signal_closes_existing_long():
    holding = long_position("BTC", 1, 100)
    d = decide(make_signal(SHORT), holding, 1, Settings(allow_short=True))
    assert d.action == ACTION_CLOSE


def test_decide_long_signal_closes_existing_short():
    holding = short_position("BTC", 1, 100)
    d = decide(make_signal(LONG), holding, 1, Settings())
    assert d.action == ACTION_CLOSE


def test_decide_holds_when_already_long():
    holding = long_position("BTC", 1, 100)
    d = decide(make_signal(LONG), holding, 1, Settings())
    assert d.action == ACTION_HOLD and "already long" in d.reason


def test_decide_respects_max_open_positions():
    d = decide(make_signal(LONG), None, 5, Settings(max_open_positions=5))
    assert d.action == ACTION_HOLD and "max open" in d.reason


# --------------------------------------------------------------------------- #
# size_by_risk()
# --------------------------------------------------------------------------- #
def test_size_by_risk_from_stop_distance():
    acct = Account(equity=10_000, cash=10_000, buying_power=10_000)
    sig = make_signal(LONG, price=100, stop=95)  # risk 0.5% = $50, stop dist 5 -> $1000
    s = Settings(risk_per_trade_pct=0.005, max_position_pct=0.10, futures_leverage=3)
    assert size_by_risk(acct, sig, s) == 1_000.0


def test_size_by_risk_capped_by_position_limit():
    acct = Account(equity=10_000, cash=10_000, buying_power=10_000)
    sig = make_signal(LONG, price=100, stop=99.9)  # tiny stop -> huge desired notional
    s = Settings(risk_per_trade_pct=0.005, max_position_pct=0.10, futures_leverage=3)
    assert size_by_risk(acct, sig, s) == 3_000.0  # equity*0.10*3


def test_size_by_risk_capped_by_margin_buffer():
    acct = Account(equity=10_000, cash=100, buying_power=100)
    sig = make_signal(LONG, price=100, stop=95)
    s = Settings(risk_per_trade_pct=0.005, max_position_pct=0.10,
                 cash_buffer_pct=0.10, futures_leverage=3)
    assert size_by_risk(acct, sig, s) == 270.0  # cash*3*(1-0.10)


# --------------------------------------------------------------------------- #
# run_trading() — end to end with a fake broker (signals injected, no network)
# --------------------------------------------------------------------------- #
def test_run_trading_opens_long(db):
    broker = FakeBroker(equity=10_000, cash=10_000)
    sig = make_signal(LONG, price=100, stop=95, target=110, db=db)

    summary = run_trading(db, broker=broker, signals=[sig], confirmer=_approve)

    assert broker.submitted == [("BTC", "buy", 1_000.0, None)]
    t = db.query(Trade).one()
    assert t.side == SIDE_BUY and t.status == TRADE_SUBMITTED
    assert t.notional == 1_000.0 and t.entry_price == 100.0
    assert t.stop_price == 95.0 and t.take_profit == 110.0
    assert t.model == "orderflow-v1" and t.prediction_id is not None
    assert db.query(EquitySnapshot).count() == 1
    assert summary["actions"][0]["action"] == ACTION_BUY


def test_run_trading_opens_short(db):
    broker = FakeBroker(equity=10_000, cash=10_000)
    sig = make_signal(SHORT, price=100, stop=105, target=90, db=db)

    run_trading(db, broker=broker, signals=[sig], confirmer=_approve)

    assert broker.submitted == [("BTC", "sell", 1_000.0, None)]
    t = db.query(Trade).one()
    assert t.side == SIDE_SELL and t.stop_price == 105.0 and t.take_profit == 90.0


def test_run_trading_holds_when_not_passed(db):
    broker = FakeBroker()
    run_trading(db, broker=broker, signals=[make_signal(LONG, passed=False, db=db)])
    assert broker.submitted == []
    assert db.query(Trade).count() == 0


def test_run_trading_closes_long_on_short_signal(db):
    db.add(Trade(asset="BTC", side=SIDE_BUY, status=TRADE_OPEN,
                 entry_price=90.0, qty=10.0, model="orderflow-v1"))
    db.commit()
    broker = FakeBroker(positions=[long_position("BTC", 10, 90)])

    run_trading(db, broker=broker, signals=[make_signal(SHORT, price=100, db=db)])

    assert broker.closed == ["BTC"]
    t = db.query(Trade).filter_by(status=TRADE_CLOSED).one()
    assert t.exit_price == 100.0 and t.pnl == 100.0  # (100-90)*10
    assert t.close_reason == "signal"


def test_run_trading_dry_run_places_nothing(db):
    broker = FakeBroker()
    summary = run_trading(db, broker=broker, signals=[make_signal(LONG, db=db)],
                          dry_run=True, confirmer=_approve)

    assert broker.submitted == [] and db.query(Trade).count() == 0
    assert db.query(EquitySnapshot).count() == 0
    assert summary["dry_run"] is True
    assert summary["actions"][0]["action"] == ACTION_BUY  # intended only


def test_run_trading_skips_when_pending_order(db):
    from app.broker.base import OrderResult

    broker = FakeBroker(open_orders=[OrderResult(id="9", symbol="BTC", side="buy", status="new")])
    run_trading(db, broker=broker, signals=[make_signal(LONG, db=db)])

    assert broker.submitted == [] and db.query(Trade).count() == 0


# --------------------------------------------------------------------------- #
# run_sync() — reconcile + risk exits
# --------------------------------------------------------------------------- #
def test_run_sync_reconciles_open_trade(db, monkeypatch):
    monkeypatch.setattr(trader_mod, "fetch_price", lambda asset: 100.0)
    db.add(Trade(asset="BTC", side=SIDE_BUY, status=TRADE_SUBMITTED))
    db.commit()
    broker = FakeBroker(positions=[long_position("BTC", 10, 95)])

    summary = run_sync(db, broker=broker)

    t = db.query(Trade).one()
    assert t.status == TRADE_OPEN and t.entry_price == 95 and t.qty == 10
    assert summary["reconciled"] == 1
    assert db.query(EquitySnapshot).count() == 1


def test_run_sync_triggers_stop_loss(db, monkeypatch):
    monkeypatch.setattr(trader_mod, "fetch_price", lambda asset: 90.0)  # below stop
    db.add(Trade(asset="BTC", side=SIDE_BUY, status=TRADE_OPEN,
                 entry_price=100.0, qty=10.0, stop_price=92.0))
    db.commit()
    broker = FakeBroker(positions=[long_position("BTC", 10, 100)])

    summary = run_sync(db, broker=broker)

    assert broker.closed == ["BTC"]
    t = db.query(Trade).one()
    assert t.status == TRADE_CLOSED and t.close_reason == "stop_loss"
    assert t.pnl == -100.0 and summary["closed"] == 1


def test_run_sync_time_stop_closes_stale_position(db, monkeypatch):
    from datetime import timedelta

    from app.models import utcnow

    monkeypatch.setattr(trader_mod, "fetch_price", lambda asset: 100.0)  # no stop/take hit
    old = utcnow() - timedelta(hours=48)  # older than 96 bars × 15m = 24h
    db.add(Trade(asset="BTC", side=SIDE_BUY, status=TRADE_OPEN, created_at=old,
                 entry_price=100.0, qty=10.0))
    db.commit()
    broker = FakeBroker(positions=[long_position("BTC", 10, 100)])

    summary = run_sync(db, broker=broker)

    assert broker.closed == ["BTC"]
    t = db.query(Trade).one()
    assert t.status == TRADE_CLOSED and t.close_reason == "max_hold"
    assert summary["closed"] == 1


def test_run_sync_triggers_take_profit_on_short(db, monkeypatch):
    monkeypatch.setattr(trader_mod, "fetch_price", lambda asset: 90.0)  # below short target
    db.add(Trade(asset="BTC", side=SIDE_SELL, status=TRADE_OPEN,
                 entry_price=100.0, qty=10.0, stop_price=105.0, take_profit=92.0))
    db.commit()
    broker = FakeBroker(positions=[short_position("BTC", 10, 100)])

    summary = run_sync(db, broker=broker)

    assert broker.closed == ["BTC"]
    t = db.query(Trade).one()
    assert t.close_reason == "take_profit" and t.pnl == 100.0  # (100-90)*10 short
    assert summary["closed"] == 1


# --------------------------------------------------------------------------- #
# virtual_account() — equity tracked as a clean $10k paper book
# --------------------------------------------------------------------------- #
def test_virtual_account_flat_is_starting_equity(db):
    acct = virtual_account(db, [], Settings(paper_starting_equity=10_000, futures_leverage=3))
    assert acct.equity == 10_000.0 and acct.cash == 10_000.0


def test_virtual_account_counts_realized_and_unrealized(db):
    db.add(Trade(asset="BTC", side=SIDE_BUY, status=TRADE_CLOSED, pnl=250.0))
    db.add(Trade(asset="BTC", side=SIDE_SELL, status=TRADE_CLOSED, pnl=-50.0))
    db.commit()
    pos = Position(symbol="ETH", qty=1.0, side=LONG, avg_entry_price=2_000.0,
                   market_value=2_000.0, unrealized_pl=100.0)
    acct = virtual_account(db, [pos], Settings(paper_starting_equity=10_000, futures_leverage=2))
    # wallet = 10000 + (250 - 50) = 10200; equity = 10200 + 100 = 10300
    # used_margin = 2000 / 2 = 1000; cash = 10200 - 1000 = 9200
    assert acct.equity == 10_300.0
    assert acct.cash == 9_200.0


def test_run_trading_records_virtual_equity_not_broker_balance(db):
    broker = FakeBroker(equity=500_000, cash=500_000)  # testnet's inflated fake balance
    run_trading(db, broker=broker, signals=[make_signal(LONG, db=db)], confirmer=_approve)
    snap = db.query(EquitySnapshot).one()
    assert snap.equity == 10_000.0  # virtual $10k base, not the broker's 500k


# --------------------------------------------------------------------------- #
# LLM confirmation gate (second gate over the order-flow signal)
# --------------------------------------------------------------------------- #
def test_run_trading_holds_when_llm_rejects(db):
    broker = FakeBroker(equity=10_000, cash=10_000)
    summary = run_trading(db, broker=broker, signals=[make_signal(LONG, db=db)], confirmer=_reject)

    assert broker.submitted == [] and db.query(Trade).count() == 0
    assert summary["actions"][0]["action"] == ACTION_HOLD
    assert "LLM" in summary["actions"][0]["reason"]


def test_run_trading_records_llm_rationale_on_trade(db):
    broker = FakeBroker(equity=10_000, cash=10_000)
    run_trading(db, broker=broker, signals=[make_signal(LONG, db=db)], confirmer=_approve)

    t = db.query(Trade).one()
    assert "LLM" in t.rationale and "confirmed" in t.rationale


def test_confirm_setup_disabled_is_fail_open(db):
    ok, verdict = confirm_setup(BTC, make_signal(LONG),
                                settings=Settings(require_llm_confirmation=False))
    assert ok is True and verdict is None


def test_confirm_setup_approves_above_threshold():
    prov = _FakeProvider(verdict=PredictionResult(bullish_prob=70, bearish_prob=30, rationale="ok"))
    ok, verdict = confirm_setup(BTC, make_signal(LONG), provider=prov,
                                settings=Settings(llm_confirm_min=60))
    assert ok is True and verdict.bullish_prob == 70


def test_confirm_setup_rejects_below_threshold():
    prov = _FakeProvider(verdict=PredictionResult(bullish_prob=55, bearish_prob=45, rationale="meh"))
    ok, _ = confirm_setup(BTC, make_signal(LONG), provider=prov,
                          settings=Settings(llm_confirm_min=60))
    assert ok is False


def test_confirm_setup_fail_open_without_models():
    ok, verdict = confirm_setup(BTC, make_signal(LONG), provider=_FakeProvider(models=()),
                                settings=Settings())
    assert ok is True and verdict is None


def test_confirm_setup_fail_open_on_error():
    ok, verdict = confirm_setup(BTC, make_signal(LONG), provider=_FakeProvider(raise_exc=True),
                                settings=Settings())
    assert ok is True and verdict is None


# --------------------------------------------------------------------------- #
# reset_paper_data() — clean slate
# --------------------------------------------------------------------------- #
def test_reset_paper_data_wipes_everything(db):
    pred = Prediction(asset="BTC", model="orderflow-v1", direction=BULLISH,
                      bullish_prob=80, bearish_prob=20, price_at_prediction=100.0)
    db.add(pred)
    db.flush()
    db.add(Evaluation(prediction_id=pred.id, horizon="24h",
                      target_eval_time=utcnow(), status="pending"))
    db.add(Trade(asset="BTC", side=SIDE_BUY, status=TRADE_CLOSED, pnl=10.0))
    db.add(EquitySnapshot(equity=10_000, cash=10_000, buying_power=10_000))
    db.commit()

    counts = reset_paper_data(db)

    assert counts == {"evaluations": 1, "trades": 1, "predictions": 1, "equity_snapshots": 1}
    assert db.query(Trade).count() == 0 and db.query(Prediction).count() == 0
    assert db.query(Evaluation).count() == 0 and db.query(EquitySnapshot).count() == 0


def test_reset_paper_data_dry_run_keeps_rows(db):
    db.add(Trade(asset="BTC", side=SIDE_BUY, status=TRADE_CLOSED, pnl=10.0))
    db.commit()

    counts = reset_paper_data(db, dry_run=True)

    assert counts["trades"] == 1 and db.query(Trade).count() == 1
