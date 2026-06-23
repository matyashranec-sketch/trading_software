"""Backtest harness for the order-flow strategy — the gate before going live.

Walks the decision timeframe (LTF) bar by bar and, at each closed bar, calls the
**same** :func:`app.engine.strategy.confluence.evaluate` on data available up to
that bar (no lookahead), enters at the next bar's open, and manages the position
against subsequent bars with taker fees + slippage. Reports win rate, profit
factor, expectancy (in R), max drawdown and return.

Honesty: order-book imbalance and live funding are **not** available historically
(no historical L2), so those checks simply don't count in the backtest — the
candle-derived order flow (CVD/delta/structure/volume) is what gets validated.
"""
from __future__ import annotations

import bisect
import logging
import time
from dataclasses import asdict, dataclass, field

from app.engine.strategy import confluence as C
from app.engine.strategy.confluence import MarketSnapshot, StrategyParams
from app.sources.market_data import Candle, fetch_klines_range, interval_ms

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestConfig:
    fee_rate: float = 0.0004        # taker fee per side (futures ≈ 0.04%)
    slippage: float = 0.0002        # adverse slippage per fill
    equity0: float = 10_000.0
    risk_pct: float = 0.005         # risk per trade (fraction of equity)
    max_leverage: float = 3.0       # notional cap = equity * leverage
    max_hold_bars: int = 96         # force-exit after this many LTF bars
    htf_window: int = 200
    mtf_window: int = 300
    ltf_window: int = 200


@dataclass
class BTTrade:
    direction: str
    entry_time: int
    entry: float
    stop: float
    target: float
    qty: float
    exit_time: int = 0
    exit: float = 0.0
    reason: str = ""
    pnl: float = 0.0
    r: float = 0.0
    hold_bars: int = 0


@dataclass
class BacktestReport:
    asset: str
    htf: str
    mtf: str
    ltf: str
    trades: int = 0
    wins: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_r: float = 0.0
    expectancy_r: float = 0.0
    return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    exposure_pct: float = 0.0
    avg_hold_bars: float = 0.0
    final_equity: float = 0.0
    params: dict = field(default_factory=dict)
    trade_log: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _closed_slice(candles: list[Candle], close_times: list[int], t: int,
                  window: int) -> list[Candle]:
    """Candles whose bar has fully closed by time ``t`` (no lookahead), last ``window``."""
    n = bisect.bisect_right(close_times, t)
    lo = max(0, n - window)
    return candles[lo:n]


def simulate(htf: list[Candle], mtf: list[Candle], ltf: list[Candle],
             params: StrategyParams | None = None,
             cfg: BacktestConfig | None = None,
             entry_range: tuple[int, int] | None = None) -> BacktestReport:
    """Core event loop over already-fetched candles (network-free → testable).

    ``entry_range`` restricts *new entries* to LTF indices ``[start, end)`` (used
    by the optimizer for train/test splits); positions are always managed over the
    full series.
    """
    p = params or StrategyParams()
    cfg = cfg or BacktestConfig()
    htf_ct = [c.close_time for c in htf]
    mtf_ct = [c.close_time for c in mtf]

    equity = cfg.equity0
    peak = equity
    max_dd = 0.0
    bars_in_market = 0
    trades: list[BTTrade] = []
    open_t: BTTrade | None = None

    for i in range(len(ltf) - 1):
        bar = ltf[i]
        nxt = ltf[i + 1]

        # --- manage an open position against this bar ---
        if open_t is not None:
            open_t.hold_bars += 1
            bars_in_market += 1
            hit = _exit_hit(open_t, bar)
            if hit is None and open_t.hold_bars >= cfg.max_hold_bars:
                hit = (bar.close, "max_hold")
            if hit is not None:
                px, reason = hit
                equity += _close(open_t, px, reason, cfg)
                trades.append(open_t)
                open_t = None
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)

        # --- look for a new entry (only when flat, within the allowed range) ---
        if open_t is None and (entry_range is None or entry_range[0] <= i < entry_range[1]):
            snap = MarketSnapshot(
                asset_symbol="BT", price=bar.close,
                htf=_closed_slice(htf, htf_ct, bar.close_time, cfg.htf_window),
                mtf=_closed_slice(mtf, mtf_ct, bar.close_time, cfg.mtf_window),
                ltf=ltf[max(0, i + 1 - cfg.ltf_window):i + 1],
            )
            res = C.evaluate(snap, p)
            if res.passed and res.stop_price is not None:
                open_t = _open(res, nxt, equity, cfg)

    report = _metrics(trades, cfg.equity0, equity, max_dd, bars_in_market, len(ltf))
    report.params = {**asdict(p)}
    return report


def _open(res, entry_bar: Candle, equity: float, cfg: BacktestConfig) -> BTTrade | None:
    is_long = res.direction == C.LONG
    fill = entry_bar.open * (1 + cfg.slippage) if is_long else entry_bar.open * (1 - cfg.slippage)
    stop = res.stop_price
    stop_dist = abs(fill - stop)
    if stop_dist <= 0:
        return None
    notional = min((equity * cfg.risk_pct) / (stop_dist / fill), equity * cfg.max_leverage)
    qty = notional / fill
    return BTTrade(direction=res.direction, entry_time=entry_bar.open_time, entry=fill,
                   stop=stop, target=res.target_price, qty=qty)


def _exit_hit(t: BTTrade, bar: Candle) -> tuple[float, str] | None:
    """Stop/target check for one bar. Stop is assumed first when both are touched."""
    if t.direction == C.LONG:
        if bar.low <= t.stop:
            return t.stop, "stop"
        if t.target and bar.high >= t.target:
            return t.target, "target"
    else:
        if bar.high >= t.stop:
            return t.stop, "stop"
        if t.target and bar.low <= t.target:
            return t.target, "target"
    return None


def _close(t: BTTrade, px: float, reason: str, cfg: BacktestConfig) -> float:
    """Close the trade; returns net PnL (after both fees). Sets trade fields."""
    fill = px * (1 - cfg.slippage) if t.direction == C.LONG else px * (1 + cfg.slippage)
    gross = t.qty * (fill - t.entry) if t.direction == C.LONG else t.qty * (t.entry - fill)
    fees = cfg.fee_rate * (t.qty * t.entry + t.qty * fill)
    net = gross - fees
    risk_amount = t.qty * abs(t.entry - t.stop)
    t.exit, t.exit_time, t.reason = round(fill, 8), 0, reason
    t.pnl = round(net, 4)
    t.r = round(net / risk_amount, 3) if risk_amount else 0.0
    return net


def _metrics(trades: list[BTTrade], eq0: float, eq: float, max_dd: float,
             bars_in_market: int, total_bars: int) -> BacktestReport:
    rep = BacktestReport(asset="", htf="", mtf="", ltf="")
    rep.trades = len(trades)
    rep.final_equity = round(eq, 2)
    rep.return_pct = round(100.0 * (eq - eq0) / eq0, 2) if eq0 else 0.0
    rep.max_drawdown_pct = round(100.0 * max_dd, 2)
    rep.exposure_pct = round(100.0 * bars_in_market / total_bars, 2) if total_bars else 0.0
    if not trades:
        return rep
    wins = [t for t in trades if t.pnl > 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in trades if t.pnl <= 0)
    rep.wins = len(wins)
    rep.win_rate = round(100.0 * len(wins) / len(trades), 2)
    rep.profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else float("inf")
    rep.avg_r = round(sum(t.r for t in trades) / len(trades), 3)
    rep.expectancy_r = rep.avg_r  # mean R per trade
    rep.avg_hold_bars = round(sum(t.hold_bars for t in trades) / len(trades), 1)
    rep.trade_log = [asdict(t) for t in trades]
    return rep


def run_backtest(asset_symbol: str, pair: str, *, days: int = 365,
                 htf: str = "4h", mtf: str = "1h", ltf: str = "15m",
                 params: StrategyParams | None = None, cfg: BacktestConfig | None = None,
                 futures: bool = True) -> BacktestReport:
    """Fetch history and run the simulation for one asset."""
    end = int(time.time() * 1000)
    start = end - days * 24 * 60 * 60 * 1000
    # pad HTF/MTF start so the first decision bar has enough closed history
    pad = (cfg or BacktestConfig()).htf_window * interval_ms(htf)
    htf_c = fetch_klines_range(pair, htf, start - pad, end, futures=futures)
    mtf_c = fetch_klines_range(pair, mtf, start - pad, end, futures=futures)
    ltf_c = fetch_klines_range(pair, ltf, start, end, futures=futures)
    logger.info("Backtest %s: %d htf / %d mtf / %d ltf candles", asset_symbol,
                len(htf_c), len(mtf_c), len(ltf_c))
    rep = simulate(htf_c, mtf_c, ltf_c, params, cfg)
    rep.asset, rep.htf, rep.mtf, rep.ltf = asset_symbol, htf, mtf, ltf
    return rep
