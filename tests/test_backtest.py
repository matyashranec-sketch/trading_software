"""Tests for the backtest event loop: entry-next-open, exits, fee/R accounting."""
from app.engine import backtest as B
from app.engine.strategy import confluence as C
from app.engine.strategy.confluence import ConfluenceResult
from app.sources.market_data import Candle


def mk(t, o, h, low, c):
    return Candle(open_time=t, open=o, high=h, low=low, close=c, volume=100.0,
                  close_time=t + 1, quote_volume=100.0 * c, trades=10, taker_buy_base=60.0)


def _ctx():
    htf = [mk(i, 100, 101, 99, 100) for i in range(5)]
    mtf = [mk(i, 100, 101, 99, 100) for i in range(5)]
    ltf = [
        mk(0, 100, 101, 99, 100),    # 0 decision bar (entry fires here)
        mk(2, 100, 101, 99, 100),    # 1 entry bar (fill ~100), no exit
        mk(4, 100, 111, 99, 110),    # 2 target 110 hit
        mk(6, 110, 112, 108, 111),   # 3 filler
        mk(8, 111, 112, 110, 111),   # 4 filler
    ]
    return htf, mtf, ltf


def test_winning_long_trade_accounts_fees_and_r(monkeypatch):
    fired = {"done": False}

    def stub(snap, params):
        if not fired["done"]:
            fired["done"] = True
            return ConfluenceResult(direction=C.LONG, passed=True, score=5, max_score=6,
                                    checks={}, stop_price=95.0, target_price=110.0)
        return ConfluenceResult(direction=None, passed=False, score=0, max_score=0, checks={})

    monkeypatch.setattr(B.C, "evaluate", stub)
    htf, mtf, ltf = _ctx()
    rep = B.simulate(htf, mtf, ltf)

    assert rep.trades == 1 and rep.wins == 1 and rep.win_rate == 100.0
    t = rep.trade_log[0]
    assert t["reason"] == "target"
    assert t["pnl"] > 0 and rep.final_equity > B.BacktestConfig().equity0
    assert 1.5 < t["r"] < 2.2          # ~2R target, minus fees/slippage
    assert rep.profit_factor == float("inf")  # no losers


def test_entry_range_gates_new_entries(monkeypatch):
    # evaluate always passes, but an empty entry range must block all entries
    monkeypatch.setattr(
        B.C, "evaluate",
        lambda snap, params: ConfluenceResult(direction=C.LONG, passed=True, score=5,
                                              max_score=6, checks={}, stop_price=95.0,
                                              target_price=110.0),
    )
    htf, mtf, ltf = _ctx()
    assert B.simulate(htf, mtf, ltf, entry_range=(0, 0)).trades == 0


def test_no_signal_means_no_trades(monkeypatch):
    monkeypatch.setattr(
        B.C, "evaluate",
        lambda snap, params: ConfluenceResult(direction=None, passed=False, score=0,
                                              max_score=0, checks={}),
    )
    htf, mtf, ltf = _ctx()
    rep = B.simulate(htf, mtf, ltf)
    assert rep.trades == 0 and rep.return_pct == 0.0
