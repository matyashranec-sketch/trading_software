"""Command-line entry point for the trading bot.

Production heartbeat = GitHub Actions cron (every ~2h) running:
    python -m app.cli sync      # reconcile positions, exits, equity, scoring
    python -m app.cli trade     # generate signals + place trades

Local / dev:
    python -m app.cli initdb        # create tables (local SQLite or Supabase)
    python -m app.cli trade --dry-run
    python -m app.cli predict       # refresh multi-model accuracy leaderboard
    python -m app.cli run           # blocking local scheduler (every N hours)
"""
from __future__ import annotations

import argparse
import json
import logging

from app.db import init_db, session_scope


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_initdb(_args: argparse.Namespace) -> None:
    init_db()
    print("Database initialized.")


def cmd_trade(args: argparse.Namespace) -> None:
    from app.engine.trader import run_trading

    init_db()
    with session_scope() as session:
        summary = run_trading(session, dry_run=args.dry_run)
    _print(summary)


def cmd_sync(_args: argparse.Namespace) -> None:
    from app.engine.trader import run_sync

    init_db()
    with session_scope() as session:
        summary = run_sync(session)
    _print(summary)


def cmd_predict(_args: argparse.Namespace) -> None:
    from app.engine.predictor import run_predictions

    init_db()
    with session_scope() as session:
        summary = run_predictions(session)
    _print(summary)


def cmd_run(_args: argparse.Namespace) -> None:
    from app.scheduler import run_forever

    run_forever()


def cmd_backtest(args: argparse.Namespace) -> None:
    """Validate the order-flow strategy on historical klines (the go-live gate)."""
    import time as _time
    from pathlib import Path

    from app.config import ASSETS, ASSETS_BY_SYMBOL, DATA_DIR, get_settings
    from app.engine.backtest import BacktestConfig, run_backtest
    from app.engine.strategy.engine import params_from_settings

    settings = get_settings()
    params = params_from_settings(settings)
    cfg = BacktestConfig()
    futures = settings.broker == "binance_futures"
    htf = args.htf or getattr(settings, "strategy_htf", "4h")
    mtf = args.mtf or getattr(settings, "strategy_mtf", "1h")
    ltf = args.ltf or getattr(settings, "strategy_ltf", "15m")

    symbols = [args.asset] if args.asset else [a.symbol for a in ASSETS if a.tradable]
    out_dir = Path(DATA_DIR) / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    for sym in symbols:
        asset = ASSETS_BY_SYMBOL.get(sym)
        if asset is None:
            print(f"unknown asset {sym!r}")
            continue
        pair = asset.binance_symbol or f"{sym}USDT"
        rep = run_backtest(sym, pair, days=args.days, htf=htf, mtf=mtf, ltf=ltf,
                           params=params, cfg=cfg, futures=futures)
        path = out_dir / f"{sym}_{ltf}_{int(_time.time())}.json"
        path.write_text(json.dumps(rep.to_dict(), indent=2, default=str))
        summaries.append({
            "asset": sym, "trades": rep.trades, "win_rate": rep.win_rate,
            "profit_factor": rep.profit_factor, "expectancy_r": rep.expectancy_r,
            "return_pct": rep.return_pct, "max_drawdown_pct": rep.max_drawdown_pct,
            "exposure_pct": rep.exposure_pct, "report": str(path),
        })
    _print({"days": args.days, "htf": htf, "mtf": mtf, "ltf": ltf, "results": summaries})


def cmd_liquidate(args: argparse.Namespace) -> None:
    from app.broker import get_broker

    broker = get_broker()
    liquidate = getattr(broker, "liquidate_all", None)
    if liquidate is None:
        print("liquidate is only supported by the Binance broker.")
        return
    _print(liquidate(dry_run=args.dry_run))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="News-driven trading bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("initdb", help="create database tables")
    p_trade = sub.add_parser("trade", help="generate signals and place trades")
    p_trade.add_argument(
        "--dry-run", action="store_true",
        help="compute intended orders but do NOT place them",
    )
    sub.add_parser("sync", help="reconcile positions, apply exits, record equity, score signals")
    sub.add_parser("predict", help="refresh the multi-model accuracy leaderboard")
    sub.add_parser("run", help="blocking local scheduler (every run_interval_hours)")
    p_liq = sub.add_parser("liquidate", help="market-sell all non-USDT balances into USDT")
    p_liq.add_argument(
        "--dry-run", action="store_true",
        help="show what would be sold, but place no orders",
    )
    p_bt = sub.add_parser("backtest", help="backtest the order-flow strategy on history")
    p_bt.add_argument("--asset", help="single asset symbol (default: all tradable)")
    p_bt.add_argument("--days", type=int, default=365, help="lookback window in days")
    p_bt.add_argument("--htf", help="trend timeframe (default from config, e.g. 4h)")
    p_bt.add_argument("--mtf", help="structure timeframe (default from config, e.g. 1h)")
    p_bt.add_argument("--ltf", help="decision timeframe (default from config, e.g. 15m)")
    return parser


_COMMANDS = {
    "initdb": cmd_initdb,
    "trade": cmd_trade,
    "sync": cmd_sync,
    "predict": cmd_predict,
    "run": cmd_run,
    "liquidate": cmd_liquidate,
    "backtest": cmd_backtest,
}


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    _COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
