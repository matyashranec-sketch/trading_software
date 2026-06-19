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
    return parser


_COMMANDS = {
    "initdb": cmd_initdb,
    "trade": cmd_trade,
    "sync": cmd_sync,
    "predict": cmd_predict,
    "run": cmd_run,
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
