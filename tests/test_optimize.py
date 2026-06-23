"""Tests for the optimizer's pure aggregation + ranking (robust selection)."""
from app.engine.optimize import Combo, _aggregate, _rank, default_grid
from app.engine.strategy.confluence import StrategyParams


def _asset(train_r, test_r, test_trades, train_trades=40):
    return {
        "train": {"expectancy_r": train_r, "trades": train_trades},
        "test": {"expectancy_r": test_r, "trades": test_trades},
    }


def test_aggregate_respects_min_trades_and_counts_profitable():
    per_asset = {
        "A": _asset(0.2, 0.10, 30),    # qualifies, profitable in test
        "B": _asset(-0.1, -0.05, 25),  # qualifies, not profitable
        "C": _asset(0.3, 0.40, 5),     # too few test trades -> excluded from edge stats
    }
    agg = _aggregate(per_asset, min_trades=15)
    assert agg["assets_evaluated"] == 2          # A, B (C excluded)
    assert agg["test_profitable_assets"] == 1    # only A
    assert agg["sum_test_expectancy_r"] == 0.05  # 0.10 - 0.05
    assert agg["total_test_trades"] == 60        # counts all assets (30+25+5)


def test_rank_prefers_more_profitable_then_higher_edge():
    mk = lambda prof, s: {"aggregate": {"test_profitable_assets": prof, "sum_test_expectancy_r": s}}
    a, b, c = mk(2, 0.1), mk(3, -0.2), mk(2, 0.5)
    ranked = _rank([a, b, c])
    assert [r["aggregate"]["test_profitable_assets"] for r in ranked] == [3, 2, 2]
    assert ranked[1] is c  # tie on 2 -> higher summed test edge first


def test_default_grid_spans_modes_and_timeframes():
    combos = default_grid(StrategyParams())
    assert {"15m", "1h"} <= {c.tf for c in combos}
    assert {"reversal", "momentum"} <= {c.mode for c in combos}
    assert len(combos) == len({c.key() for c in combos})  # keys unique
