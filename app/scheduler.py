"""Optional local scheduler.

Production runs the bot via GitHub Actions cron (``sync`` then ``trade`` every
~2h). This is only for running the same cycle on your own machine:

    python -m app.cli run

It runs one cycle immediately, then every ``run_interval_hours``.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db import init_db, session_scope
from app.engine.trader import run_sync, run_trading

logger = logging.getLogger(__name__)


def _cycle() -> None:
    try:
        with session_scope() as session:
            run_sync(session)
        with session_scope() as session:
            summary = run_trading(session)
        logger.info("Trading cycle done: %d signals, %d actions.",
                    summary.get("signals", 0), len(summary.get("actions", [])))
    except Exception:
        logger.exception("Trading cycle failed")


def run_forever() -> None:
    settings = get_settings()
    init_db()
    _cycle()  # run once immediately on start

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        _cycle,
        IntervalTrigger(hours=settings.run_interval_hours),
        id="cycle",
        replace_existing=True,
    )
    logger.info("Local scheduler started — cycle every %d h. Ctrl-C to stop.",
                settings.run_interval_hours)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
