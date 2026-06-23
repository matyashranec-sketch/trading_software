"""Parameter-sweep optimizer with a train/test split.

Goal: find strategy settings that are **robust** — positive out-of-sample across
several assets — not curve-fit to one coin or one stretch of history. For each
combo it splits each asset's LTF history into a train slice and a held-out test
slice (entries restricted per slice via ``simulate(entry_range=...)``), then ranks
combos by how many assets stay profitable **in test**.

Candles are fetched once per asset/timeframe and reused across the whole grid, so
the sweep is just CPU. Honest caveat: a grid search can still overfit — prefer a
combo that works on several assets in test, and re-confirm with a plain backtest.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace

from app.engine.backtest import BacktestConfig, BacktestReport, simulate
from app.engine.strategy.confluence import StrategyParams
from app.sources.market_data import fetch_klines_range, interval_ms

logger = logging.getLogger(__name__)

# Decision-timeframe sets to compare: key -> (htf, mtf, ltf).
TF_SETS: dict[str, tuple[str, str, str]] = {
    "15m": ("4h", "1h", "15m"),
    "1h": ("1d", "4h", "1h"),
}


MODES = ("reversal", "momentum")


@dataclass(frozen=True)
class Combo:
    mode: str
    tf: str
    min_confluence: int
    reward_risk: float
    delta_strength_min: float
    atr_stop_mult: float

    def key(self) -> str:
        return (f"{self.mode}|{self.tf}|mc{self.min_confluence}|rr{self.reward_risk}"
                f"|ds{self.delta_strength_min}|sm{self.atr_stop_mult}")


def default_grid(base: StrategyParams) -> list[Combo]:
    combos: list[Combo] = []
    for mode in MODES:
        for tf in TF_SETS:
            for mc in (4, 5):
                for rr in (1.5, 2.0, 3.0):
                    for ds in (0.10, 0.20):
                        combos.append(Combo(mode, tf, mc, rr, ds, base.atr_stop_mult))
    return combos


def _params_for(base: StrategyParams, c: Combo) -> StrategyParams:
    return replace(base, mode=c.mode, min_confluence=c.min_confluence,
                   reward_risk=c.reward_risk, delta_strength_min=c.delta_strength_min,
                   atr_stop_mult=c.atr_stop_mult)


def _slim(r: BacktestReport) -> dict:
    return {"trades": r.trades, "win_rate": r.win_rate, "profit_factor": r.profit_factor,
            "expectancy_r": r.expectancy_r, "return_pct": r.return_pct,
            "max_drawdown_pct": r.max_drawdown_pct}


def _aggregate(per_asset: dict[str, dict], min_trades: int) -> dict:
    """Combine per-asset train/test slices into robustness metrics for one combo."""
    qualified = [a for a in per_asset.values() if a["test"]["trades"] >= min_trades]
    test_exps = [a["test"]["expectancy_r"] for a in qualified]
    train_exps = [a["train"]["expectancy_r"] for a in qualified]
    profitable = sum(1 for a in qualified if a["test"]["expectancy_r"] > 0)
    return {
        "assets_evaluated": len(qualified),
        "test_profitable_assets": profitable,
        "sum_test_expectancy_r": round(sum(test_exps), 3),
        "sum_train_expectancy_r": round(sum(train_exps), 3),
        "total_test_trades": sum(a["test"]["trades"] for a in per_asset.values()),
    }


def _rank(results: list[dict]) -> list[dict]:
    """Most robust first: more test-profitable assets, then higher summed test edge."""
    return sorted(
        results,
        key=lambda r: (r["aggregate"]["test_profitable_assets"],
                       r["aggregate"]["sum_test_expectancy_r"]),
        reverse=True,
    )


def evaluate_combo(combo: Combo, base: StrategyParams,
                   data: dict[str, dict[str, tuple]], cfg: BacktestConfig,
                   train_frac: float, min_trades: int) -> dict:
    params = _params_for(base, combo)
    per_asset: dict[str, dict] = {}
    for sym, by_tf in data.items():
        htf, mtf, ltf = by_tf[combo.tf]
        if len(ltf) < cfg.ltf_window + 50:
            continue
        split = int(len(ltf) * train_frac)
        warm = cfg.ltf_window
        train = simulate(htf, mtf, ltf, params, cfg, entry_range=(warm, split))
        test = simulate(htf, mtf, ltf, params, cfg, entry_range=(split, len(ltf)))
        per_asset[sym] = {"train": _slim(train), "test": _slim(test)}
    return {
        "combo": combo.key(), "mode": combo.mode, "tf": combo.tf,
        "min_confluence": combo.min_confluence, "reward_risk": combo.reward_risk,
        "delta_strength_min": combo.delta_strength_min, "atr_stop_mult": combo.atr_stop_mult,
        "aggregate": _aggregate(per_asset, min_trades), "assets": per_asset,
    }


def _fetch_set(pair: str, tf_set: tuple[str, str, str], days: int,
               cfg: BacktestConfig, futures: bool) -> tuple:
    htf_i, mtf_i, ltf_i = tf_set
    end = int(time.time() * 1000)
    start = end - days * 24 * 60 * 60 * 1000
    pad = cfg.htf_window * interval_ms(htf_i)
    return (
        fetch_klines_range(pair, htf_i, start - pad, end, futures=futures),
        fetch_klines_range(pair, mtf_i, start - pad, end, futures=futures),
        fetch_klines_range(pair, ltf_i, start, end, futures=futures),
    )


def run(symbols: list[str], pairs: list[str], *, days: int = 365,
        base: StrategyParams | None = None, cfg: BacktestConfig | None = None,
        futures: bool = True, grid: list[Combo] | None = None,
        train_frac: float = 0.67, min_trades: int = 15) -> dict:
    base = base or StrategyParams()
    cfg = cfg or BacktestConfig()
    grid = grid or default_grid(base)

    # fetch candles once per asset per timeframe set (reused across the whole grid)
    data: dict[str, dict[str, tuple]] = {}
    for sym, pair in zip(symbols, pairs):
        data[sym] = {}
        for tf, tf_set in TF_SETS.items():
            data[sym][tf] = _fetch_set(pair, tf_set, days, cfg, futures)
        logger.info("Fetched history for %s", sym)

    results: list[dict] = []
    for n, combo in enumerate(grid, 1):
        results.append(evaluate_combo(combo, base, data, cfg, train_frac, min_trades))
        logger.info("Combo %d/%d done: %s", n, len(grid), combo.key())

    ranked = _rank(results)
    return {
        "days": days, "train_frac": train_frac, "min_trades": min_trades,
        "combos": len(grid), "best": ranked[0] if ranked else None,
        "ranked": ranked,
    }
